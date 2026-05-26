"""Full pipeline orchestrator: Forum → Swarm → Prediction.

Connects ForumEngine (LLM debate), DebateSimulation (rule-based swarm),
and ClusterWeightedPredictor (scoring) into a single async pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from models.schemas import ClusterProfile, ForumPost, PredictionResult

logger = logging.getLogger(__name__)


def extract_debate_scores(
    forum_result: Dict[str, Any],
) -> Dict[int, float]:
    """Extract per-cluster debate scores from forum result dict.

    Analyzes agent_summaries to estimate how well each cluster performed.
    Uses post count and influence weight as proxy for debate effectiveness.
    """
    scores: Dict[int, float] = {}

    agent_summaries: List[Dict[str, Any]] = forum_result.get("agent_summaries", [])
    if not agent_summaries:
        return scores

    # Collect per-cluster post count and influence
    cluster_posts: Dict[int, int] = {}
    cluster_influence: Dict[int, float] = {}

    for summary in agent_summaries:
        cid = summary.get("cluster_id")
        if cid is None:
            continue
        post_count = summary.get("post_count", 0)
        influence = summary.get("influence_weight", 1.0) * post_count

        cluster_posts[cid] = cluster_posts.get(cid, 0) + post_count
        cluster_influence[cid] = cluster_influence.get(cid, 0.0) + influence

    if not cluster_posts:
        return scores

    max_posts = max(cluster_posts.values()) if cluster_posts else 1
    max_influence = max(cluster_influence.values()) if cluster_influence else 1.0

    for cid in cluster_posts:
        post_score = cluster_posts[cid] / max(max_posts, 1)
        influence_score = cluster_influence.get(cid, 0.0) / max(max_influence, 1e-9)
        scores[cid] = 0.5 * post_score + 0.5 * influence_score

    return scores


def merge_results(
    forum_result: Dict[str, Any],
    swarm_prediction: Optional[PredictionResult],
    predictor_result: Optional[PredictionResult] = None,
) -> Dict[str, Any]:
    """Merge forum debate result with swarm/predictor predictions.

    Priority: predictor_result (if available) > swarm_prediction > forum only.
    """
    # Pick the best available prediction
    prediction = predictor_result or swarm_prediction

    if prediction is None:
        return forum_result

    forum_result["prediction"] = {
        "topic": prediction.topic,
        "dominant_opinion": prediction.dominant_opinion,
        "confidence": prediction.confidence,
        "consensus_level": prediction.consensus_level,
        "cluster_predictions": [
            {
                "cluster_label": cp.cluster_label,
                "weight": cp.weight,
                "debate_score": cp.debate_score,
                "weighted_score": cp.weighted_score,
                "stance_shift": cp.stance_shift,
                "key_arguments_survived": cp.key_arguments_survived,
            }
            for cp in prediction.cluster_predictions
        ],
    }

    forum_result["dominant_opinion"] = prediction.dominant_opinion
    forum_result["confidence"] = prediction.confidence
    forum_result["consensus_level"] = prediction.consensus_level

    return forum_result


async def run_full_pipeline(
    topic: str,
    clusters: List[ClusterProfile],
    forum_engine: "ForumEngine",  # noqa: F821
    agent_count: int = 100,
    num_steps: int = 20,
    enable_predictor: bool = True,
) -> Dict[str, Any]:
    """Run the full pipeline: Forum → Swarm → Prediction.

    Steps:
      1. ForumEngine.run() — LLM-based multi-agent debate
      2. extract debate_scores from forum result
      3. DebateSimulation.run() — rule-based swarm simulation
      4. ClusterWeightedPredictor.predict() — final scoring (optional)
      5. Merge everything into a single result dict

    Args:
        topic: Debate topic (used by swarm; forum reads from its config).
        clusters: ClusterProfile list shared across all stages.
        forum_engine: Pre-configured ForumEngine instance.
        agent_count: Number of rule-based swarm agents.
        num_steps: Swarm simulation steps.
        enable_predictor: Also run ClusterWeightedPredictor for refined scoring.

    Returns:
        Merged result dict with forum posts + swarm prediction.
    """
    # ── Step 1: Forum debate ──────────────────────────────────────────
    forum_result = await forum_engine.run()
    logger.info(
        "Forum completed: %d posts, %d rounds",
        forum_result.get("total_posts", 0),
        forum_result.get("total_rounds", 0),
    )

    # ── Step 2: Extract debate scores ─────────────────────────────────
    debate_scores = extract_debate_scores(forum_result)
    logger.info("Debate scores extracted: %s", debate_scores)

    # ── Step 3: Swarm simulation ──────────────────────────────────────
    swarm_prediction: Optional[PredictionResult] = None
    try:
        from swarm.engine import DebateSimulation

        sim = DebateSimulation(clusters=clusters, agent_count=agent_count)
        swarm_prediction = await sim.run(
            topic=topic,
            num_steps=num_steps,
            debate_scores=debate_scores,
        )
        logger.info(
            "Swarm completed: dominant=%s confidence=%.2f",
            swarm_prediction.dominant_opinion,
            swarm_prediction.confidence,
        )
    except Exception:
        logger.warning("Swarm simulation failed, continuing without it", exc_info=True)

    # ── Step 4: ClusterWeightedPredictor (optional) ───────────────────
    predictor_result: Optional[PredictionResult] = None
    if enable_predictor:
        try:
            from evaluation.predictor import ClusterWeightedPredictor

            posts = [
                ForumPost(**p) if isinstance(p, dict) else p
                for p in forum_result.get("posts", [])
            ]
            predictor = ClusterWeightedPredictor()

            # If swarm produced a prediction, pass its cluster_predictions
            # as a simulation_result dict that _integrate_simulation expects.
            sim_dict: Optional[Dict[str, Any]] = None
            if swarm_prediction is not None:
                votes: Dict[str, float] = {}
                total_votes = 0
                for cp in swarm_prediction.cluster_predictions:
                    votes[cp.cluster_label] = cp.weighted_score
                    total_votes += 1
                sim_dict = {"votes": votes, "total_votes": total_votes}

            predictor_result = predictor.predict(
                clusters=clusters,
                debate_scores=debate_scores,
                posts=posts,
                simulation_result=sim_dict,
            )
            logger.info(
                "Predictor completed: dominant=%s confidence=%.2f",
                predictor_result.dominant_opinion,
                predictor_result.confidence,
            )
        except Exception:
            logger.warning("Predictor failed, using swarm result only", exc_info=True)

    # ── Step 5: Merge ─────────────────────────────────────────────────
    final = merge_results(forum_result, swarm_prediction, predictor_result)
    final["pipeline"] = "full"
    return final
