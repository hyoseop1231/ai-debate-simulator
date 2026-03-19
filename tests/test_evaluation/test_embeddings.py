"""Tests for evaluation.embeddings -- EmbeddingSimilarity."""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from evaluation.embeddings import EmbeddingSimilarity, _FallbackEmbedder


@pytest.fixture
def similarity() -> EmbeddingSimilarity:
    """EmbeddingSimilarity with a TF-IDF fallback embedder to avoid
    loading sentence-transformers in tests."""
    sim = EmbeddingSimilarity()
    # Force fallback embedder so tests run without sentence-transformers GPU load
    sim._embedder = _FallbackEmbedder()
    return sim


class TestCosineSimilarityIdentical:
    """test_cosine_similarity_identical: same text -> ~1.0."""

    def test_identical_texts(self, similarity: EmbeddingSimilarity) -> None:
        score = similarity.cosine_similarity(
            "AI safety is important for humanity",
            "AI safety is important for humanity",
        )
        assert score > 0.99, f"Expected ~1.0 for identical texts, got {score}"


class TestCosineSimilarityDifferent:
    """test_cosine_similarity_different: unrelated text -> low score."""

    def test_unrelated_texts(self, similarity: EmbeddingSimilarity) -> None:
        score = similarity.cosine_similarity(
            "Quantum computing uses qubits for parallel processing",
            "The recipe for chocolate cake requires flour and cocoa",
        )
        # Unrelated texts should have low similarity
        assert score < 0.5, f"Expected low similarity for unrelated texts, got {score}"


class TestEvaluateRelevance:
    """test_evaluate_relevance: relevant > irrelevant."""

    def test_relevant_higher_than_irrelevant(
        self, similarity: EmbeddingSimilarity
    ) -> None:
        topic = "artificial intelligence safety and alignment"

        relevant_score = similarity.evaluate_relevance(
            "AI alignment research focuses on ensuring safe AI systems",
            topic,
        )
        irrelevant_score = similarity.evaluate_relevance(
            "The weather forecast shows rain tomorrow afternoon",
            topic,
        )
        assert relevant_score > irrelevant_score

    def test_empty_argument_returns_zero(
        self, similarity: EmbeddingSimilarity
    ) -> None:
        score = similarity.evaluate_relevance("", "some topic")
        assert score == 0.0

    def test_empty_topic_returns_zero(
        self, similarity: EmbeddingSimilarity
    ) -> None:
        score = similarity.evaluate_relevance("some argument", "   ")
        assert score == 0.0


class TestEvaluateOriginality:
    """test_evaluate_originality: novel > repeated."""

    def test_novel_argument_more_original(
        self, similarity: EmbeddingSimilarity
    ) -> None:
        previous = [
            "AI safety requires alignment research",
            "Government regulation is needed for AI",
        ]
        novel_score = similarity.evaluate_originality(
            "Space exploration drives innovation in materials science",
            previous,
        )
        repeated_score = similarity.evaluate_originality(
            "AI safety needs alignment research and development",
            previous,
        )
        assert novel_score > repeated_score

    def test_first_argument_default_score(
        self, similarity: EmbeddingSimilarity
    ) -> None:
        score = similarity.evaluate_originality("Any argument", [])
        assert score == 0.7

    def test_empty_argument_returns_zero(
        self, similarity: EmbeddingSimilarity
    ) -> None:
        score = similarity.evaluate_originality("  ", ["some previous argument"])
        assert score == 0.0


class TestDetectRepetition:
    """test_detect_repetition: same texts detected."""

    def test_identical_rounds_detected(
        self, similarity: EmbeddingSimilarity
    ) -> None:
        texts = [
            "AI safety is essential for responsible deployment",
            "Regulation frameworks must keep pace with AI progress",
        ]
        is_repetitive = similarity.detect_repetition(
            round_n_texts=texts,
            round_n_minus_1_texts=texts,
            threshold=0.85,
        )
        assert is_repetitive is True

    def test_different_rounds_not_detected(
        self, similarity: EmbeddingSimilarity
    ) -> None:
        round_1 = ["AI safety is essential for responsible deployment"]
        round_2 = ["Chocolate cake recipes require flour and butter"]
        is_repetitive = similarity.detect_repetition(
            round_n_texts=round_2,
            round_n_minus_1_texts=round_1,
            threshold=0.85,
        )
        assert is_repetitive is False

    def test_empty_round_not_repetitive(
        self, similarity: EmbeddingSimilarity
    ) -> None:
        assert similarity.detect_repetition([], ["text"]) is False
        assert similarity.detect_repetition(["text"], []) is False


class TestFallbackEmbedder:
    """test_fallback_embedder: works when sentence-transformers unavailable."""

    def test_fallback_embed_returns_array(self) -> None:
        embedder = _FallbackEmbedder()
        result = embedder.embed(["Hello world", "Test text"])
        assert isinstance(result, np.ndarray)
        assert result.shape[0] == 2
        assert result.shape[1] > 0

    def test_fallback_embed_single(self) -> None:
        embedder = _FallbackEmbedder()
        result = embedder.embed_single("Hello world")
        assert isinstance(result, np.ndarray)
        assert result.ndim == 1

    def test_fallback_embed_empty(self) -> None:
        embedder = _FallbackEmbedder()
        result = embedder.embed([])
        assert result.shape == (0, 0)

    def test_similarity_uses_fallback_when_import_fails(self) -> None:
        sim = EmbeddingSimilarity()
        # Patch clustering.engine import to fail
        with patch.dict("sys.modules", {"clustering.engine": None}):
            sim._embedder = None  # Reset to force re-initialization
            # Access embedder property -- should fall back to _FallbackEmbedder
            embedder = sim.embedder
            assert isinstance(embedder, _FallbackEmbedder)


class TestBatchSimilarity:
    """Test batch_similarity returns correct shape."""

    def test_batch_returns_square_matrix(
        self, similarity: EmbeddingSimilarity
    ) -> None:
        texts = ["text one", "text two", "text three"]
        matrix = similarity.batch_similarity(texts)
        assert matrix.shape == (3, 3)
        # Diagonal should be ~1.0
        for i in range(3):
            assert matrix[i, i] > 0.99

    def test_batch_empty(self, similarity: EmbeddingSimilarity) -> None:
        matrix = similarity.batch_similarity([])
        assert matrix.shape == (0, 0)
