"""Common pytest fixtures for AI Debate Simulator v2 tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pytest

from models.schemas import (
    ClusterPrediction,
    ClusterProfile,
    Document,
    ForumPost,
    PipelineResult,
    PredictionResult,
)


@pytest.fixture
def sample_documents() -> List[Document]:
    """Nine documents spanning three conceptual groups for clustering tests."""
    docs: List[Document] = []
    topics = [
        ("AI Safety", "AI safety research focuses on alignment and interpretability of large language models."),
        ("AI Ethics", "Ethical considerations in AI include bias mitigation and fairness in machine learning systems."),
        ("AI Regulation", "Government regulation of AI systems requires transparent accountability frameworks."),
        ("Climate Change", "Climate change poses significant risks to global ecosystems and biodiversity."),
        ("Renewable Energy", "Renewable energy sources such as solar and wind are essential for sustainability."),
        ("Carbon Emissions", "Reducing carbon emissions is critical for meeting international climate targets."),
        ("Space Exploration", "Space exploration advances human understanding of the universe and drives technological innovation."),
        ("Mars Colonization", "Mars colonization requires solving radiation shielding and life support challenges."),
        ("Satellite Technology", "Satellite technology enables global communication and Earth observation systems."),
    ]
    for i, (title, content) in enumerate(topics):
        docs.append(
            Document(
                id=f"doc-{i}",
                source="test",
                title=title,
                content=content,
                url=f"https://example.com/doc-{i}",
                timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
                metadata={"group": i // 3},
            )
        )
    return docs


@pytest.fixture
def sample_clusters() -> List[ClusterProfile]:
    """Three sample opinion clusters with varying weights."""
    return [
        ClusterProfile(
            cluster_id=0,
            label="ai-safety-alignment",
            weight=0.5,
            document_count=5,
            key_arguments=[
                "AI alignment research is essential for safe deployment.",
                "Interpretability methods must be developed alongside capabilities.",
            ],
            keywords=["ai", "safety", "alignment", "interpretability"],
            sentiment=0.3,
        ),
        ClusterProfile(
            cluster_id=1,
            label="ai-regulation-governance",
            weight=0.3,
            document_count=3,
            key_arguments=[
                "Government oversight prevents unchecked AI deployment.",
                "International cooperation is needed for AI governance.",
            ],
            keywords=["regulation", "governance", "oversight"],
            sentiment=-0.1,
        ),
        ClusterProfile(
            cluster_id=2,
            label="ai-innovation-progress",
            weight=0.2,
            document_count=2,
            key_arguments=[
                "Open innovation accelerates beneficial AI development.",
            ],
            keywords=["innovation", "progress", "open"],
            sentiment=0.6,
        ),
    ]


@pytest.fixture
def sample_posts() -> List[ForumPost]:
    """Sample forum posts from two agents across two rounds."""
    base_time = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    return [
        ForumPost(
            post_id="post-001",
            agent_id="agent-0-ai-safety",
            round=1,
            timestamp=base_time,
            content="AI alignment research is crucial for preventing catastrophic outcomes.",
            cluster_id=0,
            influence_weight=1.0,
            stance_shift=0.1,
        ),
        ForumPost(
            post_id="post-002",
            agent_id="agent-1-ai-regulation",
            round=1,
            timestamp=base_time,
            content="Without proper regulation, AI systems risk harming vulnerable populations.",
            reply_to="post-001",
            cluster_id=1,
            influence_weight=0.8,
            stance_shift=-0.05,
        ),
        ForumPost(
            post_id="post-003",
            agent_id="agent-0-ai-safety",
            round=2,
            timestamp=base_time,
            content="Technical alignment solutions complement regulatory approaches effectively.",
            reply_to="post-002",
            cluster_id=0,
            influence_weight=1.0,
            stance_shift=0.05,
        ),
        ForumPost(
            post_id="post-004",
            agent_id="agent-2-ai-innovation",
            round=2,
            timestamp=base_time,
            content="Open innovation frameworks enable rapid progress while maintaining safety standards.",
            cluster_id=2,
            influence_weight=0.6,
        ),
    ]


@pytest.fixture
def sample_prediction(sample_clusters: List[ClusterProfile]) -> PredictionResult:
    """Sample prediction result derived from sample_clusters."""
    return PredictionResult(
        topic="AI Safety and Governance",
        cluster_predictions=[
            ClusterPrediction(
                cluster_label="ai-safety-alignment",
                weight=0.5,
                debate_score=0.8,
                weighted_score=0.4,
                stance_shift=0.1,
                key_arguments_survived=[
                    "AI alignment research is essential for safe deployment.",
                ],
            ),
            ClusterPrediction(
                cluster_label="ai-regulation-governance",
                weight=0.3,
                debate_score=0.7,
                weighted_score=0.21,
                stance_shift=-0.05,
                key_arguments_survived=[
                    "Government oversight prevents unchecked AI deployment.",
                ],
            ),
            ClusterPrediction(
                cluster_label="ai-innovation-progress",
                weight=0.2,
                debate_score=0.6,
                weighted_score=0.12,
                stance_shift=0.0,
                key_arguments_survived=[
                    "Open innovation accelerates beneficial AI development.",
                ],
            ),
        ],
        dominant_opinion="ai-safety-alignment",
        confidence=0.75,
        consensus_level=0.45,
    )


@pytest.fixture
def sample_pipeline_result(
    sample_clusters: List[ClusterProfile],
    sample_prediction: PredictionResult,
) -> PipelineResult:
    """Sample pipeline result combining clusters and prediction."""
    return PipelineResult(
        pipeline_id="test-pipeline-001",
        status="completed",
        clusters=sample_clusters,
        prediction=sample_prediction,
        report="The dominant opinion on AI Safety favors alignment research.",
    )
