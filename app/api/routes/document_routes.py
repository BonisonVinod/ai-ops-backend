from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.services.document_service import extract_text, chunk_text
from sqlalchemy.orm import Session
from app.database.session.db import get_db
import os
import uuid

router = APIRouter(prefix="/documents", tags=["Documents"])

COLLECTION_NAME = "documents"
VECTOR_SIZE = 384


# Lazy imports
def get_workflow_builder():
    from app.workflow.workflow_builder import build_workflow_from_steps
    return build_workflow_from_steps


def get_embedding_service():
    from app.services.embedding_service import generate_embeddings
    return generate_embeddings


def get_qdrant_client():
    from app.vector.qdrant_client import upsert_vector, create_collection
    return upsert_vector, create_collection


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):

    if not file.filename.endswith((".pdf", ".docx", ".txt")):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    os.makedirs("tmp", exist_ok=True)
    temp_path = f"tmp/{file.filename}"

    with open(temp_path, "wb") as f:
        f.write(await file.read())

    try:
        text = extract_text(temp_path)
        text = text.replace("\x00", "")
        chunks = chunk_text(text)

        # Workflow
        build_workflow_from_steps = get_workflow_builder()
        workflow = build_workflow_from_steps(
            db,
            chunks,
            workflow_name=file.filename
        )

        # Embeddings
        generate_embeddings = get_embedding_service()
        embeddings = generate_embeddings(chunks)

        stored = 0

        # ✅ Safe Qdrant block
        try:
            upsert_vector, create_collection = get_qdrant_client()

            create_collection(COLLECTION_NAME, VECTOR_SIZE)

            for chunk, embedding in zip(chunks, embeddings):
                payload = {
                    "text": chunk,
                    "source_file": file.filename
                }

                vector_id = str(uuid.uuid4())

                upsert_vector(
                    COLLECTION_NAME,
                    vector_id,
                    embedding,
                    payload
                )

                stored += 1

        except Exception as e:
            print("Qdrant error (non-blocking):", str(e))

        return {
            "workflow_id": workflow.id if workflow else None,
            "filename": file.filename,
            "chunks_processed": len(chunks),
            "vectors_stored": stored
        }

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
