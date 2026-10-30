from functools import lru_cache

from repoguide.config import settings
from repoguide.telemetry import observed


class EmbeddingService:
    def __init__(self):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(settings.embedding_model)

        dimension = self.model.get_sentence_embedding_dimension()
        if dimension != settings.embedding_dim:
            raise ValueError(
                f"Expected {settings.embedding_dim} dimensions, got {dimension}"
            )

    @observed("embedding.documents", "CHAIN")
    def encode_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors = self.model.encode_document(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    @observed("embedding.query", "CHAIN")
    def encode_query(self, text: str) -> list[float]:
        vector = self.model.encode_query(
            text,
            normalize_embeddings=True,
        )
        return vector.tolist()


@lru_cache
def get_embedding_service() -> EmbeddingService:
    return EmbeddingService()
