from sqlalchemy.orm import Session
from sklearn.cluster import KMeans
from app.database.models.workflow import Workflow
from app.database.models.task import Task
from app.database.models.activity import Activity
from app.services.embedding_service import generate_embeddings


def build_workflow_from_steps(db: Session, steps: list, workflow_name: str):

    workflow = Workflow(
        name=workflow_name,
        description="Generated from document"
    )

    db.add(workflow)
    db.commit()
    db.refresh(workflow)

    if not steps:
        return workflow

    # Generate embeddings for steps
    embeddings = generate_embeddings(steps)

    # Choose cluster count (simple heuristic)
    n_clusters = min(3, len(steps))

    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
    labels = kmeans.fit_predict(embeddings)

    tasks = {}

    for cluster_id in range(n_clusters):

        task = Task(
            workflow_id=workflow.id,
            name=f"Task Group {cluster_id + 1}",
            role="Operations",
            tool=None,
            frequency="Daily",
            estimated_minutes=5
        )

        db.add(task)
        db.commit()
        db.refresh(task)

        tasks[cluster_id] = task

    for i, step in enumerate(steps):

        cluster_id = labels[i]

        activity = Activity(
            task_id=tasks[cluster_id].id,
            name=step,
            description="Generated from document",
            sequence_order=i
        )

        db.add(activity)

    db.commit()

    return workflow
