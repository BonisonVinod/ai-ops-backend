from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session.db import get_db
from app.database.models.workflow import Workflow
from app.workflow.intelligence_engine import analyze_workflow

# 👉 NEW IMPORT
from app.services.agent_spec_service import generate_agent_spec

router = APIRouter(prefix="/workflow-intelligence", tags=["Workflow Intelligence"])


@router.get("/{workflow_id}")
def get_workflow_intelligence(workflow_id: int, db: Session = Depends(get_db)):

    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    insights = analyze_workflow(workflow)

    # 👉 NEW: Agent Spec Generation (non-breaking)
    agent_spec = generate_agent_spec(insights)

    return {
        "analysis": insights,
        "agent_spec": agent_spec
    }
