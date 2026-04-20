"""
Engine Routes — Agentic Factory API

Endpoints:
  POST /engine/run               Start a factory run for any task
  POST /engine/resume            Resume a thread after human interrupt
  GET  /engine/status/{thread_id} Inspect persisted thread state
  POST /engine/audit/run         Start an accounting audit (CSV upload)
  POST /engine/audit/resume      Resume an audit after CA review
"""

import os
import uuid
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/engine", tags=["Agentic Factory"])

# Checkpoint DB path — use /tmp for Render compatibility
_FACTORY_DB = os.getenv("FACTORY_DB_PATH", "factory_checkpoints.db")
_AUDIT_DB   = os.getenv("AUDIT_DB_PATH",   "audit_checkpoints.db")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RunRequest(BaseModel):
    task: str
    thread_id: Optional[str] = None
    analysis_report: Optional[dict] = None  # optional SOP Analyzer output to include


class ResumeRequest(BaseModel):
    thread_id: str
    task: str                               # needed to reopen the same factory context
    human_feedback: str


class AuditResumeRequest(BaseModel):
    thread_id: str
    human_feedback: str


class ThreadStatusRequest(BaseModel):
    thread_id: str


# ---------------------------------------------------------------------------
# /engine/run
# ---------------------------------------------------------------------------

@router.post("/run")
def run_factory_endpoint(req: RunRequest):
    """
    Start or restart a factory run for a given task.

    Returns one of:
    - { status: "completed", thread_id, final_output, ... }
    - { status: "awaiting_review", thread_id, review_payload, ... }
    """
    from app.engine.composer import run_factory

    thread_id = req.thread_id or str(uuid.uuid4())

    try:
        result = run_factory(
            task=req.task,
            thread_id=thread_id,
            db_path=_FACTORY_DB,
            analysis_report=req.analysis_report,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Factory run failed: {str(e)}")

    # Detect if the graph paused at a human interrupt node
    interrupted = _is_interrupted(result)

    if interrupted:
        return {
            "status": "awaiting_review",
            "thread_id": thread_id,
            "message": "Human review required. Call POST /engine/resume with your feedback.",
            "domain": result.get("knowledge_domain"),
            "human_review_required": result.get("human_review_required"),
            "tool_results_preview": [r[:300] for r in (result.get("tool_results") or [])],
            "knowledge_rules_applied": _extract_rule_ids(result),
            "proposed_actions": result.get("planned_actions", []),
        }

    return {
        "status": "completed",
        "thread_id": thread_id,
        "domain": result.get("knowledge_domain"),
        "final_output": result.get("final_output"),
        "tool_results": result.get("tool_results", []),
        "human_review_required": result.get("human_review_required", False),
        "human_feedback": result.get("human_feedback"),
        "error": result.get("error"),
    }


# ---------------------------------------------------------------------------
# /engine/resume
# ---------------------------------------------------------------------------

@router.post("/resume")
def resume_factory_endpoint(req: ResumeRequest):
    """
    Resume a factory thread after human review.

    Supply the same thread_id from the /run response and your human_feedback string.
    """
    from app.engine.composer import run_factory

    try:
        result = run_factory(
            task=req.task,
            thread_id=req.thread_id,
            db_path=_FACTORY_DB,
            human_feedback=req.human_feedback,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Factory resume failed: {str(e)}")

    return {
        "status": "completed",
        "thread_id": req.thread_id,
        "domain": result.get("knowledge_domain"),
        "final_output": result.get("final_output"),
        "human_feedback": result.get("human_feedback"),
        "tool_results": result.get("tool_results", []),
        "error": result.get("error"),
    }


# ---------------------------------------------------------------------------
# /engine/status/{thread_id}
# ---------------------------------------------------------------------------

@router.get("/status/{thread_id}")
def get_thread_status(thread_id: str):
    """
    Inspect the persisted state of a factory thread.
    Useful for polling after a human-interrupt pause.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    if not Path(_FACTORY_DB).exists() and _FACTORY_DB != ":memory:":
        raise HTTPException(status_code=404, detail="No factory database found. Run a task first.")

    try:
        with SqliteSaver.from_conn_string(_FACTORY_DB) as cp:
            config = {"configurable": {"thread_id": thread_id}}
            snapshot = cp.get(config)

        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")

        state = snapshot.values if hasattr(snapshot, "values") else {}
        interrupted = _is_interrupted(state)

        return {
            "thread_id": thread_id,
            "status": "awaiting_review" if interrupted else "completed",
            "domain": state.get("knowledge_domain"),
            "human_review_required": state.get("human_review_required"),
            "human_feedback": state.get("human_feedback"),
            "planned_actions": state.get("planned_actions", []),
            "tool_results_count": len(state.get("tool_results") or []),
            "final_output_preview": (state.get("final_output") or "")[:400] or None,
            "error": state.get("error"),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")


# ---------------------------------------------------------------------------
# /engine/audit/run  (multipart CSV upload)
# ---------------------------------------------------------------------------

@router.post("/audit/run")
async def run_audit_endpoint(
    audit_period: str = "FY 2025-26",
    thread_id: Optional[str] = None,
    file: UploadFile = File(...),
):
    """
    Upload a CSV ledger and start an accounting audit.

    The agent will:
    1. Read the CSV
    2. Load accounting_rules.json (TDS, GST, PF, IndAS)
    3. Analyze for compliance violations
    4. Generate corrective journal entry proposals
    5. Pause for CA review

    Returns { status: "awaiting_review", thread_id, ... } when ready for human review.
    """
    from app.engine.agents.accounting_audit_agent import AccountingAuditAgent

    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")

    # Write to a temp file so the agent can read it
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="wb") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    tid = thread_id or f"audit-{uuid.uuid4().hex[:10]}"

    try:
        agent = AccountingAuditAgent(db_path=_AUDIT_DB)
        result = agent.run(
            csv_file_path=tmp_path,
            audit_period=audit_period,
            thread_id=tid,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audit run failed: {str(e)}")
    finally:
        os.unlink(tmp_path)

    interrupted = _is_audit_interrupted(result)

    if interrupted:
        return {
            "status": "awaiting_review",
            "thread_id": tid,
            "audit_period": audit_period,
            "message": "Audit analysis complete. CA review required. Call POST /engine/audit/resume.",
            "tds_flags": result.get("tds_flags", []),
            "gst_flags": result.get("gst_flags", []),
            "pf_flags": result.get("pf_flags", []),
            "other_flags": result.get("other_flags", []),
            "anomalies": result.get("anomalies", []),
            "proposed_changes": result.get("proposed_changes", []),
            "change_summary": result.get("change_summary", ""),
            "total_flags": (
                len(result.get("tds_flags", [])) +
                len(result.get("gst_flags", [])) +
                len(result.get("pf_flags", [])) +
                len(result.get("other_flags", []))
            ),
        }

    return {
        "status": "completed",
        "thread_id": tid,
        "audit_memo": result.get("audit_memo"),
        "human_approved": result.get("human_approved", False),
        "tds_flags": result.get("tds_flags", []),
        "gst_flags": result.get("gst_flags", []),
        "pf_flags": result.get("pf_flags", []),
        "other_flags": result.get("other_flags", []),
        "proposed_changes": result.get("proposed_changes", []),
    }


# ---------------------------------------------------------------------------
# /engine/audit/resume
# ---------------------------------------------------------------------------

@router.post("/audit/resume")
def resume_audit_endpoint(req: AuditResumeRequest):
    """
    Resume an accounting audit after CA review.

    Supply:
    - thread_id: from the /audit/run response
    - human_feedback: "approved", "approved: <notes>", or "rejected: <reason>"
    """
    from app.engine.agents.accounting_audit_agent import AccountingAuditAgent

    try:
        agent = AccountingAuditAgent(db_path=_AUDIT_DB)
        result = agent.resume(
            thread_id=req.thread_id,
            human_feedback=req.human_feedback,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audit resume failed: {str(e)}")

    return {
        "status": "completed",
        "thread_id": req.thread_id,
        "human_approved": result.get("human_approved", False),
        "human_feedback": result.get("human_feedback"),
        "audit_memo": result.get("audit_memo"),
        "tds_flags": result.get("tds_flags", []),
        "gst_flags": result.get("gst_flags", []),
        "pf_flags": result.get("pf_flags", []),
        "proposed_changes": result.get("proposed_changes", []),
        "change_summary": result.get("change_summary", ""),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_interrupted(state: dict) -> bool:
    """
    Detect if the graph paused at the human_interrupt node.
    LangGraph sets __interrupt__ in the returned state dict when paused.
    We also fall back to checking human_review_required + no final_output.
    """
    if not isinstance(state, dict):
        return False
    if state.get("__interrupt__"):
        return True
    # Fallback: review was required but output was never produced
    return bool(state.get("human_review_required")) and not state.get("final_output")


def _is_audit_interrupted(state: dict) -> bool:
    if not isinstance(state, dict):
        return False
    if state.get("__interrupt__"):
        return True
    # Audit pauses before human_approval_gate — memo not generated yet
    return state.get("proposed_changes") is not None and not state.get("audit_memo")


def _extract_rule_ids(state: dict) -> list[str]:
    ctx = state.get("knowledge_context") or {}
    rules = ctx.get("applicable_rules") or []
    return [r.get("id", "") for r in rules if isinstance(r, dict)]
