from sqlalchemy.orm import Session
from app.database.models.task import Task
from app.database.schemas.task_schema import TaskCreate


def create_task(db: Session, task: TaskCreate):
    db_task = Task(**task.model_dump())

    db.add(db_task)
    db.commit()
    db.refresh(db_task)

    return db_task


def get_tasks(db: Session):
    return db.query(Task).all()


def get_task_by_id(db: Session, task_id: int):
    return db.query(Task).filter(Task.id == task_id).first()


def get_tasks_by_workflow(db: Session, workflow_id: int):
    return db.query(Task).filter(Task.workflow_id == workflow_id).all()
