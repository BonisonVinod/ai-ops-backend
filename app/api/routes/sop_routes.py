from fastapi import APIRouter
from app.agents.sop_analyzer import analyze_sop
from app.services.agent_spec_service import generate_agent_spec

router = APIRouter(prefix="/sop", tags=["SOP Analyzer"])


@router.post("/analyze")
def analyze_sop_endpoint(request: dict):

    input_text = request.get("input", "")

    result = analyze_sop(input_text)

    if result.get("status") != "success":
        return result

    insights = result["analysis"]

    agent_spec = generate_agent_spec(insights)

    return {
        "analysis": insights,
        "agent_spec": agent_spec
    }
