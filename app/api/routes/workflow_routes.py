from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database.session.db import get_db
from app.database.schemas.workflow_schema import WorkflowCreate, WorkflowResponse
from app.services.workflow_persistence_service import save_workflow
from app.services.workflow_service import create_workflow, get_workflows, get_workflow_by_id

from app.services.document_service import chunk_text
from app.workflow.reconstruction_engine import reconstruct_workflow
from app.workflow.observation_engine import generate_observations


router = APIRouter(prefix="/workflows", tags=["Workflows"])


# ------------------------------------------------
# EXISTING WORKFLOW CRUD ROUTES
# ------------------------------------------------

@router.post("/", response_model=WorkflowResponse)
def create_workflow_endpoint(workflow: WorkflowCreate, db: Session = Depends(get_db)):
    return create_workflow(db, workflow)


@router.get("/", response_model=list[WorkflowResponse])
def get_workflows_endpoint(db: Session = Depends(get_db)):
    return get_workflows(db)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow_endpoint(workflow_id: int, db: Session = Depends(get_db)):
    return get_workflow_by_id(db, workflow_id)


# ------------------------------------------------
# AI WORKFLOW ANALYSIS ROUTE
# ------------------------------------------------

class WorkflowAnalysisRequest(BaseModel):
    text: str


class WorkflowAnalysisResponse(BaseModel):
    workflow: dict
    observations: list

@router.post("/analyze", response_model=WorkflowAnalysisResponse)
def analyze_workflow(data: WorkflowAnalysisRequest):

    # split document text into chunks
    chunks = chunk_text(data.text)

    # reconstruct workflow from chunks
    workflow_data = reconstruct_workflow(chunks)

    # generate operational observations
    observations = generate_observations(workflow_data["workflow"])

    return {
        "workflow": workflow_data,
        "observations": observations
    }

@router.post("/auto-generate")
def auto_generate_workflow(data: WorkflowAnalysisRequest, db: Session = Depends(get_db)):

    chunks = chunk_text(data.text)

    workflow_data = reconstruct_workflow(chunks)

    db_workflow = save_workflow(db, workflow_data)

    observations = generate_observations(workflow_data["workflow"])

    return {
        "workflow_id": db_workflow.id,
        "observations": observations,
        "message": "Workflow generated, saved, and analyzed"
    }
