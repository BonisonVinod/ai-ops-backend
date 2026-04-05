from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session.db import get_db
from app.database.models.workflow import Workflow
from app.workflow.graph_service import build_workflow_graph, extract_workflow_signals
from app.workflow.observation_engine import generate_insights_from_signals

# ✅ DEFINE ROUTER FIRST
router = APIRouter(prefix="/workflow-graph", tags=["Workflow Graph"])


# ✅ GRAPH ENDPOINT
@router.get("/{workflow_id}")
def get_workflow_graph(workflow_id: int, db: Session = Depends(get_db)):

    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    graph = build_workflow_graph(db, workflow_id)

    return graph


# ✅ SIGNALS ENDPOINT
@router.get("/signals/{workflow_id}")
def get_workflow_signals(workflow_id: int, db: Session = Depends(get_db)):

    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    graph = build_workflow_graph(db, workflow_id)
    signals = extract_workflow_signals(graph["nodes"], graph["edges"])

    return {
        "workflow_id": workflow_id,
        "signals": signals
    }


# ✅ INSIGHTS ENDPOINT (ONLY ONCE)
@router.get("/insights/{workflow_id}")
def get_workflow_insights(workflow_id: int, db: Session = Depends(get_db)):

    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()

    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    graph = build_workflow_graph(db, workflow_id)
    signals = extract_workflow_signals(graph["nodes"], graph["edges"])

    insights = generate_insights_from_signals(signals)

    return {
        "workflow_id": workflow_id,
        "signals": signals,
        "insights": insights
    }
