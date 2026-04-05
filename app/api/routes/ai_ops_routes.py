from fastapi import APIRouter
from pydantic import BaseModel

from app.orchestrator.main_orchestrator import Orchestrator
from app.agents.sop_analyzer import analyze_sop

router = APIRouter()

orchestrator = Orchestrator()


# -------------------------------
# EXISTING ENDPOINT (KEEP)
# -------------------------------
@router.post("/test-ai")
def test_ai(ticket: dict):
    ticket_text = ticket.get("text", "")

    result = orchestrator.run(ticket_text)

    return {
        "status": "success",
        "data": result
    }


# -------------------------------
# NEW ANALYZER ENDPOINT
# -------------------------------
class AnalyzeRequest(BaseModel):
    text: str


@router.post("/analyze")
def analyze(request: AnalyzeRequest):
    try:
        result = analyze_sop(request.text)

        return {
            "status": "success",
            "analysis": result.get("analysis")
        }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
