"""Swarm simulation engine -- rule-based agent swarm for debate opinion simulation.

No external dependencies beyond stdlib.
Runs rule-based agents (hundreds, no LLM) + optional LLM representatives (few).
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Dict, List, Optional

from models.schemas import ClusterPrediction, ClusterProfile, PredictionResult
from swarm.agent_graph import AgentGraph
from swarm.rule_agent import RuleAgent
from swarm.trace import SimulationTrace

logger = logging.getLogger(__name__)


class DebateSimulation:
    """Swarm env.step() pattern -- self-implemented for debate domain.

    No external dependencies (no camel-ai).
    Runs rule-based agents (hundreds, no LLM) + LLM representatives (few).
    """

    def __init__(
        self,
        clusters: List[ClusterProfile],
        agent_count: int = 100,
        db_path: Optional[str] = None,
    ) -> None:
        self.clusters = clusters
        self.agent_count = agent_count
        self.graph = AgentGraph()
        self.graph.create_from_clusters(clusters, scale=agent_count)
        self.trace = SimulationTrace(db_path)
        self.current_step = 0
        self.topic = ""
        # Build cluster lookup for prediction building
        self._cluster_map: Dict[int, ClusterProfile] = {
            c.cluster_id: c for c in clusters
        }

    async def run(
        self,
        topic: str,
        num_steps: int = 20,
        debate_scores: Optional[Dict[int, float]] = None,
    ) -> PredictionResult:
        """Run full simulation.

        Args:
            topic: Debate topic
            num_steps: Number of simulation steps
            debate_scores: Optional M-MAD scores per cluster_id from ForumEngine

        Returns:
            PredictionResult with weighted predictions
        """
        self.topic = topic
        self.current_step = 0

        logger.info(
            "Starting Swarm simulation: %d agents, %d steps, topic=%s",
            len(self.graph.agents),
            num_steps,
            topic,
        )

        for step in range(num_steps):
            self.current_step = step + 1
            await self.step()

        result = self._build_prediction(debate_scores)
        logger.info(
            "Simulation complete: dominant=%s, confidence=%.2f",
            result.dominant_opinion,
            result.confidence,
        )
        return result

    async def step(self) -> Dict:
        """One simulation step -- Swarm env.step() pattern.

        1. Calculate simulated hour (24h cycle)
        2. Filter eligible agents by active_hours
        3. Select by activity_level weight
        4. Each selected agent votes (rule-based)
        5. Neighbor influence propagation
        6. Log to trace
        """
        # Map steps to a 24h cycle (each step = ~1 simulated hour)
        simulated_hour = self.current_step % 24

        # Filter eligible agents by active hours
        eligible = [
            a for a in self.graph.agents if simulated_hour in a.active_hours
        ]

        # Select by activity_level (weighted random)
        active = self._select_active(eligible)

        if not active:
            self.trace.log_step(self.current_step, [])
            return {"step": self.current_step, "active": 0, "results": []}

        # Each agent votes
        results: List[Dict] = []
        for agent in active:
            neighbor_influence = self._get_neighbor_influence(agent)
            vote = agent.act(neighbor_influence)
            results.append(
                {
                    "agent_id": agent.agent_id,
                    "cluster_id": agent.cluster_id,
                    "vote": vote,
                    "influence": agent.influence_weight,
                }
            )

        # Log step
        self.trace.log_step(self.current_step, results)

        # Propagate influence to neighbors
        self._propagate_influence(results)

        # Yield control to event loop for cooperative multitasking
        await asyncio.sleep(0)

        return {"step": self.current_step, "active": len(active), "results": results}

    def _select_active(self, eligible: List[RuleAgent]) -> List[RuleAgent]:
        """Select agents by activity_level probability."""
        if not eligible:
            return []
        return [a for a in eligible if random.random() < a.activity_level]

    def _get_neighbor_influence(self, agent: RuleAgent) -> Dict[str, float]:
        """Get aggregated stance of agent's neighbors.

        Returns weighted stance distribution, considering neighbor influence_weight.
        """
        neighbors = self.graph.get_neighbors(agent.agent_id)
        if not neighbors:
            return {"support": 0.0, "oppose": 0.0, "neutral": 0.0}

        totals: Dict[str, float] = {"support": 0.0, "oppose": 0.0, "neutral": 0.0}
        total_weight = 0.0

        for neighbor in neighbors:
            stance = neighbor.stance
            if stance in totals:
                totals[stance] += neighbor.influence_weight
                total_weight += neighbor.influence_weight

        # Normalize to proportions
        if total_weight > 0:
            for key in totals:
                totals[key] /= total_weight

        return totals

    def _propagate_influence(self, results: List[Dict]) -> None:
        """Update agent sentiment based on neighbor votes and influence_weight.

        Agents with high influence_weight shift neighbors' sentiment slightly.
        """
        for r in results:
            agent = self.graph.get(r["agent_id"])
            if agent is None:
                continue
            if agent.influence_weight < 1.5:
                continue  # Only high-influence agents propagate

            vote = r["vote"]
            if vote == "abstain":
                continue

            # Map vote to sentiment shift direction
            shift_direction = {"support": 0.02, "oppose": -0.02, "neutral": 0.0}.get(
                vote, 0.0
            )
            if shift_direction == 0.0:
                continue

            # Scale by influence weight (normalized)
            shift = shift_direction * (agent.influence_weight / 3.0)

            neighbors = self.graph.get_neighbors(agent.agent_id)
            for neighbor in neighbors:
                # Agents resist influence from other clusters slightly more
                resistance = 0.7 if neighbor.cluster_id != agent.cluster_id else 1.0
                neighbor.sentiment_bias = max(
                    -1.0,
                    min(1.0, neighbor.sentiment_bias + shift * resistance),
                )

    # @MX:ANCHOR: Core prediction builder -- integrates cluster weights, debate scores, and simulation votes
    # @MX:REASON: Called by run() and potentially by external pipeline; fan_in >= 3
    def _build_prediction(
        self, debate_scores: Optional[Dict[int, float]] = None
    ) -> PredictionResult:
        """Build PredictionResult from simulation trace.

        Combines:
        - Cluster weights (from clustering)
        - Debate scores (from ForumEngine M-MAD, if provided)
        - Simulation vote distribution (from this engine)
        """
        final_dist = self.trace.get_final_distribution()
        cluster_predictions: List[ClusterPrediction] = []

        for cluster in self.clusters:
            cid = cluster.cluster_id

            # Simulation support ratio as debate score proxy
            dist = final_dist.get(cid, {"support": 0.0, "oppose": 0.0, "neutral": 0.0})
            sim_score = dist.get("support", 0.0)

            # Use debate_scores from ForumEngine if provided, otherwise simulation
            if debate_scores and cid in debate_scores:
                # Blend: 60% debate score + 40% simulation score
                blended_score = 0.6 * debate_scores[cid] + 0.4 * sim_score
            else:
                blended_score = sim_score

            # Weighted score = cluster weight * blended score
            weighted = cluster.weight * blended_score

            # Calculate stance shift from initial sentiment
            initial_sentiment = cluster.sentiment
            # Normalized shift: how much the simulation moved from initial
            final_sentiment = dist.get("support", 0.0) - dist.get("oppose", 0.0)
            stance_shift = final_sentiment - initial_sentiment

            cluster_predictions.append(
                ClusterPrediction(
                    cluster_label=cluster.label,
                    weight=cluster.weight,
                    debate_score=round(blended_score, 4),
                    weighted_score=round(weighted, 4),
                    stance_shift=round(stance_shift, 4),
                    key_arguments_survived=cluster.key_arguments[:5],
                )
            )

        # Determine dominant opinion
        if cluster_predictions:
            best = max(cluster_predictions, key=lambda cp: cp.weighted_score)
            dominant_opinion = best.cluster_label
        else:
            dominant_opinion = "unknown"

        # Confidence based on separation between top-2 clusters
        sorted_preds = sorted(
            cluster_predictions, key=lambda cp: cp.weighted_score, reverse=True
        )
        if len(sorted_preds) >= 2:
            gap = sorted_preds[0].weighted_score - sorted_preds[1].weighted_score
            total_score = sum(cp.weighted_score for cp in sorted_preds)
            confidence = min(1.0, gap / max(total_score, 0.01) + 0.5)
        elif len(sorted_preds) == 1:
            confidence = 0.8
        else:
            confidence = 0.0

        # Consensus level: 1.0 = all clusters agree, 0.0 = maximum disagreement
        if len(sorted_preds) >= 2:
            scores = [cp.weighted_score for cp in sorted_preds]
            max_score = max(scores) if scores else 0.0
            total = sum(scores) if scores else 0.0
            consensus = max_score / total if total > 0 else 0.0
        elif len(sorted_preds) == 1:
            consensus = 1.0
        else:
            consensus = 0.0

        return PredictionResult(
            topic=self.topic,
            cluster_predictions=cluster_predictions,
            dominant_opinion=dominant_opinion,
            confidence=round(confidence, 4),
            consensus_level=round(consensus, 4),
        )
