"""Rule-based agents for swarm simulation -- no LLM calls."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from models.schemas import ClusterProfile


# @MX:NOTE: MiroFish entity type defaults for activity/influence configuration
ENTITY_TYPE_DEFAULTS: Dict[str, Dict[str, object]] = {
    "Expert": {
        "activity_level": 0.3,
        "influence_weight": 3.0,
        "active_hours": list(range(9, 18)),
    },
    "Media": {
        "activity_level": 0.5,
        "influence_weight": 2.5,
        "active_hours": list(range(7, 24)),
    },
    "Student": {
        "activity_level": 0.8,
        "influence_weight": 0.8,
        "active_hours": list(range(8, 14)) + list(range(18, 24)),
    },
    "General": {
        "activity_level": 0.7,
        "influence_weight": 1.0,
        "active_hours": list(range(9, 14)) + list(range(18, 24)),
    },
    "Institution": {
        "activity_level": 0.2,
        "influence_weight": 3.0,
        "active_hours": list(range(9, 18)),
    },
}

ENTITY_TYPE_DISTRIBUTION: Dict[str, float] = {
    "General": 0.50,
    "Student": 0.25,
    "Expert": 0.10,
    "Media": 0.10,
    "Institution": 0.05,
}


def _sentiment_to_stance(sentiment: float) -> str:
    """Map a sentiment value to a stance label."""
    if sentiment > 0.3:
        return "support"
    if sentiment < -0.3:
        return "oppose"
    return "neutral"


@dataclass
class RuleAgent:
    """Rule-based agent -- no LLM calls.

    Makes decisions based on:
    - sentiment_bias: initial tendency (-1.0 to 1.0)
    - influence_weight: how much this agent affects neighbors
    - Neighbor influence: aggregated neighbor stances
    """

    agent_id: str
    cluster_id: int
    entity_type: str  # Expert, Media, Student, General, Institution
    activity_level: float  # 0.0~1.0 -- probability of participation per step
    active_hours: List[int]  # Hours when agent is active
    sentiment_bias: float  # -1.0 (oppose) ~ 1.0 (support)
    influence_weight: float  # How much this agent influences neighbors
    stance: str  # Current stance label
    neighbors: List[str] = field(default_factory=list)

    def act(self, neighbor_influence: Dict[str, float]) -> str:
        """Rule-based vote decision.

        Combines own sentiment_bias with neighbor influence.
        Returns: "support", "oppose", "neutral", or "abstain"
        """
        # Own sentiment contributes 70%
        own_weight = 0.7
        neighbor_weight = 0.3

        # Neighbor influence is a dict like {"support": 0.6, "oppose": 0.3, "neutral": 0.1}
        # Convert to a single sentiment score: support=+1, oppose=-1, neutral=0
        neighbor_sentiment = 0.0
        total_neighbor = sum(neighbor_influence.values()) if neighbor_influence else 0.0
        if total_neighbor > 0:
            neighbor_sentiment = (
                neighbor_influence.get("support", 0.0)
                - neighbor_influence.get("oppose", 0.0)
            ) / total_neighbor

        # Effective sentiment with random noise for diversity
        noise = random.gauss(0, 0.05)
        effective = (
            own_weight * self.sentiment_bias
            + neighbor_weight * neighbor_sentiment
            + noise
        )

        # Clamp to [-1, 1]
        effective = max(-1.0, min(1.0, effective))

        # Update internal sentiment_bias slightly toward effective (learning)
        self.sentiment_bias = 0.95 * self.sentiment_bias + 0.05 * effective

        # Low-activity agents sometimes abstain
        if random.random() > self.activity_level * 1.2:
            return "abstain"

        # Map to vote
        if effective > 0.25:
            self.stance = "support"
            return "support"
        if effective < -0.25:
            self.stance = "oppose"
            return "oppose"
        self.stance = "neutral"
        return "neutral"

    @classmethod
    def create_for_cluster(
        cls,
        cluster: ClusterProfile,
        agent_idx: int,
        entity_type: str,
    ) -> RuleAgent:
        """Create a rule agent for a specific cluster."""
        defaults = ENTITY_TYPE_DEFAULTS.get(entity_type, ENTITY_TYPE_DEFAULTS["General"])

        # Add per-agent variance to sentiment based on cluster sentiment
        base_sentiment = cluster.sentiment
        variance = random.gauss(0, 0.15)
        sentiment = max(-1.0, min(1.0, base_sentiment + variance))

        return cls(
            agent_id=f"c{cluster.cluster_id}_a{agent_idx}",
            cluster_id=cluster.cluster_id,
            entity_type=entity_type,
            activity_level=float(defaults["activity_level"]),  # type: ignore[arg-type]
            active_hours=list(defaults["active_hours"]),  # type: ignore[arg-type]
            sentiment_bias=sentiment,
            influence_weight=float(defaults["influence_weight"]),  # type: ignore[arg-type]
            stance=_sentiment_to_stance(sentiment),
        )
