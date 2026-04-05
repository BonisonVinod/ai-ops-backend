from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session.db import get_db
from app.database.schemas.task_schema import TaskCreate, TaskResponse
from app.services.task_service import (
    create_task,
    get_tasks,
    get_task_by_id,
    get_tasks_by_workflow
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post("/", response_model=TaskResponse)
def create_task_route(task: TaskCreate, db: Session = Depends(get_db)):
    return create_task(db, task)


@router.get("/", response_model=list[TaskResponse])
def read_tasks(db: Session = Depends(get_db)):
    return get_tasks(db)


@router.get("/{task_id}", response_model=TaskResponse)
def read_task(task_id: int, db: Session = Depends(get_db)):
    return get_task_by_id(db, task_id)


@router.get("/workflow/{workflow_id}", response_model=list[TaskResponse])
def read_tasks_by_workflow(workflow_id: int, db: Session = Depends(get_db)):
    return get_tasks_by_workflow(db, workflow_id)
