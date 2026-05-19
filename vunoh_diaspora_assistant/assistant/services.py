# 3 services

#   1. Talk to the LLM API (extract intent, generate steps, generate messages)
#   2. Calculate risk score via a local rules engine
#   3. Create and persist the full task record atomically

import json
import logging
import requests
from django.conf import settings
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
#    INTENT_TEAM_MAP,
)
from .prompts import (
    INTENT_EXTRACTION_PROMPT
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
    