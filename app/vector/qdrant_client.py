from qdrant_client import QdrantClient
from qdrant_client.http import models
from app.core.config.settings import settings
from typing import List

client = QdrantClient(url=settings.qdrant_url)


def create_collection(collection_name: str, vector_size: int):
    """
    Create collection if it does not exist.
    """
    collections = client.get_collections().collections
    existing = [c.name for c in collections]

    if collection_name not in existing:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE
            )
        )


def upsert_vector(
    collection_name: str,
    vector_id: str,
    embedding: List[float],
    payload: dict
):
    """
    Insert or update vector.
    """
    client.upsert(
        collection_name=collection_name,
        points=[
            models.PointStruct(
                id=vector_id,
                vector=embedding,
                payload=payload
            )
        ]
    )


def search_vectors(
    collection_name: str,
    query_vector: List[float],
    limit: int = 5
):
    """
    Perform semantic search.
    """
    results = client.search(
        collection_name=collection_name,
        query_vector=query_vector,
        limit=limit
    )

    return [
        {
            "id": r.id,
            "score": r.score,
            "payload": r.payload
        }
        for r in results
    ]
