from celery import Celery
from app.core.config.settings import settings
from app.services.document_service import extract_text, chunk_text, store_embeddings

# Celery application
celery_app = Celery(
    "worker",
    broker=settings.redis_url,
    backend=settings.redis_url
)

@celery_app.task
def process_document(file_path: str):
    text = extract_text(file_path)
    chunks = chunk_text(text)
    store_embeddings(chunks)
    return {"status": "processed", "chunks": len(chunks)}


@celery_app.task
def generate_workflow_analysis(workflow_id: int):
    # Placeholder for workflow analysis logic
    return {"workflow_id": workflow_id, "analysis": "not implemented yet"}
