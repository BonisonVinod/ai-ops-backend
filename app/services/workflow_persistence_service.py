from sqlalchemy.orm import Session
from app.database.models import Workflow, Task, Activity


def save_workflow(db: Session, workflow_data: dict):
    """
    Saves reconstructed workflow JSON into DB
    """

    wf = workflow_data.get("workflow")

    if not wf:
        raise ValueError("Invalid workflow structure")

    # 1. Create Workflow
    db_workflow = Workflow(
        name=wf.get("name"),
        description="Auto-generated workflow"
    )
    db.add(db_workflow)
    db.commit()
    db.refresh(db_workflow)

    # 2. Create Tasks
    for task in wf.get("tasks", []):

        db_task = Task(
            workflow_id=db_workflow.id,
            name=task.get("name"),
            role=task.get("role"),
            tool=task.get("tool"),
            frequency=task.get("frequency"),
            estimated_minutes=task.get("estimated_minutes")
        )

        db.add(db_task)
        db.commit()
        db.refresh(db_task)

        # 3. Create Activities
        for activity in task.get("activities", []):

            db_activity = Activity(
                task_id=db_task.id,
                name=activity.get("name"),
                description=activity.get("description"),
                sequence_order=activity.get("sequence_order"),
		intent=activity.get("intent"),
		execution_type=activity.get("execution_type"),
		automation_potential=activity.get("automation_potential")
            )

            db.add(db_activity)

        db.commit()

    return db_workflow
