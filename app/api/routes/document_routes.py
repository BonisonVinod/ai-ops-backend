from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from app.services.document_service import extract_text, chunk_text
from app.services.embedding_service import generate_embeddings
from app.vector.qdrant_client import upsert_vector, create_collection
from sqlalchemy.orm import Session
from app.database.session.db import get_db
build_workflow_from_steps = None
import os
import uuid

router = APIRouter(prefix="/documents", tags=["Documents"])

COLLECTION_NAME = "documents"
VECTOR_SIZE = 384


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

        # ✅ FIX: remove NULL characters (critical)
        text = text.replace("\x00", "")

        # Chunk text
        chunks = chunk_text(text)

        # Build workflow (DB write happens here)
        #workflow = build_workflow_from_steps(
        #    db,
        #    chunks,
        #    workflow_name=file.filename
        #)
	workflow = None
        # Generate embeddings
        embeddings = generate_embeddings(chunks)

        # Ensure collection exists
        create_collection(COLLECTION_NAME, VECTOR_SIZE)

        stored = 0

        # Store vectors
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

        return {
            "workflow_id": None,
	    "filename": file.filename,
            "chunks_processed": len(chunks),
            "vectors_stored": stored
        }

    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)
