from typing import Dict
from openai import OpenAI
import os
import json

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# -------------------------------
# SCORING
# -------------------------------
def calculate_score(factors: Dict) -> int:
    mapping = {"high": 20, "medium": 10, "low": 0}

    score = 0
    for key in [
        "process_clarity",
        "input_availability",
        "decision_logic",
        "system_access",
        "human_dependency"
    ]:
        score += mapping.get(factors.get(key, "low"), 0)

    return score


# -------------------------------
# FACTORS
# -------------------------------
def derive_factors(text: str) -> Dict:
    t = text.lower()

    return {
        "process_clarity": "high" if len(t) > 150 else "medium" if len(t) > 60 else "low",
        "input_availability": "high" if "form" in t or "details" in t else "medium",
        "decision_logic": "high" if "if" in t or "after" in t or "verify" in t else "medium",
        "system_access": "medium" if "system" in t or "email" in t else "low",
        "human_dependency": "low" if "manual" in t else "medium"
    }


# -------------------------------
# COST
# -------------------------------
def estimate_cost(score: int, steps: int) -> Dict:
    if score >= 85:
        return {"effort": "Low", "cost": "₹20K – ₹50K"}
    elif score >= 60:
        return {"effort": "Medium", "cost": "₹50K – ₹1.5L"}
    else:
        return {"effort": "High", "cost": "₹1.5L – ₹5L"}


# -------------------------------
# MAIN ANALYZER
# -------------------------------
def analyze_sop(input_text: str) -> Dict:
    # We use the prompt you already wrote because it is structured perfectly
    prompt = f"""
You are a senior operations consultant.
Analyze the process and break it into steps.

RULES:
- Customer/user actions are NOT automation targets
- Use best practices for common things (passwords, retries, validations)
- DO NOT ask unnecessary questions
- MAX 3 missing items
- Questions ONLY if absolutely required
- Keep everything simple and business-friendly
- Include decision steps wherever validation or conditional logic exists (use "check", "if", "verify")

INPUT:
{input_text}

OUTPUT JSON:
{{
  "process_understanding": "...",
  "steps": [
    {{
      "step": "...",
      "automation": "Automatable / Needs clarity / Manual",
      "reason": "..."
    }}
  ],
  "missing_items": [
    {{
      "missing": "...",
      "suggested_solution": "...",
      "question": "optional (can be empty)"
    }}
  ],
  "automation_plan": [
    "High-level solution"
  ]
}}
"""

    try:
        # FIX 1: Use gpt-4o and add response_format for total stability
        response = client.chat.completions.create(
            model="gpt-4o", 
            messages=[
                {"role": "system", "content": "You are a practical automation consultant. Always return valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )

        # FIX 2: Safe parsing
        parsed = json.loads(response.choices[0].message.content)

        # --- KEEPING YOUR STEP FALLBACK LOGIC ---
        steps = parsed.get("steps", [])
        if not steps:
            steps = [{
                "step": "Process not clearly defined",
                "automation": "Needs clarity",
                "reason": "Steps not identifiable"
            }]
        parsed["steps"] = steps

        # --- KEEPING YOUR LIMIT MISSING ITEMS LOGIC ---
        missing_items = parsed.get("missing_items", [])[:3]
        for item in missing_items:
            if not item.get("question"):
                item["question"] = ""
        parsed["missing_items"] = missing_items

        # --- KEEPING YOUR DETERMINISTIC MATH (THE CORE) ---
        factors = derive_factors(input_text)
        score = calculate_score(factors)
        cost_data = estimate_cost(score, len(steps))

        # --- FINAL OUTPUT CONSTRUCTION ---
        final_output = {
            **parsed,
            "automation_opportunity": {
                "score": f"{score}%",
                "verdict": f"This process can be automated up to {score}%"
            },
            "effort_level": cost_data["effort"],
            "estimated_cost": cost_data["cost"]
        }

        return {
            "status": "success",
            "analysis": final_output
        }

    except Exception as e:
        # Safety net to prevent the app from crashing
        return {
            "status": "error",
            "message": str(e)
        }
