from sqlalchemy.orm import Session
from app.database.session.db import SessionLocal
from app.database.models.workflow import Workflow
from app.database.models.task import Task
from app.database.models.activity import Activity


class SOPRetriever:

    def get_workflows(self, limit: int = 2):
        """
        Fetch workflows with tasks and activities
        (simple version: no vector search yet)
        """

        db: Session = SessionLocal()

        try:
            workflows = db.query(Workflow).limit(limit).all()

            result = []

            for wf in workflows:
                tasks = db.query(Task).filter(Task.workflow_id == wf.id).all()

                task_list = []

                for task in tasks:
                    activities = db.query(Activity).filter(Activity.task_id == task.id).all()

                    activity_list = [
                        {
                            "name": act.name,
                            "description": act.description
                        }
                        for act in activities
                    ]

                    task_list.append({
                        "task_name": task.name,
                        "role": task.role,
                        "activities": activity_list
                    })

                result.append({
                    "workflow_name": wf.name,
                    "description": wf.description,
                    "tasks": task_list
                })

            return result

        finally:
            db.close()
