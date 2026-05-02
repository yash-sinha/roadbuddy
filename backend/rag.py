import os
import shutil
import sqlite3
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from .synthetic_data import POLICY_TEXT, generate_policy

POLICY_PATH = os.path.join(os.path.dirname(__file__), "..", "policy.txt")
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "chroma_db")
COLLECTION_NAME = "policy_chunks"

_collection: chromadb.Collection | None = None


def _chunk_text(text: str, chunk_words: int = 200, overlap_words: int = 20) -> list[str]:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i: i + chunk_words])
        chunks.append(chunk)
        i += chunk_words - overlap_words
    return chunks


def _make_client_and_collection() -> chromadb.Collection:
    ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    return client.get_or_create_collection(COLLECTION_NAME, embedding_function=ef)


def _reset_chroma_store() -> None:
    if os.path.exists(CHROMA_PATH):
        shutil.rmtree(CHROMA_PATH)


def init() -> None:
    global _collection

    if not os.path.exists(POLICY_PATH):
        generate_policy(POLICY_PATH)

    try:
        _collection = _make_client_and_collection()
    except sqlite3.OperationalError as exc:
        # Older Chroma releases created an incompatible SQLite schema.
        # The vector store is only a cache, so rebuild it automatically.
        if "collections.topic" not in str(exc):
            raise
        print("[RAG] Detected incompatible Chroma schema. Rebuilding local vector store.")
        _reset_chroma_store()
        _collection = _make_client_and_collection()

    if _collection.count() == 0:
        with open(POLICY_PATH) as f:
            text = f.read()
        chunks = _chunk_text(text)
        _collection.add(
            documents=chunks,
            ids=[f"chunk_{i}" for i in range(len(chunks))],
        )


def reinit(policy_text: str) -> None:
    """Replace the policy document and rebuild the vector index."""
    global _collection
    with open(POLICY_PATH, "w") as f:
        f.write(policy_text)
    ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    _collection = client.create_collection(COLLECTION_NAME, embedding_function=ef)
    chunks = _chunk_text(policy_text)
    _collection.add(
        documents=chunks,
        ids=[f"chunk_{i}" for i in range(len(chunks))],
    )


def get_policy_text() -> str:
    if not os.path.exists(POLICY_PATH):
        generate_policy(POLICY_PATH)
    with open(POLICY_PATH) as f:
        return f.read()


def query(claim_string: str, n_results: int = 3) -> list[str]:
    if _collection is None:
        raise RuntimeError("RAG not initialised — call rag.init() first")
    results = _collection.query(query_texts=[claim_string], n_results=n_results)
    return results["documents"][0]
