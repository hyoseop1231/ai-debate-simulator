"""Cluster-weighted prediction system for L4.

Combines M-MAD debate scores with cluster weights to produce quantitative
predictions about dominant opinion and consensus level.
"""

import logging
import math
from typing import Dict, List, Optional

from models.schemas import (
    ClusterPrediction,
    ClusterProfile,
    ForumPost,
    PredictionResult,
)

logger = logging.getLogger(__name__)


class ClusterWeightedPredictor:
    """Generates quantitative predictions from debate results + cluster weights.

    Formula::

        weighted_score_i = cluster_weight_i * debate_score_i * (1 + stance_shift_i)
        dominant_opinion = argmax(weighted_scores)
        confidence = max(weighted_score) / sum(weighted_scores)
    """

    def predict(
        self,
        clusters: List[ClusterProfile],
        debate_scores: Dict[int, float],
        posts: List[ForumPost],
        simulation_result: Optional[Dict] = None,
    ) -> PredictionResult:
        """Generate prediction from debate results.

        Args:
            clusters: Opinion clusters from L1.
            debate_scores: M-MAD scores per cluster_id from L4 evaluator.
            posts: All ForumPosts from L3.
            simulation_result: Optional swarm simulation result.

        Returns:
            PredictionResult with weighted predictions.
        """
        if not clusters:
            return PredictionResult(
                topic=self._extract_topic(posts),
                cluster_predictions=[],
                dominant_opinion="",
                confidence=0.0,
                consensus_level=0.0,
            )

        predictions: List[ClusterPrediction] = []

        for cluster in clusters:
            cluster_id = cluster.cluster_id

            # Get debate score (default 0.5 if not evaluated)
            debate_score = debate_scores.get(cluster_id, 0.5)

            # Calculate stance shift from posts
            stance_shift = self._calculate_stance_shift(cluster_id, posts)

            # Get surviving arguments
            survived = self._get_surviving_arguments(
                cluster_id, posts, debate_scores
            )

            # Weighted score formula, clamped to [0, 1]
            raw_weighted = cluster.weight * debate_score * (1.0 + stance_shift)
            weighted = min(1.0, max(0.0, raw_weighted))

            predictions.append(
                ClusterPrediction(
                    cluster_label=cluster.label,
                    weight=cluster.weight,
                    debate_score=debate_score,
                    weighted_score=weighted,
                    stance_shift=stance_shift,
                    key_arguments_survived=survived,
                )
            )

        # Integrate simulation result if available
        if simulation_result:
            predictions = self._integrate_simulation(predictions, simulation_result)

        # Sort by weighted score descending
        predictions.sort(key=lambda p: p.weighted_score, reverse=True)

        # Calculate confidence and consensus
        total = sum(p.weighted_score for p in predictions)
        confidence = (
            predictions[0].weighted_score / total if total > 0 else 0.0
        )
        consensus = self._calculate_consensus(predictions)

        return PredictionResult(
            topic=self._extract_topic(posts),
            cluster_predictions=predictions,
            dominant_opinion=predictions[0].cluster_label if predictions else "",
            confidence=min(1.0, max(0.0, confidence)),
            consensus_level=consensus,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _calculate_stance_shift(
        self, cluster_id: int, posts: List[ForumPost]
    ) -> float:
        """Calculate average stance shift for a cluster's posts.

        Positive means the cluster's position was strengthened during debate;
        negative means it was weakened.
        """
        cluster_posts = [
            p for p in posts if p.cluster_id == cluster_id and p.stance_shift is not None
        ]
        if not cluster_posts:
            return 0.0

        total_shift = sum(p.stance_shift for p in cluster_posts)  # type: ignore[arg-type]
        return total_shift / len(cluster_posts)

    def _get_surviving_arguments(
        self,
        cluster_id: int,
        posts: List[ForumPost],
        debate_scores: Dict[int, float],
    ) -> List[str]:
        """Get arguments that were not effectively rebutted.

        An argument "survives" if no reply from a higher-scoring opposing
        cluster directly countered it, or if no reply exists at all.
        """
        cluster_posts = [p for p in posts if p.cluster_id == cluster_id]
        if not cluster_posts:
            return []

        # Build a set of post_ids that received strong rebuttals
        rebutted_ids: set = set()
        own_score = debate_scores.get(cluster_id, 0.5)

        for post in posts:
            if post.cluster_id == cluster_id:
                continue  # skip same-cluster posts
            if post.reply_to is None:
                continue
            opponent_score = debate_scores.get(post.cluster_id or -1, 0.5)
            if opponent_score > own_score:
                rebutted_ids.add(post.reply_to)

        survived: List[str] = []
        for post in cluster_posts:
            if post.post_id not in rebutted_ids:
                # Truncate long content for summary
                text = post.content[:200].strip()
                if text:
                    survived.append(text)

        # Cap at 5 key surviving arguments
        return survived[:5]

    def _integrate_simulation(
        self,
        predictions: List[ClusterPrediction],
        sim_result: Dict,
    ) -> List[ClusterPrediction]:
        """Integrate swarm simulation results into predictions.

        Adjusts weighted_score based on simulation vote distribution.
        Simulation adds confidence but does not override debate scores.

        Expected sim_result format::

            {
                "votes": {"cluster_label": vote_count, ...},
                "total_votes": int,
            }
        """
        votes: Dict[str, float] = sim_result.get("votes", {})
        total_votes = sim_result.get("total_votes", 0)

        if not votes or total_votes <= 0:
            return predictions

        adjusted: List[ClusterPrediction] = []
        for pred in predictions:
            cluster_votes = votes.get(pred.cluster_label, 0)
            vote_ratio = cluster_votes / total_votes

            # Blend: 70% debate-based, 30% simulation-based
            blended = pred.weighted_score * 0.7 + vote_ratio * 0.3
            blended = min(1.0, max(0.0, blended))

            adjusted.append(
                ClusterPrediction(
                    cluster_label=pred.cluster_label,
                    weight=pred.weight,
                    debate_score=pred.debate_score,
                    weighted_score=blended,
                    stance_shift=pred.stance_shift,
                    key_arguments_survived=pred.key_arguments_survived,
                )
            )

        return adjusted

    def _calculate_consensus(
        self, predictions: List[ClusterPrediction]
    ) -> float:
        """Calculate consensus level (0=total disagreement, 1=total consensus).

        Uses normalized entropy of weighted score distribution.
        When one cluster dominates, entropy is low -> consensus is high.
        When scores are evenly distributed, entropy is high -> consensus is low.
        """
        if not predictions:
            return 0.0
        if len(predictions) == 1:
            return 1.0

        total = sum(p.weighted_score for p in predictions)
        if total == 0:
            return 0.0

        # Compute Shannon entropy of the score distribution
        entropy = 0.0
        for pred in predictions:
            p = pred.weighted_score / total
            if p > 0:
                entropy -= p * math.log2(p)

        # Maximum entropy for n categories
        max_entropy = math.log2(len(predictions))
        if max_entropy == 0:
            return 1.0

        # Normalized entropy: 0 (one dominates) to 1 (uniform)
        normalized = entropy / max_entropy

        # Invert: high entropy = low consensus
        return max(0.0, min(1.0, 1.0 - normalized))

    def _extract_topic(self, posts: List[ForumPost]) -> str:
        """Extract topic from posts context.

        Uses the content of the earliest post as a proxy for the topic.
        Falls back to empty string if no posts are available.
        """
        if not posts:
            return ""

        # Sort by round then timestamp and return first post content (truncated)
        earliest = min(posts, key=lambda p: (p.round, p.timestamp))
        # Take the first sentence or first 100 chars as topic proxy
        content = earliest.content
        first_sentence_end = content.find(".")
        if 0 < first_sentence_end < 150:
            return content[: first_sentence_end + 1].strip()
        return content[:100].strip()
