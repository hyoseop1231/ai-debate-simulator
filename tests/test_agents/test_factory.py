"""Tests for agents.factory -- PersonaFactory and ForumAgent."""

from __future__ import annotations

import re
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.factory import ForumAgent, PersonaFactory
from models.schemas import ClusterProfile, ForumAgentConfig


class TestCreateAgentsRuleBased:
    """test_create_agents_rule_based: creates agents without LLM."""

    @pytest.mark.asyncio
    async def test_create_agents_rule_based(
        self, sample_clusters: List[ClusterProfile]
    ) -> None:
        factory = PersonaFactory(default_model="test-model")
        agents = await factory.create_agents(sample_clusters, use_llm_persona=False)

        assert len(agents) == len(sample_clusters)
        for agent in agents:
            assert isinstance(agent, ForumAgent)
            assert agent.config.model == "test-model"
            assert agent.config.persona_prompt  # non-empty

    @pytest.mark.asyncio
    async def test_persona_prompt_is_rule_based(
        self, sample_clusters: List[ClusterProfile]
    ) -> None:
        factory = PersonaFactory()
        agents = await factory.create_agents(sample_clusters, use_llm_persona=False)

        for agent in agents:
            # Rule-based personas contain the cluster label
            assert agent.config.label in agent.config.persona_prompt


class TestAgentIdSafe:
    """test_agent_id_safe: no filesystem-unsafe characters."""

    @pytest.mark.asyncio
    async def test_agent_id_safe(self, sample_clusters: List[ClusterProfile]) -> None:
        factory = PersonaFactory()
        agents = await factory.create_agents(sample_clusters, use_llm_persona=False)

        unsafe_pattern = re.compile(r'[/\\<>:"\'\|?\*\s]')
        for agent in agents:
            assert not unsafe_pattern.search(agent.config.agent_id), (
                f"Agent ID '{agent.config.agent_id}' contains unsafe characters"
            )

    def test_safe_agent_id_with_special_chars(self) -> None:
        cluster = ClusterProfile(
            cluster_id=0,
            label="test/label with spaces & <special>",
            weight=0.5,
            document_count=1,
        )
        safe_id = PersonaFactory._safe_agent_id(cluster)
        unsafe_pattern = re.compile(r'[/\\<>:"\'\|?\*]')
        assert not unsafe_pattern.search(safe_id)
        assert safe_id.startswith("agent-0-")


class TestPersonaContainsArguments:
    """test_persona_contains_arguments: persona prompt includes cluster key_arguments."""

    @pytest.mark.asyncio
    async def test_persona_contains_arguments(
        self, sample_clusters: List[ClusterProfile]
    ) -> None:
        factory = PersonaFactory()
        agents = await factory.create_agents(sample_clusters, use_llm_persona=False)

        for agent, cluster in zip(agents, sample_clusters):
            for arg in cluster.key_arguments:
                assert arg in agent.config.persona_prompt, (
                    f"Key argument '{arg[:50]}...' not found in persona prompt"
                )


class TestActivityLevelRange:
    """test_activity_level_range: 0.5~0.9."""

    @pytest.mark.asyncio
    async def test_activity_level_range(
        self, sample_clusters: List[ClusterProfile]
    ) -> None:
        factory = PersonaFactory()
        agents = await factory.create_agents(sample_clusters, use_llm_persona=False)

        for agent in agents:
            assert 0.5 <= agent.config.activity_level <= 0.9, (
                f"Activity level {agent.config.activity_level} outside 0.5~0.9"
            )

    def test_determine_activity_boundary_values(self) -> None:
        factory = PersonaFactory()

        # weight=0.0 -> activity=0.5
        cluster_min = ClusterProfile(
            cluster_id=0, label="min", weight=0.0, document_count=1
        )
        assert factory._determine_activity(cluster_min) == pytest.approx(0.5)

        # weight=1.0 -> activity=0.9
        cluster_max = ClusterProfile(
            cluster_id=1, label="max", weight=1.0, document_count=1
        )
        assert factory._determine_activity(cluster_max) == pytest.approx(0.9)


class TestForumAgentFallback:
    """Test ForumAgent._generate_fallback uses cluster arguments."""

    def test_fallback_with_arguments(self) -> None:
        config = ForumAgentConfig(
            agent_id="test-agent",
            cluster_id=0,
            label="test-cluster",
            weight=0.5,
            persona_prompt="test persona",
            key_arguments=["Important argument about AI safety"],
        )
        agent = ForumAgent(
            config=config,
            api_url="http://localhost:11434/v1",
            api_key="test",
        )
        fallback = agent._generate_fallback()
        assert "test-cluster" in fallback
        assert "50%" in fallback

    def test_fallback_without_arguments(self) -> None:
        config = ForumAgentConfig(
            agent_id="test-agent",
            cluster_id=0,
            label="empty-cluster",
            weight=0.3,
            persona_prompt="test persona",
            key_arguments=[],
        )
        agent = ForumAgent(
            config=config,
            api_url="http://localhost:11434/v1",
            api_key="test",
        )
        fallback = agent._generate_fallback()
        assert "empty-cluster" in fallback
