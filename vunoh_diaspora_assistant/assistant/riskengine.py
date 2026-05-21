from typing import Dict, Any

HIGH_RISK_INTENTS = {
    "land_title": 35,
    "property_purchase": 40,
    "legal_document": 30,
}

MEDIUM_RISK_INTENTS = {
    "urgent_payment": 20,
    "emergency_funds": 15,
}

AMOUNT_THRESHOLDS = [
    (100000, 35),
    (50000, 25),
    (10000, 10),
]

def safe_amount_parser(value) -> int:
    """
    Safely converts amounts like:
    '15,000', 'KES 20000', 30000.0
    into integers.
    """
    if value is None:
        return 0

    try:
        cleaned = (
            str(value)
            .replace(",", "")
            .replace("KES", "")
            .replace("kes", "")
            .strip()
        )

        return int(float(cleaned))

    except (ValueError, TypeError):
        return 0


def calculate_risk_score(intent: str, entities: Dict[str, Any]) -> Dict[str, Any]:

    risk_score = 0
    reasons = []

    # Amount Risk
    amount = safe_amount_parser(entities.get("amount"))

    for threshold, score in AMOUNT_THRESHOLDS:
        if amount > threshold:
            risk_score += score
            reasons.append(
                f"Transaction amount above KES {threshold:,}"
            )
            break

    # Intent Risk
    if intent in HIGH_RISK_INTENTS:
        score = HIGH_RISK_INTENTS[intent]
        risk_score += score
        reasons.append(f"High-risk service type: {intent}")

    elif intent in MEDIUM_RISK_INTENTS:
        score = MEDIUM_RISK_INTENTS[intent]
        risk_score += score
        reasons.append(f"Medium-risk request type: {intent}")

    # Urgency Risk
    urgency = entities.get("urgency")

    urgency_scores = {
        "high": 20,
        "medium": 10,
        "low": 0
    }

    if urgency in urgency_scores:
        risk_score += urgency_scores[urgency]

        if urgency != "low":
            reasons.append(
                f"{urgency.capitalize()} urgency request"
            )

    # Recipient Verification
    recipient_verified = entities.get(
        "recipient_verified", False
    )

    if not recipient_verified:
        risk_score += 25
        reasons.append("Recipient not verified")

    #Behavioural 
    if entities.get("returning_customer"):
        risk_score -= 15
        reasons.append("Returning customer history")

    if entities.get("clean_history"):
        risk_score -= 10
        reasons.append("Clean transaction history")

    # High urgency + large amount
    if amount > 100000 and urgency == "high":
        risk_score += 15
        reasons.append(
            "Large urgent transaction combination"
        )

    # Property + unverified recipient
    if (
        intent in ["land_title", "property_purchase"]
        and not recipient_verified
    ):
        risk_score += 20
        reasons.append(
            "Property-related request with unverified recipient"
        )

    risk_score = max(0, min(100, risk_score))

    # Risk Levels
    if risk_score >= 75:
        risk_level = "HIGH"
    elif risk_score >= 40:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    # return {
    #     "score": risk_score,
    #     "level": risk_level,
    #     "reasons": reasons,
    # }

    return risk_score