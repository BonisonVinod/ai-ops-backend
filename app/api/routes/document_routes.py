from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.services.document_service import extract_text, chunk_text
from sqlalchemy.orm import Session
from app.database.session.db import get_db
import os

router = APIRouter(prefix="/documents", tags=["Documents"])


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

        # 🚫 Temporarily disabled (for stability)
        workflow = None
        stored = 0

        return {
            "workflow_id": None,
            "filename": file.filename,
            "chunks_processed": len(chunks),
            "vectors_stored": stored
        }

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
