from fastapi import APIRouter
from openai import OpenAI

router = APIRouter()
client = OpenAI()


# -------------------------------
# CONTEXT-AWARE FULL SYSTEM
# -------------------------------
def generate_full_system(architecture, steps, process_text):

    architecture_text = "\n".join(
        [f"{c['name']} - {c['description']}" for c in architecture]
    )

    steps_text = "\n".join(
        [f"{s['step']} - {s['automation']}" for s in steps]
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
"You are a senior AI systems architect.\n\n"

"Build a REAL automation system using FastAPI.\n\n"

"STRICT RULES:\n"
"- Do NOT build generic CRUD\n"
"- Reflect actual process steps\n"
"- Keep it in ONE FILE\n\n"

"CRITICAL REQUIREMENT:\n"
"- Create a CENTRAL ORCHESTRATOR FUNCTION\n"
"- This function MUST control the ENTIRE workflow\n"
"- After submission, the system should CONTINUE automatically\n"
"- Do NOT rely on separate manual APIs for each step\n\n"

"AUTOMATION FLOW:\n"
"- Submission API triggers orchestrator\n"
"- Orchestrator internally handles:\n"
"   → manager decision (simulate or logic-based)\n"
"   → approval/rejection\n"
"   → HR update\n"
"   → notifications\n\n"

"IMPORTANT:\n"
"- Manager decision should NOT require separate API\n"
"- HR update should NOT require separate API\n"
"- Entire process should be driven inside orchestrator\n\n"

"DECISION ENGINE REQUIREMENT:"

"- Create a separate function called decision_engine"
"- This function should take the request data and return a decision (approved/rejected)"
"- The orchestrator MUST call this decision_engine instead of using hardcoded logic"

"- Decision should be based on:"
"  - leave duration"
"  - leave type"
"  - (optional) simple rules or simulated intelligence"

"- DO NOT hardcode decision directly inside orchestrator"

"GOAL:\n"
"Make the system modular so decision logic can be upgraded later (AI, rules, etc.)"
"ONE API → FULL PROCESS EXECUTION\n"
)
                },
                {
                    "role": "user",
                    "content": f"""
PROCESS DESCRIPTION:
{process_text}

PROCESS STEPS:
{steps_text}

ARCHITECTURE:
{architecture_text}

Build the system accordingly.
"""
                }
            ]
        )

        return response.choices[0].message.content

    except Exception as e:
        print("Context generation failed:", e)
        return "# Failed to generate system"


# -------------------------------
# API
# -------------------------------
@router.post("/generate-code")
def generate_code(payload: dict):

    mode = payload.get("mode", "full")

    if mode == "full":
        architecture = payload.get("architecture", [])
        steps = payload.get("steps", [])
        process_text = payload.get("process", "")

        code = generate_full_system(architecture, steps, process_text)
        return {"code": code}

