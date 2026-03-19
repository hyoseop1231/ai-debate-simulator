"""Tests for evaluation.predictor -- ClusterWeightedPredictor."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, List

import pytest

from evaluation.predictor import ClusterWeightedPredictor
from models.schemas import ClusterProfile, ForumPost, PredictionResult


@pytest.fixture
def predictor() -> ClusterWeightedPredictor:
    return ClusterWeightedPredictor()


@pytest.fixture
def two_clusters() -> List[ClusterProfile]:
    return [
        ClusterProfile(
            cluster_id=0,
            label="pro-ai",
            weight=0.6,
            document_count=6,
            key_arguments=["AI benefits society"],
            sentiment=0.4,
        ),
        ClusterProfile(
            cluster_id=1,
            label="anti-ai",
            weight=0.4,
            document_count=4,
            key_arguments=["AI poses risks"],
            sentiment=-0.3,
        ),
    ]


@pytest.fixture
def debate_scores() -> Dict[int, float]:
    return {0: 0.8, 1: 0.6}


@pytest.fixture
def minimal_posts() -> List[ForumPost]:
    return [
        ForumPost(
            post_id="p1",
            agent_id="a0",
            round=1,
            content="AI is beneficial for healthcare.",
            cluster_id=0,
            stance_shift=0.1,
        ),
        ForumPost(
            post_id="p2",
            agent_id="a1",
            round=1,
            content="AI risks are underestimated.",
            cluster_id=1,
            stance_shift=-0.05,
        ),
    ]


class TestPredictBasic:
    """test_predict_basic: produces PredictionResult."""

    def test_predict_basic(
        self,
        predictor: ClusterWeightedPredictor,
        two_clusters: List[ClusterProfile],
        debate_scores: Dict[int, float],
        minimal_posts: List[ForumPost],
    ) -> None:
        result = predictor.predict(two_clusters, debate_scores, minimal_posts)

        assert isinstance(result, PredictionResult)
        assert len(result.cluster_predictions) == 2
        assert result.dominant_opinion  # non-empty
        assert 0.0 <= result.confidence <= 1.0
        assert 0.0 <= result.consensus_level <= 1.0

    def test_predictions_sorted_by_weighted_score(
        self,
        predictor: ClusterWeightedPredictor,
        two_clusters: List[ClusterProfile],
        debate_scores: Dict[int, float],
        minimal_posts: List[ForumPost],
    ) -> None:
        result = predictor.predict(two_clusters, debate_scores, minimal_posts)
        scores = [cp.weighted_score for cp in result.cluster_predictions]
        assert scores == sorted(scores, reverse=True)


class TestWeightedScoreFormula:
    """test_weighted_score_formula: weight * score * (1 + shift)."""

    def test_formula_without_shift(
        self,
        predictor: ClusterWeightedPredictor,
        two_clusters: List[ClusterProfile],
        debate_scores: Dict[int, float],
    ) -> None:
        # Posts without stance_shift
        posts = [
            ForumPost(
                post_id="p1",
                agent_id="a0",
                round=1,
                content="Content",
                cluster_id=0,
            ),
        ]
        result = predictor.predict(two_clusters, debate_scores, posts)

        # For cluster 0: weight=0.6, debate_score=0.8, shift=0.0
        # weighted = 0.6 * 0.8 * (1 + 0.0) = 0.48
        pro_pred = next(
            cp for cp in result.cluster_predictions if cp.cluster_label == "pro-ai"
        )
        assert pro_pred.weighted_score == pytest.approx(0.48, abs=0.01)

    def test_formula_with_positive_shift(
        self,
        predictor: ClusterWeightedPredictor,
    ) -> None:
        clusters = [
            ClusterProfile(
                cluster_id=0, label="test", weight=0.5, document_count=5
            ),
        ]
        scores = {0: 0.8}
        posts = [
            ForumPost(
                post_id="p1",
                agent_id="a0",
                round=1,
                content="Content",
                cluster_id=0,
                stance_shift=0.2,
            ),
        ]
        result = predictor.predict(clusters, scores, posts)

        # weight=0.5, score=0.8, shift=0.2
        # weighted = 0.5 * 0.8 * (1 + 0.2) = 0.48
        assert result.cluster_predictions[0].weighted_score == pytest.approx(0.48, abs=0.01)


class TestDominantOpinion:
    """test_dominant_opinion: highest weighted score wins."""

    def test_dominant_is_highest_weighted(
        self,
        predictor: ClusterWeightedPredictor,
        two_clusters: List[ClusterProfile],
        debate_scores: Dict[int, float],
        minimal_posts: List[ForumPost],
    ) -> None:
        result = predictor.predict(two_clusters, debate_scores, minimal_posts)
        # pro-ai has weight=0.6, score=0.8 -> higher weighted score
        assert result.dominant_opinion == "pro-ai"

    def test_dominant_changes_with_scores(
        self,
        predictor: ClusterWeightedPredictor,
        two_clusters: List[ClusterProfile],
        minimal_posts: List[ForumPost],
    ) -> None:
        # Reverse the scores: anti-ai gets higher score
        reversed_scores = {0: 0.3, 1: 0.95}
        result = predictor.predict(two_clusters, reversed_scores, minimal_posts)
        # anti-ai: 0.4 * 0.95 * (1 + (-0.05)) = 0.361
        # pro-ai: 0.6 * 0.3 * (1 + 0.1) = 0.198
        assert result.dominant_opinion == "anti-ai"


class TestConsensusCalculation:
    """test_consensus_calculation: entropy-based."""

    def test_single_cluster_full_consensus(
        self, predictor: ClusterWeightedPredictor
    ) -> None:
        clusters = [
            ClusterProfile(
                cluster_id=0, label="only", weight=1.0, document_count=10
            ),
        ]
        posts = [
            ForumPost(
                post_id="p1", agent_id="a0", round=1, content="C", cluster_id=0
            ),
        ]
        result = predictor.predict(clusters, {0: 0.8}, posts)
        assert result.consensus_level == 1.0

    def test_equal_clusters_low_consensus(
        self, predictor: ClusterWeightedPredictor
    ) -> None:
        clusters = [
            ClusterProfile(
                cluster_id=0, label="a", weight=0.5, document_count=5
            ),
            ClusterProfile(
                cluster_id=1, label="b", weight=0.5, document_count=5
            ),
        ]
        posts = [
            ForumPost(
                post_id="p1", agent_id="a0", round=1, content="C", cluster_id=0
            ),
            ForumPost(
                post_id="p2", agent_id="a1", round=1, content="C", cluster_id=1
            ),
        ]
        # Equal weights + equal scores -> maximum entropy -> low consensus
        result = predictor.predict(clusters, {0: 0.5, 1: 0.5}, posts)
        assert result.consensus_level < 0.1  # Near zero for uniform distribution


class TestEmptyPosts:
    """test_empty_posts: handles gracefully."""

    def test_empty_posts_no_crash(
        self, predictor: ClusterWeightedPredictor
    ) -> None:
        result = predictor.predict([], {}, [])
        assert isinstance(result, PredictionResult)
        assert result.dominant_opinion == ""
        assert result.confidence == 0.0
        assert result.consensus_level == 0.0
        assert result.cluster_predictions == []

    def test_clusters_without_posts(
        self, predictor: ClusterWeightedPredictor, two_clusters: List[ClusterProfile]
    ) -> None:
        result = predictor.predict(two_clusters, {0: 0.5, 1: 0.5}, [])
        assert len(result.cluster_predictions) == 2
        assert result.dominant_opinion  # should still pick one


class TestExtractTopic:
    """Test _extract_topic helper."""

    def test_extracts_from_first_post(
        self, predictor: ClusterWeightedPredictor
    ) -> None:
        posts = [
            ForumPost(
                post_id="p1",
                agent_id="a0",
                round=1,
                content="AI safety is critical. More details follow.",
                cluster_id=0,
            ),
        ]
        topic = predictor._extract_topic(posts)
        assert "AI safety is critical." in topic

    def test_empty_posts_returns_empty(
        self, predictor: ClusterWeightedPredictor
    ) -> None:
        assert predictor._extract_topic([]) == ""
