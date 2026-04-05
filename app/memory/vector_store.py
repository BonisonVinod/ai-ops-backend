import chromadb
import os
from app.memory.embeddings import get_embedding

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
PERSIST_PATH = os.path.join(BASE_DIR, "chroma_db")

print("Chroma will persist at:", PERSIST_PATH)  # DEBUG

client = chromadb.PersistentClient(path=PERSIST_PATH)

collection = client.get_or_create_collection(name="tickets")

def store_ticket(ticket_text: str, metadata: dict):
    """
    Store only high-quality resolved tickets
    """

    # 🔹 Condition (relaxed for now)
    if metadata.get("confidence", 0) < 70:
        return

    # 🔹 Check duplicates safely
    existing = retrieve_similar(ticket_text, n_results=1)

    if existing and "documents" in existing:
        docs = existing.get("documents", [[]])
        if docs and docs[0] and ticket_text in docs[0]:
            return

    # 🔹 Generate embedding
    embedding = get_embedding(ticket_text)

    # 🔹 Flatten metadata (IMPORTANT)
    clean_metadata = {
        "category": metadata.get("classification", {}).get("category"),
        "priority": metadata.get("classification", {}).get("priority"),
        "action": metadata.get("decision", {}).get("action"),
        "confidence": metadata.get("confidence"),
        "status": metadata.get("status")
    }

    collection.add(
        documents=[ticket_text],
        embeddings=[embedding],
        metadatas=[clean_metadata],
        ids=[str(hash(ticket_text))]
    )


def retrieve_similar(ticket_text: str, n_results: int = 3):
    """
    Retrieve similar past tickets
    """

    embedding = get_embedding(ticket_text)

    results = collection.query(
        query_embeddings=[embedding],
        n_results=n_results
    )

    return results
