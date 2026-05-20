# 3 services

#   1. Talk to the LLM API (extract intent, generate steps, generate messages)
#   2. Calculate risk score via a local rules engine
#   3. Create and persist the full task record atomically

import json
import logging
import requests
from django.conf import settings
from django.db import transaction
import os
from google import genai
from google.genai import types
from google.genai import errors

from .models import (
    Task,
    TaskStep,
    Message,
    StatusHistory,
    MessageChannel,
    INTENT_TEAM_MAP,
)
from .prompts import (
    INTENT_EXTRACTION_PROMPT,
    STEP_GENERATION_PROMPT,
    MESSAGE_GENERATION_PROMPT,
)
logger = logging.getLogger(__name__)

"""
LLM CLIENT
"""
def _call_llm(system_prompt:str, user_message: str) -> str:
    """
    Single entry point for all LLM calls.
    Reads provider config from settings so swapping providers
    only requires changing .env — no code changes needed.
 
    Returns the raw text response from the model.
    Raises RuntimeError if the call fails.
    """
    GEMINI_API_KEY = settings.LLM_API_KEY

    if not GEMINI_API_KEY:
        raise RuntimeError("LLM_API_KEY is not set in your .env file.")
    
    # Initialize the client explicitly with the key from your settings
    client = genai.Client(api_key=GEMINI_API_KEY)

    try:
        # Build configuration for system instructions and token limits
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=1024,
        )

        # Execute the call using the official SDK parameters
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=user_message,
            config=config
        )
        
        if not response.text:
            raise RuntimeError("Gemini returned an empty response.")
            
        return response.text.strip()

    # Catch specific Gemini API errors (similar to HTTPError)
    except errors.APIError as e:
        raise RuntimeError(f"Gemini API returned an error: {e.code} — {e.message}")
    # Catch any other unexpected exceptions
    except Exception as e:
        raise RuntimeError(f"LLM request failed: {str(e)}")

def _parse_json_response(raw: str, label: str) -> dict | list:
      
    cleaned = raw.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse %s JSON: %s\nRaw response: %s", label, e, raw)
        raise RuntimeError(f"Could not parse {label} response from AI. Raw: {raw[:200]}")

"""
Extract intent and entities
"""
def extract_intent(message: str) -> dict:
    raw = _call_llm(system_prompt=INTENT_EXTRACTION_PROMPT, user_message=message)
    print(raw)
    result = _parse_json_response(raw, "intent extraction")

    # Validate required keys are present
    required = {"intent", "entities", "confidence"}
    missing = required - set(result.keys())
    if missing:
        raise RuntimeError(f"Intent extraction response missing keys: {missing}")

    return result

#3. Risk Score Calculation
def calculate_risk_score(intent: str, entities: dict) -> int:
    risk = 0

    amount_raw = entities.get("amount")
    if amount_raw and isinstance(amount_raw, (int, float, str)):
        try:
            amount = int(float(amount_raw))
        except (ValueError, TypeError):
            amount = 0
    else:
        amount = 0

    print(type(amount))
    if amount > 100000:
       risk += 30
    elif amount > 50000:
        risk += 20
    elif amount > 10000:
        risk += 10 

    # Intent-based risk
    high_risk_intents = ["land_title", "property_purchase", "legal_document"]
    medium_risk_intents = ["urgent_payment", "emergency_funds"]
    
    if intent in high_risk_intents:
        risk += 30
    elif intent in medium_risk_intents:
        risk += 15

     # Urgency increases risk
    if entities.get("urgency") == "high":
        risk += 20
    elif entities.get("urgency") == "medium":
        risk += 10

    # Recipient verification
    if not entities.get("recipient_verified", False):
        risk += 25
    
    # Customer history (lower risk for returning customers)
    if entities.get("returning_customer"):
        risk -= 20
    if entities.get("clean_history"):
        risk -= 15
    
    return max(0, min(100, risk))

#4.  Generate Steps
def generate_steps(intent, entities):
    #Leverages llm to generate ordered list of fulfilemt steps specific to intent
    user_message = (
        f"Intent: {intent}\n"
        f"Entities: {json.dumps(entities, indent=2)}\n\n"
        "Generate the fulfilment steps for this task."
    )
    raw = _call_llm(STEP_GENERATION_PROMPT, user_message)
    steps = _parse_json_response(raw, "step generation")

    if not isinstance(steps, list) or len(steps) == 0:
        raise RuntimeError("Step generation returned empty")
    
    return [str(step) for step in steps]

def generate_messages(task_code: str, intent: str, entities: dict, risk_score: int, assigned_team: str) -> dict:
    """
    Asks the LLM to generate three confirmation messages: whatsapp, email, sms
    Returnsa a dic with keys:whatsapp, email, sms
    """

    user_message = (
        f"Task code: {task_code}\n"
        f"Intent: {intent}\n"
        f"Entities: {json.dumps(entities, indent=2)}\n"
        f"Risk level: {'high' if risk_score > 60 else 'medium' if risk_score > 30 else 'low'} ({risk_score}/100)\n"
        "Assigned team: {assigned_team}\n\n"
        "Generate the three confirmation messages." 
    )

    raw = _call_llm(MESSAGE_GENERATION_PROMPT, user_message)
    messages = _parse_json_response(raw, "message generation")

    required_channels = {"whatsapp", "email", "sms"}
    missing = required_channels - set(messages.keys())
    if missing:
        raise RuntimeError(f"Message generation response missing channels: {missing}")
    
    return messages

def assign_team(intent: str):
    # Maps intent to the responsible team 
    # Fallback to Operations for unmapped intent
    return INTENT_TEAM_MAP.get(intent, "Operations")


def process_task(raw_message: str) -> Task:
    """
    Full pipeline for a single customer request
    Steps:
      1. Extract intent and entities via LLM
      2. Calculate risk score
      3. Assign team
      4. Create Task in DB
      5. Generate fulfilment steps via LLM → save as TaskStep rows
      6. Generate 3-format messages via LLM → save as Message rows
      7. Record initial StatusHistory entry
 
    All DB writes happen inside a single atomic transaction.
    If anything fails, nothing is committed.
 
    Returns the saved Task instance.
    """
    #1. Intent extraction
    print(f"Extracting intent from message: {raw_message[:80]}")
    extraction = extract_intent(raw_message)
    intent = extraction["intent"]
    entities = extraction["entities"]

    #2. Risk Scoring
    risk_score = calculate_risk_score(intent, entities)
    print(f"Risk score: {risk_score}")

    #3. Team assignemnt
    assigned_team = assign_team(intent)

    #All DB writes in one atomic block
    with transaction.atomic():

        #4. Create the task
        task = Task.objects.create(
            raw_message=raw_message,
            intent=intent,
            entities=entities,
            risk_score=risk_score,
            assigned_team=assigned_team,
        )
        print(f"Task created: {task.task_code}")

        #5. Generate and save steps
        step_descriptions = generate_steps(intent, entities)
        TaskStep.objects.bulk_create([
            TaskStep(
                task=task,
                step_order=i+1,
                description=desc,
            )
            for i, desc in enumerate(step_descriptions)
        ])

        #6. Generate and save messages
        messages_data = generate_messages(
            task_code=task.task_code,
            intent=intent,
            entities=entities,
            risk_score=risk_score,
            assigned_team=assigned_team,
        )
        Message.objects.bulk_create([
            Message(task=task, channel=channel, body=body)
            for channel, body in messages_data.items()
        ])

        #7. Record initial status history

    return task


