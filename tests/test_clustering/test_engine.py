"""Tests for clustering.engine -- OpinionClusterEngine and TextEmbedder."""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from clustering.engine import OpinionClusterEngine, TextEmbedder, _cosine_similarity_batch
from models.schemas import ClusterProfile, Document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_docs(n: int, prefix: str = "doc") -> List[Document]:
    """Create n minimal documents with distinct content."""
    return [
        Document(
            id=f"{prefix}-{i}",
            source="test",
            title=f"Title {prefix} {i}",
            content=f"Content about topic {prefix} number {i}. " * 5,
        )
        for i in range(n)
    ]


def _fake_embedder() -> MagicMock:
    """Return a mock TextEmbedder that produces deterministic embeddings."""
    mock = MagicMock(spec=TextEmbedder)

    def _embed(texts: List[str]) -> np.ndarray:
        rng = np.random.RandomState(42)
        return rng.rand(len(texts), 64).astype(np.float32)

    def _embed_single(text: str) -> np.ndarray:
        rng = np.random.RandomState(hash(text) % 2**31)
        return rng.rand(64).astype(np.float32)

    mock.embed.side_effect = _embed
    mock.embed_single.side_effect = _embed_single
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClusterWithKMeans:
    """test_cluster_with_kmeans: 9 docs -> 3 clusters, weights sum to 1.0."""

    def test_cluster_with_kmeans(self, sample_documents: List[Document]) -> None:
        engine = OpinionClusterEngine()
        engine.embedder = _fake_embedder()

        profiles = engine.cluster(sample_documents, n_clusters=3)

        assert len(profiles) == 3
        total_weight = sum(p.weight for p in profiles)
        assert abs(total_weight - 1.0) < 1e-4, f"Weights sum to {total_weight}, expected 1.0"
        for p in profiles:
            assert p.document_count > 0
            assert 0.0 <= p.weight <= 1.0

    def test_cluster_document_counts_match(self, sample_documents: List[Document]) -> None:
        engine = OpinionClusterEngine()
        engine.embedder = _fake_embedder()

        profiles = engine.cluster(sample_documents, n_clusters=3)
        total_docs = sum(p.document_count for p in profiles)
        assert total_docs == len(sample_documents)


class TestClusterWithHDBSCAN:
    """test_cluster_with_hdbscan: enough docs for auto-clustering."""

    def test_cluster_with_hdbscan(self) -> None:
        docs = _make_docs(20, prefix="hdbscan")
        engine = OpinionClusterEngine(min_cluster_size=3, min_samples=2)
        engine.embedder = _fake_embedder()

        profiles = engine.cluster(docs, n_clusters=None)

        assert len(profiles) >= 1
        total_weight = sum(p.weight for p in profiles)
        assert abs(total_weight - 1.0) < 1e-4


class TestSingleDocument:
    """test_single_document: edge case -- single doc produces one cluster."""

    def test_single_document(self) -> None:
        docs = _make_docs(1, prefix="single")
        engine = OpinionClusterEngine()
        engine.embedder = _fake_embedder()

        profiles = engine.cluster(docs)

        assert len(profiles) == 1
        assert profiles[0].weight == 1.0
        assert profiles[0].document_count == 1
        assert profiles[0].cluster_id == 0


class TestEmptyDocuments:
    """test_empty_documents: should handle gracefully."""

    def test_empty_documents(self) -> None:
        engine = OpinionClusterEngine()
        profiles = engine.cluster([])
        assert profiles == []


class TestClusterLabelsSafe:
    """test_cluster_labels_safe: no slashes or special chars in labels."""

    def test_cluster_labels_safe(self, sample_documents: List[Document]) -> None:
        engine = OpinionClusterEngine()
        engine.embedder = _fake_embedder()

        profiles = engine.cluster(sample_documents, n_clusters=3)

        unsafe_chars = set("/\\<>:\"'|?*")
        for p in profiles:
            assert not any(ch in p.label for ch in unsafe_chars), (
                f"Label '{p.label}' contains unsafe characters"
            )


class TestEmbedderLazyLoad:
    """test_embedder_lazy_load: model not loaded until first use."""

    def test_embedder_lazy_load(self) -> None:
        embedder = TextEmbedder(model_name="all-MiniLM-L6-v2")
        # Internal _model should be None before any embedding call
        assert embedder._model is None

    def test_embedder_empty_texts(self) -> None:
        embedder = TextEmbedder()
        result = embedder.embed([])
        assert result.shape == (0, 0)


class TestCosineSimilarityBatch:
    """Unit tests for the module-level _cosine_similarity_batch helper."""

    def test_identical_vectors(self) -> None:
        v = np.array([1.0, 2.0, 3.0])
        embeddings = np.array([v, v])
        sims = _cosine_similarity_batch(embeddings, v)
        np.testing.assert_allclose(sims, [1.0, 1.0], atol=1e-6)

    def test_zero_target(self) -> None:
        embeddings = np.array([[1.0, 2.0], [3.0, 4.0]])
        target = np.array([0.0, 0.0])
        sims = _cosine_similarity_batch(embeddings, target)
        np.testing.assert_array_equal(sims, [0.0, 0.0])
