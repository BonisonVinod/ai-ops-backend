from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.services.document_service import extract_text, chunk_text
from sqlalchemy.orm import Session
from app.database.session.db import get_db
import os

router = APIRouter(prefix="/documents", tags=["Documents"])


# ✅ Lazy import for workflow (safe)
def get_workflow_builder():
    from app.workflow.workflow_builder import build_workflow_from_steps
    return build_workflow_from_steps


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):

    if not file.filename.endswith((".pdf", ".docx", ".txt")):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    os.makedirs("tmp", exist_ok=True)
    temp_path = f"tmp/{file.filename}"

    # Save file temporarily
    with open(temp_path, "wb") as f:
        f.write(await file.read())

    try:
        # Extract text
        text = extract_text(temp_path)

        # Clean text
        text = text.replace("\x00", "")

        # Chunk text
        chunks = chunk_text(text)

        # ✅ Safe workflow execution
        build_workflow_from_steps = get_workflow_builder()

        workflow = build_workflow_from_steps(
            db,
            chunks,
            workflow_name=file.filename
        )

        stored = 0  # embeddings disabled for now

        return {
            "workflow_id": workflow.id if workflow else None,
            "filename": file.filename,
            "chunks_processed": len(chunks),
            "vectors_stored": stored
        }

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
