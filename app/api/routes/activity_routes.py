from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session.db import get_db
from app.database.schemas.activity_schema import ActivityCreate, ActivityResponse
from app.services.activity_service import (
    create_activity,
    get_activities,
    get_activity_by_id,
    get_activities_by_task
)

router = APIRouter(prefix="/activities", tags=["Activities"])


@router.post("/", response_model=ActivityResponse)
def create_activity_route(activity: ActivityCreate, db: Session = Depends(get_db)):
    return create_activity(db, activity)


@router.get("/", response_model=list[ActivityResponse])
def read_activities(db: Session = Depends(get_db)):
    return get_activities(db)


@router.get("/{activity_id}", response_model=ActivityResponse)
def read_activity(activity_id: int, db: Session = Depends(get_db)):
    return get_activity_by_id(db, activity_id)


@router.get("/task/{task_id}", response_model=list[ActivityResponse])
def read_activities_by_task(task_id: int, db: Session = Depends(get_db)):
    return get_activities_by_task(db, task_id)
