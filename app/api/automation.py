from fastapi import APIRouter

router = APIRouter()


def calculate_complexity(steps):
    automatable = sum(1 for s in steps if s["type"] == "automatable")
    unclear = sum(1 for s in steps if s["type"] == "needs_clarity")
    manual = sum(1 for s in steps if s["type"] == "manual")

    score = (automatable * 2) - (unclear * 1.5) - (manual * 1)

    if score <= 1:
        return "Low", "1-2 weeks", "1 Developer"
    elif score <= 4:
        return "Medium", "2-4 weeks", "1-2 Developers"
    else:
        return "High", "4-8 weeks", "2-3 Developers"


def generate_architecture(steps):
    components = []

    # Always needed
    components.append({
        "name": "Input API",
        "description": "Handles incoming data (requests, emails, forms)",
        "tech": "FastAPI / Node.js"
    })

    for step in steps:

        if step["type"] == "automatable":
            components.append({
                "name": f"{step['name']} Agent",
                "description": "AI agent to process and automate this step",
                "tech": "OpenAI / LangChain"
            })

        elif step["type"] == "needs_clarity":
            components.append({
                "name": f"{step['name']} Validation Layer",
                "description": "Rules or human validation required before automation",
                "tech": "Custom Logic / Admin Panel"
            })

    # Always include core infra
    components.append({
        "name": "Decision Engine",
        "description": "Handles business logic and routing decisions",
        "tech": "Python Rules + LLM"
    })

    components.append({
        "name": "Database",
        "description": "Stores workflow data and logs",
        "tech": "PostgreSQL"
    })

    components.append({
        "name": "Workflow Orchestrator",
        "description": "Manages step execution flow",
        "tech": "LangGraph / Temporal"
    })

    components.append({
        "name": "Notification Service",
        "description": "Sends alerts, emails, updates",
        "tech": "SMTP / Webhooks"
    })

    return components


@router.post("/start-automation")
def start_automation(payload: dict):

    steps = payload.get("steps", [])

    # 🔥 Generate Architecture
    architecture = generate_architecture(steps)

    # 🔥 Complexity
    complexity, timeline, team = calculate_complexity(steps)

    return {
        "status": "success",
        "architecture": architecture,
        "build_complexity": complexity,
        "estimated_timeline": timeline,
        "recommended_team": team
    }
