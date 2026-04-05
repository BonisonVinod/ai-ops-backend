from sentence_transformers import SentenceTransformer
from typing import List

# Global cached model
_model = None


def load_model():
    """
    Load embedding model once and cache it.
    """
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding for a single text.
    """
    model = load_model()
    return model.encode(text).tolist()


def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for multiple texts.
    """
    model = load_model()
    return model.encode(texts).tolist()
