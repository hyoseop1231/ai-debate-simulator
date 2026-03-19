"""Tests for swarm -- RuleAgent, AgentGraph, DebateSimulation, SimulationTrace."""

from __future__ import annotations

import time
from typing import Dict, List

import pytest

from models.schemas import ClusterProfile
from swarm.agent_graph import AgentGraph
from swarm.engine import DebateSimulation
from swarm.rule_agent import ENTITY_TYPE_DEFAULTS, RuleAgent, _sentiment_to_stance
from swarm.trace import SimulationTrace


@pytest.fixture
def two_clusters() -> List[ClusterProfile]:
    return [
        ClusterProfile(
            cluster_id=0,
            label="pro",
            weight=0.6,
            document_count=6,
            key_arguments=["Pro argument"],
            sentiment=0.5,
        ),
        ClusterProfile(
            cluster_id=1,
            label="con",
            weight=0.4,
            document_count=4,
            key_arguments=["Con argument"],
            sentiment=-0.5,
        ),
    ]


class TestRuleAgentVote:
    """test_rule_agent_vote: returns valid vote strings."""

    def test_vote_returns_valid_string(self) -> None:
        agent = RuleAgent(
            agent_id="test-0",
            cluster_id=0,
            entity_type="General",
            activity_level=1.0,
            active_hours=list(range(24)),
            sentiment_bias=0.5,
            influence_weight=1.0,
            stance="support",
        )
        neighbor_influence = {"support": 0.5, "oppose": 0.3, "neutral": 0.2}
        vote = agent.act(neighbor_influence)
        assert vote in {"support", "oppose", "neutral", "abstain"}

    def test_strong_positive_bias_votes_support(self) -> None:
        agent = RuleAgent(
            agent_id="test-1",
            cluster_id=0,
            entity_type="Expert",
            activity_level=1.0,
            active_hours=list(range(24)),
            sentiment_bias=0.9,
            influence_weight=1.0,
            stance="support",
        )
        # Run multiple times to account for randomness
        votes = [agent.act({"support": 0.8, "oppose": 0.1, "neutral": 0.1}) for _ in range(20)]
        support_count = votes.count("support")
        # With strong bias, most votes should be support
        assert support_count >= 10

    def test_strong_negative_bias_votes_oppose(self) -> None:
        agent = RuleAgent(
            agent_id="test-2",
            cluster_id=1,
            entity_type="Expert",
            activity_level=1.0,
            active_hours=list(range(24)),
            sentiment_bias=-0.9,
            influence_weight=1.0,
            stance="oppose",
        )
        votes = [agent.act({"support": 0.1, "oppose": 0.8, "neutral": 0.1}) for _ in range(20)]
        oppose_count = votes.count("oppose")
        assert oppose_count >= 10

    def test_create_for_cluster(self, two_clusters: List[ClusterProfile]) -> None:
        agent = RuleAgent.create_for_cluster(two_clusters[0], agent_idx=0, entity_type="General")
        assert agent.cluster_id == 0
        assert agent.agent_id == "c0_a0"
        assert agent.entity_type == "General"


class TestSentimentToStance:
    """Test _sentiment_to_stance helper."""

    def test_positive(self) -> None:
        assert _sentiment_to_stance(0.5) == "support"

    def test_negative(self) -> None:
        assert _sentiment_to_stance(-0.5) == "oppose"

    def test_neutral(self) -> None:
        assert _sentiment_to_stance(0.0) == "neutral"

    def test_boundary(self) -> None:
        assert _sentiment_to_stance(0.3) == "neutral"
        assert _sentiment_to_stance(-0.3) == "neutral"
        assert _sentiment_to_stance(0.31) == "support"
        assert _sentiment_to_stance(-0.31) == "oppose"


class TestAgentGraphProportional:
    """test_agent_graph_proportional: cluster weights -> proportional agents."""

    def test_proportional_creation(self, two_clusters: List[ClusterProfile]) -> None:
        graph = AgentGraph()
        graph.create_from_clusters(two_clusters, scale=100)

        assert len(graph.agents) == 100

        cluster_0_count = sum(1 for a in graph.agents if a.cluster_id == 0)
        cluster_1_count = sum(1 for a in graph.agents if a.cluster_id == 1)

        # pro has weight 0.6, con has weight 0.4
        assert cluster_0_count > cluster_1_count
        # Approximate proportionality
        assert abs(cluster_0_count - 60) <= 5
        assert abs(cluster_1_count - 40) <= 5

    def test_empty_clusters(self) -> None:
        graph = AgentGraph()
        graph.create_from_clusters([], scale=100)
        assert len(graph.agents) == 0

    def test_single_cluster(self) -> None:
        clusters = [
            ClusterProfile(
                cluster_id=0, label="only", weight=1.0, document_count=10
            ),
        ]
        graph = AgentGraph()
        graph.create_from_clusters(clusters, scale=50)
        assert len(graph.agents) == 50
        assert all(a.cluster_id == 0 for a in graph.agents)

    def test_agents_have_neighbors(self, two_clusters: List[ClusterProfile]) -> None:
        graph = AgentGraph()
        graph.create_from_clusters(two_clusters, scale=20)

        # Most agents should have at least 1 neighbor
        agents_with_neighbors = sum(1 for a in graph.agents if len(a.neighbors) > 0)
        assert agents_with_neighbors >= len(graph.agents) * 0.8

    def test_get_returns_agent(self, two_clusters: List[ClusterProfile]) -> None:
        graph = AgentGraph()
        graph.create_from_clusters(two_clusters, scale=10)
        first_id = graph.agents[0].agent_id
        assert graph.get(first_id) is graph.agents[0]
        assert graph.get("nonexistent") is None

    def test_get_neighbors_returns_agents(
        self, two_clusters: List[ClusterProfile]
    ) -> None:
        graph = AgentGraph()
        graph.create_from_clusters(two_clusters, scale=20)
        agent = graph.agents[0]
        neighbors = graph.get_neighbors(agent.agent_id)
        assert all(isinstance(n, RuleAgent) for n in neighbors)


class TestSimulationRun:
    """test_simulation_run: completes without error."""

    @pytest.mark.asyncio
    async def test_simulation_completes(
        self, two_clusters: List[ClusterProfile]
    ) -> None:
        sim = DebateSimulation(clusters=two_clusters, agent_count=20)
        result = await sim.run(topic="Test topic", num_steps=5)

        assert result.topic == "Test topic"
        assert result.dominant_opinion in {"pro", "con"}
        assert 0.0 <= result.confidence <= 1.0
        assert len(result.cluster_predictions) == 2

    @pytest.mark.asyncio
    async def test_simulation_step_returns_dict(
        self, two_clusters: List[ClusterProfile]
    ) -> None:
        sim = DebateSimulation(clusters=two_clusters, agent_count=10)
        sim.topic = "Test"
        sim.current_step = 1
        step_result = await sim.step()
        assert "step" in step_result
        assert "active" in step_result
        assert "results" in step_result


class TestSimulationFast:
    """test_simulation_fast: 100 agents 20 steps < 1 second."""

    @pytest.mark.asyncio
    async def test_performance(self, two_clusters: List[ClusterProfile]) -> None:
        sim = DebateSimulation(clusters=two_clusters, agent_count=100)
        start = time.monotonic()
        await sim.run(topic="Performance test", num_steps=20)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"Simulation took {elapsed:.2f}s, expected < 1.0s"


class TestTraceSqlite:
    """test_trace_sqlite: records to database."""

    def test_log_step_and_query(self) -> None:
        trace = SimulationTrace()  # in-memory DB

        results = [
            {"agent_id": "a0", "cluster_id": 0, "vote": "support", "influence": 1.0},
            {"agent_id": "a1", "cluster_id": 0, "vote": "oppose", "influence": 0.8},
            {"agent_id": "a2", "cluster_id": 1, "vote": "support", "influence": 1.2},
        ]
        trace.log_step(1, results)

        dist = trace.get_vote_distribution()
        assert 0 in dist
        assert 1 in dist
        assert dist[0]["support"] == 1
        assert dist[0]["oppose"] == 1
        assert dist[1]["support"] == 1

    def test_final_distribution_normalized(self) -> None:
        trace = SimulationTrace()
        results = [
            {"agent_id": "a0", "cluster_id": 0, "vote": "support", "influence": 1.0},
            {"agent_id": "a1", "cluster_id": 0, "vote": "support", "influence": 1.0},
            {"agent_id": "a2", "cluster_id": 0, "vote": "oppose", "influence": 1.0},
        ]
        trace.log_step(1, results)

        final = trace.get_final_distribution()
        # 2 support, 1 oppose out of 3 non-abstain
        assert final[0]["support"] == pytest.approx(2 / 3, abs=0.01)
        assert final[0]["oppose"] == pytest.approx(1 / 3, abs=0.01)

    def test_timeline(self) -> None:
        trace = SimulationTrace()
        trace.log_step(1, [
            {"agent_id": "a0", "cluster_id": 0, "vote": "support", "influence": 1.0},
        ])
        trace.log_step(2, [
            {"agent_id": "a0", "cluster_id": 0, "vote": "oppose", "influence": 1.0},
        ])
        timeline = trace.get_timeline()
        assert len(timeline) == 2
        assert timeline[0]["step"] == 1
        assert timeline[1]["step"] == 2

    def test_empty_results(self) -> None:
        trace = SimulationTrace()
        trace.log_step(1, [])
        dist = trace.get_vote_distribution()
        assert dist == {}

    def test_close(self) -> None:
        trace = SimulationTrace()
        trace.close()
        assert trace._conn is None
        # Double close should not raise
        trace.close()
