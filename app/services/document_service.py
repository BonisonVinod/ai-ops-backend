from pdfminer.high_level import extract_text as extract_pdf_text
from docx import Document
import re


def extract_text(file_path: str) -> str:
    """
    Extract text from supported document types.
    """

    if file_path.endswith(".pdf"):
        return extract_pdf_text(file_path)

    elif file_path.endswith(".docx"):
        doc = Document(file_path)
        return "\n".join([p.text for p in doc.paragraphs])

    elif file_path.endswith(".txt"):
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    else:
        raise ValueError("Unsupported file type")


def chunk_text(text: str):
    """
    Convert document text into workflow steps.
    Handles sentences, numbered lists, and bullet points.
    """

    steps = []

    # Normalize line breaks
    text = text.replace("\r", "\n")

    # Split by sentence endings
    sentences = re.split(r"[.\n]", text)

    for sentence in sentences:

        step = sentence.strip()

        if not step:
            continue

        # Remove numbering like "1." or "Step 1"
        step = re.sub(r"^\d+\s*", "", step)
        step = re.sub(r"^step\s*\d+\s*", "", step, flags=re.IGNORECASE)

        if len(step) > 3:
            steps.append(step)

    return steps


def store_embeddings(chunks):
    """
    Placeholder storage for embeddings.
    Later this will store vectors in Qdrant.
    """

    stored = []

    for i, chunk in enumerate(chunks):
        stored.append({
            "id": i,
            "text": chunk
        })

    return stored
