"""Pydantic v2 schema models for AI Debate Simulator v2."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from forum.config import ForumEngineConfig


class DebateStance(str, Enum):
    """Debate stance positions."""

    SUPPORT = "support"
    OPPOSE = "oppose"
    NEUTRAL = "neutral"


class Document(BaseModel):
    """Collected source document."""

    id: str = Field(..., description="Unique document identifier")
    source: str = Field(..., description="Source name (e.g. 'arxiv', 'news')")
    title: str = Field(..., description="Document title")
    content: str = Field(..., description="Full text content")
    url: Optional[str] = Field(None, description="Source URL")
    timestamp: Optional[datetime] = Field(None, description="Publication timestamp")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extra metadata")


class ClusterProfile(BaseModel):
    """Opinion cluster profile from document clustering."""

    cluster_id: int = Field(..., description="Cluster identifier")
    label: str = Field(..., description="Human-readable cluster label")
    weight: float = Field(..., ge=0.0, le=1.0, description="Relative weight of cluster")
    document_count: int = Field(..., ge=0, description="Number of documents in cluster")
    key_arguments: list[str] = Field(default_factory=list, description="Key arguments")
    keywords: list[str] = Field(default_factory=list, description="Representative keywords")
    sentiment: float = Field(0.0, ge=-1.0, le=1.0, description="Sentiment score")
    centroid: Optional[list[float]] = Field(None, description="Embedding centroid vector")


class ForumAgentConfig(BaseModel):
    """Configuration for a forum simulation agent."""

    agent_id: str = Field(..., description="Unique agent identifier")
    cluster_id: int = Field(..., description="Source cluster identifier")
    label: str = Field(..., description="Agent display label")
    weight: float = Field(1.0, ge=0.0, description="Cluster weight carried by agent")
    persona_prompt: str = Field(..., description="System prompt defining persona")
    key_arguments: list[str] = Field(default_factory=list, description="Key arguments")
    model: str = Field("qwen2.5-coder:32b", description="LLM model identifier")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="Sampling temperature")
    activity_level: float = Field(
        1.0, ge=0.0, le=1.0, description="How active the agent is"
    )
    active_hours: list[int] = Field(
        default_factory=lambda: list(range(24)),
        description="Hours when agent is active",
    )
    influence_weight: float = Field(
        1.0, ge=0.0, description="Influence weight in forum"
    )


class ForumPost(BaseModel):
    """Single post in a forum debate simulation."""

    post_id: str = Field(..., description="Unique post identifier")
    agent_id: str = Field(..., description="Author agent identifier")
    round: int = Field(..., ge=0, description="Forum round number")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="Post timestamp"
    )
    content: str = Field(..., description="Post text content")
    reply_to: Optional[str] = Field(None, description="Parent post id if reply")
    evidence_refs: list[str] = Field(
        default_factory=list, description="Referenced document ids"
    )
    stance_shift: Optional[float] = Field(
        None, description="Stance shift from previous post"
    )
    cluster_id: Optional[int] = Field(None, description="Source cluster identifier")
    influence_weight: float = Field(1.0, ge=0.0, description="Post influence weight")


class LogEntry(BaseModel):
    """Structured log entry for pipeline events."""

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="Entry timestamp"
    )
    source: str = Field(..., description="Component that produced the entry")
    content: str = Field(..., description="Log message content")
    round_number: Optional[int] = Field(None, description="Associated round number")
    entry_type: str = Field("info", description="Log level / entry type")


class Argument(BaseModel):
    """Debate argument with quality metadata."""

    content: str = Field(..., description="Argument text")
    agent_name: str = Field(..., description="Author agent name")
    stance: DebateStance = Field(..., description="Stance of the argument")
    round_number: int = Field(..., ge=0, description="Round in which argument was made")
    evidence: list[str] = Field(default_factory=list, description="Supporting evidence")
    confidence_score: float = Field(0.0, ge=0.0, le=1.0, description="Confidence")
    quality_score: float = Field(0.7, ge=0.0, le=1.0, description="Quality score")
    cluster_id: Optional[int] = Field(None, description="Source cluster identifier")
    influence_weight: float = Field(1.0, ge=0.0, description="Argument influence weight")


class ClusterPrediction(BaseModel):
    """Prediction result for a single opinion cluster."""

    cluster_label: str = Field(..., description="Cluster label")
    weight: float = Field(..., ge=0.0, le=1.0, description="Cluster weight")
    debate_score: float = Field(
        ..., ge=0.0, le=1.0, description="Score from debate performance"
    )
    weighted_score: float = Field(
        ..., ge=0.0, le=1.0, description="Weight-adjusted score"
    )
    stance_shift: float = Field(0.0, description="Net stance shift during debate")
    key_arguments_survived: list[str] = Field(
        default_factory=list, description="Arguments that survived scrutiny"
    )


class PredictionResult(BaseModel):
    """Aggregate prediction from debate analysis."""

    topic: str = Field(..., description="Debate topic")
    cluster_predictions: list[ClusterPrediction] = Field(
        default_factory=list, description="Per-cluster predictions"
    )
    dominant_opinion: str = Field(..., description="Predicted dominant opinion")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Overall confidence")
    consensus_level: float = Field(
        0.0, ge=0.0, le=1.0, description="Level of consensus reached"
    )


class RuleAgentProfile(BaseModel):
    """Profile for a rule-based swarm simulation agent."""

    agent_id: str = Field(..., description="Unique agent identifier")
    entity_type: str = Field(..., description="Entity type (person, org, etc.)")
    activity_level: float = Field(
        1.0, ge=0.0, le=1.0, description="Base activity level"
    )
    active_hours: list[int] = Field(
        default_factory=lambda: list(range(24)),
        description="Hours when agent is active",
    )
    sentiment_bias: float = Field(
        0.0, ge=-1.0, le=1.0, description="Baseline sentiment bias"
    )
    influence_weight: float = Field(
        1.0, ge=0.0, description="Social influence weight"
    )
    stance: DebateStance = Field(
        DebateStance.NEUTRAL, description="Default stance position"
    )


class PipelineConfig(BaseModel):
    """End-to-end pipeline configuration."""

    topic: str = Field(..., description="Debate topic")
    sources: list[str] = Field(
        default_factory=lambda: ["news", "arxiv"],
        description="Data source identifiers",
    )
    max_docs: int = Field(50, ge=1, description="Max documents to collect per source")
    cluster_method: str = Field(
        "hdbscan", description="Clustering algorithm identifier"
    )
    forum_config: ForumEngineConfig = Field(
        default_factory=lambda: __import__("forum.config", fromlist=["ForumEngineConfig"]).ForumEngineConfig(),
        description="Forum simulation config",
    )
    enable_swarm: bool = Field(False, description="Enable swarm opinion simulation")
    swarm_agent_count: int = Field(
        100, ge=1, description="Number of swarm simulation agents"
    )
    report_format: str = Field("html", description="Output report format")


class PipelineResult(BaseModel):
    """Result of a complete pipeline execution."""

    pipeline_id: str = Field(..., description="Unique pipeline run identifier")
    status: str = Field("pending", description="Pipeline status")
    clusters: list[ClusterProfile] = Field(
        default_factory=list, description="Discovered clusters"
    )
    debate_result: Optional[dict[str, Any]] = Field(
        None, description="Forum debate results"
    )
    prediction: Optional[PredictionResult] = Field(
        None, description="Final prediction"
    )
    report: Optional[str] = Field(None, description="Generated report content")


def _rebuild_forward_refs() -> None:
    """Rebuild Pydantic models that use deferred forward references."""
    from forum.config import ForumEngineConfig as _ForumEngineConfig

    PipelineConfig.model_rebuild(_types_namespace={"ForumEngineConfig": _ForumEngineConfig})


_rebuild_forward_refs()
