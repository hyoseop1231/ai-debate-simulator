"""Embedding-based evaluation enhancements for L4.

Supplements the existing M-MAD heuristic evaluator with semantic similarity.
Reuses the same sentence-transformers model from clustering (L1).
"""

import logging
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class _FallbackEmbedder:
    """TF-IDF based fallback when sentence-transformers is unavailable.

    Provides the same ``embed`` / ``embed_single`` interface as
    :class:`clustering.engine.TextEmbedder` so callers need no branching.
    """

    def __init__(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vectorizer = TfidfVectorizer(
            max_features=512,
            stop_words="english",
            max_df=0.95,
            min_df=1,
            sublinear_tf=True,
        )
        self._fitted = False
        self._corpus: List[str] = []

    def _ensure_fitted(self, texts: List[str]) -> None:
        """Incrementally refit vectorizer when new texts arrive."""
        new_texts = [t for t in texts if t not in self._corpus]
        if new_texts or not self._fitted:
            self._corpus.extend(new_texts)
            fit_corpus = self._corpus if self._corpus else texts
            self._vectorizer.fit(fit_corpus)
            self._fitted = True

    def embed(self, texts: List[str]) -> np.ndarray:
        """Return (n_texts, n_features) dense matrix."""
        if not texts:
            return np.array([]).reshape(0, 0)
        self._ensure_fitted(texts)
        sparse = self._vectorizer.transform(texts)
        return sparse.toarray().astype(np.float32)

    def embed_single(self, text: str) -> np.ndarray:
        """Return 1-D vector for a single text."""
        return self.embed([text])[0]


class EmbeddingSimilarity:
    """Embedding-based similarity for evaluation enhancement.

    Reuses the same sentence-transformers model from clustering (L1).
    Supplements existing heuristic evaluator, does not replace it.

    Usage::

        sim = EmbeddingSimilarity()  # lazy loads model
        score = sim.evaluate_relevance("argument text", "topic text")
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.model_name = model_name
        self._embedder: Optional[object] = None  # Lazy load

    @property
    def embedder(self):
        """Lazy-load TextEmbedder from clustering module."""
        if self._embedder is None:
            try:
                from clustering.engine import TextEmbedder

                self._embedder = TextEmbedder(self.model_name)
            except (ImportError, Exception):
                logger.warning(
                    "clustering.engine / sentence-transformers not available, "
                    "using TF-IDF fallback embedder"
                )
                self._embedder = _FallbackEmbedder()
        return self._embedder

    # ------------------------------------------------------------------
    # Core similarity
    # ------------------------------------------------------------------

    def cosine_similarity(self, text_a: str, text_b: str) -> float:
        """Calculate cosine similarity between two texts."""
        emb_a = self.embedder.embed_single(text_a)
        emb_b = self.embedder.embed_single(text_b)
        dot = np.dot(emb_a, emb_b)
        norm = np.linalg.norm(emb_a) * np.linalg.norm(emb_b)
        if norm == 0:
            return 0.0
        return float(dot / norm)

    def batch_similarity(self, texts: List[str]) -> np.ndarray:
        """Calculate pairwise similarity matrix for a list of texts.

        Returns:
            (n, n) numpy array of cosine similarities.
        """
        if not texts:
            return np.array([]).reshape(0, 0)

        embeddings = self.embedder.embed(texts)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0  # avoid division by zero
        normalized = embeddings / norms
        return np.dot(normalized, normalized.T)

    # ------------------------------------------------------------------
    # Evaluation helpers
    # ------------------------------------------------------------------

    def evaluate_relevance(self, argument: str, topic: str) -> float:
        """Evaluate argument relevance to topic using embedding similarity.

        Replaces keyword matching in existing evaluator.
        Returns 0.0~1.0.
        """
        if not argument.strip() or not topic.strip():
            return 0.0
        sim = self.cosine_similarity(argument, topic)
        # Scale: cosine sim typically 0.0~0.8 for relevant text
        # Map to 0.0~1.0 evaluation score
        return min(1.0, max(0.0, sim * 1.25))

    def evaluate_originality(
        self,
        argument: str,
        previous_arguments: List[str],
    ) -> float:
        """Evaluate originality by comparing to all previous arguments.

        Replaces Jaccard similarity in existing evaluator.
        Returns 0.0~1.0 (1.0 = completely original).
        """
        if not previous_arguments:
            return 0.7  # Default for first argument

        if not argument.strip():
            return 0.0

        # Calculate max similarity to any previous argument
        max_sim = 0.0
        for prev in previous_arguments:
            if not prev.strip():
                continue
            sim = self.cosine_similarity(argument, prev)
            max_sim = max(max_sim, sim)

        # Invert: high similarity = low originality
        return max(0.0, 1.0 - max_sim * 0.8)

    def detect_repetition(
        self,
        round_n_texts: List[str],
        round_n_minus_1_texts: List[str],
        threshold: float = 0.85,
    ) -> bool:
        """Detect if current round is repeating previous round.

        Compares the average embedding of each round.  If cosine similarity
        exceeds *threshold*, the round is considered repetitive.

        Used for ForumEngine termination condition.
        """
        if not round_n_texts or not round_n_minus_1_texts:
            return False

        # Compute mean embeddings for each round
        emb_n = self.embedder.embed(round_n_texts)
        emb_prev = self.embedder.embed(round_n_minus_1_texts)

        if emb_n.size == 0 or emb_prev.size == 0:
            return False

        mean_n = np.mean(emb_n, axis=0)
        mean_prev = np.mean(emb_prev, axis=0)

        # Cosine similarity of the two mean vectors
        dot = np.dot(mean_n, mean_prev)
        norm = np.linalg.norm(mean_n) * np.linalg.norm(mean_prev)
        if norm == 0:
            return False

        similarity = float(dot / norm)
        return similarity >= threshold
