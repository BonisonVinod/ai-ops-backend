from sqlalchemy.orm import Session
from app.database.models.workflow import Workflow
from app.database.schemas.workflow_schema import WorkflowCreate


def create_workflow(db: Session, workflow: WorkflowCreate):
    new_workflow = Workflow(
        name=workflow.name,
        description=workflow.description
    )

    db.add(new_workflow)
    db.commit()
    db.refresh(new_workflow)

    return new_workflow


def get_workflows(db: Session):
    return db.query(Workflow).all()


def get_workflow_by_id(db: Session, workflow_id: int):
    return db.query(Workflow).filter(Workflow.id == workflow_id).first()
