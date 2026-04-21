import uuid
import os
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.agents.sop_analyzer import analyze_sop
from app.services.agent_spec_service import generate_agent_spec

router = APIRouter(prefix="/sop", tags=["SOP Analyzer"])

_FACTORY_DB = os.getenv("FACTORY_DB_PATH", "factory_checkpoints.db")


class AnalyzeRequest(BaseModel):
    input: str


class AnalyzeAndRunRequest(BaseModel):
    input: str
    thread_id: Optional[str] = None
    auto_run: bool = True   # if False, returns spec only without triggering factory


@router.post("/analyze")
def analyze_sop_endpoint(request: AnalyzeRequest):
    """
    Analyze an SOP or Job Description. Returns structured analysis + static agent spec.
    For live execution, use POST /sop/analyze-and-run.
    """
    result = analyze_sop(request.input)

    if result.get("status") != "success":
        return result

    insights = result["analysis"]
    agent_spec = generate_agent_spec(insights)

    return {
        "status": "success",
        "analysis": insights,
        "agent_spec": agent_spec,
    }


@router.post("/analyze-and-run")
def analyze_and_run(request: AnalyzeAndRunRequest):
    """
    Full pipeline: Analyze the SOP/JD, then immediately run it through the Agentic Factory.

    Flow:
      1. analyze_sop()          → structured analysis (precision, ROI, skill map)
      2. generate_agent_spec()  → factory-ready RunSpec (tools, domain, knowledge)
      3. run_factory()          → live LangGraph execution with domain rules + tools

    Returns:
    - status="completed"        → final_output ready
    - status="awaiting_review"  → human review required; call POST /engine/resume with thread_id
    """
    from app.engine.composer import run_factory

    # Step 1: Analyze
    analysis_result = analyze_sop(request.input)
    if analysis_result.get("status") != "success":
        return {
            "status": "error",
            "stage": "analysis",
            "message": analysis_result.get("message", "SOP analysis failed"),
        }

    insights = analysis_result["analysis"]
    agent_spec = generate_agent_spec(insights)

    if not request.auto_run:
        return {
            "status": "spec_ready",
            "analysis": insights,
            "agent_spec": agent_spec,
            "message": "Set auto_run=true to execute via the Agentic Factory.",
        }

    # Step 2: Build factory task description from the analysis
    sop_type = insights.get("type", "SOP")
    process = insights.get("process_understanding", request.input[:200])
    skills  = insights.get("required_ai_skills", [])
    plan    = insights.get("recommended_plan", "Pro")

    task_description = (
        f"{sop_type} Execution Task: {process}\n\n"
        f"Required Skills: {', '.join(skills[:5])}\n"
        f"Plan Tier: {plan}\n"
        f"Original Input: {request.input[:500]}"
    )

    thread_id = request.thread_id or f"sop-{uuid.uuid4().hex[:10]}"

    # Step 3: Run factory
    try:
        factory_result = run_factory(
            task=task_description,
            thread_id=thread_id,
            db_path=_FACTORY_DB,
            analysis_report=insights,
        )
    except Exception as e:
        return {
            "status": "error",
            "stage": "factory_run",
            "analysis": insights,
            "agent_spec": agent_spec,
            "message": str(e),
        }

    interrupted = _is_interrupted(factory_result)

    if interrupted:
        return {
            "status": "awaiting_review",
            "thread_id": thread_id,
            "analysis": insights,
            "agent_spec": agent_spec,
            "domain": factory_result.get("knowledge_domain"),
            "human_review_required": True,
            "knowledge_rules_applied": _extract_rule_ids(factory_result),
            "tool_results_preview": [
                r[:300] for r in (factory_result.get("tool_results") or [])
            ],
            "message": (
                "Human review required before proceeding. "
                f"Call POST /engine/resume with thread_id='{thread_id}'."
            ),
        }

    return {
        "status": "completed",
        "thread_id": thread_id,
        "analysis": insights,
        "agent_spec": agent_spec,
        "domain": factory_result.get("knowledge_domain"),
        "final_output": factory_result.get("final_output"),
        "tool_results": factory_result.get("tool_results", []),
        "human_review_required": factory_result.get("human_review_required", False),
        "error": factory_result.get("error"),
    }


def _is_interrupted(state: dict) -> bool:
    if not isinstance(state, dict):
        return False
    if state.get("__interrupt__"):
        return True
    return bool(state.get("human_review_required")) and not state.get("final_output")


def _extract_rule_ids(state: dict) -> list[str]:
    ctx = state.get("knowledge_context") or {}
    rules = ctx.get("applicable_rules") or []
    return [r.get("id", "") for r in rules if isinstance(r, dict)]
