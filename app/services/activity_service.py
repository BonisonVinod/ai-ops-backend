from sqlalchemy.orm import Session
from app.database.models.activity import Activity
from app.database.schemas.activity_schema import ActivityCreate


def create_activity(db: Session, activity: ActivityCreate):
    db_activity = Activity(**activity.model_dump())

    db.add(db_activity)
    db.commit()
    db.refresh(db_activity)

    return db_activity


def get_activities(db: Session):
    return db.query(Activity).all()


def get_activity_by_id(db: Session, activity_id: int):
    return db.query(Activity).filter(Activity.id == activity_id).first()


def get_activities_by_task(db: Session, task_id: int):
    return db.query(Activity).filter(Activity.task_id == task_id).all()
