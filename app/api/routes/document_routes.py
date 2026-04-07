from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.services.document_service import extract_text, chunk_text
from sqlalchemy.orm import Session
from app.database.session.db import get_db
import os

router = APIRouter(prefix="/documents", tags=["Documents"])


# ✅ Lazy import for workflow
def get_workflow_builder():
    from app.workflow.workflow_builder import build_workflow_from_steps
    return build_workflow_from_steps


# ✅ Lazy import for embeddings
def get_embedding_service():
    from app.services.embedding_service import generate_embeddings
    return generate_embeddings


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

        # ✅ Embeddings (SAFE)
        generate_embeddings = get_embedding_service()
        embeddings = generate_embeddings(chunks)

        return {
            "workflow_id": workflow.id if workflow else None,
            "filename": file.filename,
            "chunks_processed": len(chunks),
            "embeddings_generated": len(embeddings)
        }

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
