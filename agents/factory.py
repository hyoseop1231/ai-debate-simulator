"""Agent factory: creates ForumAgents from opinion cluster profiles."""

from __future__ import annotations

import logging
import random
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from agents.base import BaseLLMAgent
from models.schemas import ClusterProfile, ForumAgentConfig, ForumPost

logger = logging.getLogger(__name__)


class PersonaFactory:
    """Creates debate agents from opinion cluster profiles.

    Each cluster gets one representative agent with a persona
    built from the cluster's key arguments and evidence.
    """

    def __init__(
        self,
        default_model: str = "qwen2.5-coder:32b",
        api_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
    ) -> None:
        self.default_model = default_model
        self.api_url = api_url
        self.api_key = api_key

    async def create_agents(
        self,
        clusters: List[ClusterProfile],
        use_llm_persona: bool = True,
    ) -> List[ForumAgent]:
        """Create one ForumAgent per cluster."""
        agents: list[ForumAgent] = []
        for cluster in clusters:
            if use_llm_persona:
                persona = await self._generate_persona_llm(cluster)
            else:
                persona = self._generate_persona_rule(cluster)

            # Clamp temperature: sentiment range is -1..1, so 0.7 + sentiment*0.1
            # yields 0.6..0.8 which stays in valid range.
            temperature = max(0.0, min(2.0, 0.7 + (cluster.sentiment * 0.1)))

            agent = ForumAgent(
                config=ForumAgentConfig(
                    agent_id=f"agent-{cluster.cluster_id}-{cluster.label}",
                    cluster_id=cluster.cluster_id,
                    label=cluster.label,
                    weight=cluster.weight,
                    persona_prompt=persona,
                    key_arguments=cluster.key_arguments,
                    model=self.default_model,
                    temperature=temperature,
                    activity_level=self._determine_activity(cluster),
                    active_hours=list(range(9, 22)),
                    influence_weight=cluster.weight * 2,
                ),
                api_url=self.api_url,
                api_key=self.api_key,
            )
            agents.append(agent)
            logger.info(
                "Created agent: %s (weight=%.2f)",
                agent.config.agent_id,
                cluster.weight,
            )

        return agents

    async def _generate_persona_llm(self, cluster: ClusterProfile) -> str:
        """Generate persona using LLM (1 call per cluster)."""
        helper = BaseLLMAgent(
            model=self.default_model,
            temperature=0.5,
            api_url=self.api_url,
            api_key=self.api_key,
        )

        arguments_text = "\n".join(
            f"- {arg}" for arg in cluster.key_arguments
        )
        keywords_text = ", ".join(cluster.keywords) if cluster.keywords else "N/A"

        sentiment_desc = "중립적"
        if cluster.sentiment > 0.3:
            sentiment_desc = "긍정적/찬성"
        elif cluster.sentiment < -0.3:
            sentiment_desc = "부정적/반대"

        prompt = (
            f"다음 여론 클러스터를 대표하는 토론 참가자의 페르소나를 생성하세요.\n\n"
            f"클러스터 라벨: {cluster.label}\n"
            f"전체 여론 비중: {cluster.weight * 100:.1f}%\n"
            f"감성 성향: {sentiment_desc} (점수: {cluster.sentiment:.2f})\n"
            f"핵심 키워드: {keywords_text}\n"
            f"핵심 논점:\n{arguments_text}\n\n"
            f"요구사항:\n"
            f"- 이 클러스터의 입장을 충실히 대변하는 캐릭터를 만드세요.\n"
            f"- 핵심 논점에 기반하여 주장하되, 근거 자료를 벗어나지 마세요.\n"
            f"- 3인칭이 아닌, '당신은 ~입니다' 형태의 시스템 프롬프트로 작성하세요.\n"
            f"- 토론 스타일, 말투, 가치관을 구체적으로 서술하세요.\n"
            f"- 5~8문장으로 작성하세요."
        )

        result = await helper._call_llm(
            prompt,
            system_prompt=(
                "당신은 토론 시뮬레이션을 위한 페르소나 설계 전문가입니다. "
                "주어진 여론 클러스터 데이터를 바탕으로 토론 참가자의 "
                "성격과 논증 스타일을 설계합니다."
            ),
            max_tokens=500,
        )

        content = result.get("content", "")
        if content and not content.startswith("["):
            return content

        # Fallback to rule-based if LLM fails
        logger.warning(
            "LLM persona generation failed for cluster %s, using rule-based fallback",
            cluster.cluster_id,
        )
        return self._generate_persona_rule(cluster)

    def _generate_persona_rule(self, cluster: ClusterProfile) -> str:
        """Rule-based persona generation (no LLM, fallback)."""
        arguments_text = "\n".join(
            f"  - {arg}" for arg in cluster.key_arguments
        )

        return (
            f"당신은 '{cluster.label}' 입장을 대표하는 토론 참가자입니다.\n"
            f"핵심 입장:\n{arguments_text}\n"
            f"전체 여론에서 당신의 입장 비중: {cluster.weight * 100:.1f}%\n"
            f"토론 규칙:\n"
            f"  - 핵심 논점에 기반하여 주장하세요.\n"
            f"  - 근거 자료를 벗어나지 마세요.\n"
            f"  - 상대의 주장에 논리적으로 반박하세요.\n"
            f"  - 3~5문장으로 간결하되 설득력 있게 말하세요."
        )

    def _determine_activity(self, cluster: ClusterProfile) -> float:
        """Determine activity level from cluster characteristics.

        Larger clusters are slightly more active. Returns 0.5 ~ 0.9.
        """
        # weight is 0.0~1.0; map to 0.5~0.9 linearly
        return 0.5 + (cluster.weight * 0.4)


class ForumAgent(BaseLLMAgent):
    """A debate agent created from an opinion cluster.

    Extends BaseLLMAgent with cluster-specific behavior:
    - Persona based on cluster key arguments
    - Fallback uses cluster evidence (not generic templates)
    - Activity level from MiroFish pattern
    """

    def __init__(
        self,
        config: ForumAgentConfig,
        api_url: str,
        api_key: str,
    ) -> None:
        super().__init__(
            model=config.model,
            temperature=config.temperature,
            api_url=api_url,
            api_key=api_key,
        )
        self.config = config

    async def generate_response(
        self,
        topic: str,
        context: str,
        round_number: int,
        host_summary: Optional[str] = None,
        stream_callback=None,
    ) -> ForumPost:
        """Generate a debate response.

        If host_summary is provided (from ForumReader), inject it
        into the prompt as "### Forum Host Latest Summary".
        """
        prompt = self._build_prompt(topic, context, round_number, host_summary)

        result = await self._call_llm(
            prompt,
            stream_callback,
            system_prompt=self.config.persona_prompt,
            max_tokens=800,
        )

        content = result.get("content", "")
        if not content or content.startswith("["):
            content = self._generate_fallback()

        return ForumPost(
            post_id=f"post-{uuid.uuid4().hex[:8]}",
            agent_id=self.config.agent_id,
            round=round_number,
            timestamp=datetime.now(timezone.utc),
            content=content,
            reply_to=None,
            evidence_refs=result.get("evidence", []),
            stance_shift=None,
            cluster_id=self.config.cluster_id,
            influence_weight=self.config.influence_weight,
        )

    def _build_prompt(
        self,
        topic: str,
        context: str,
        round_number: int,
        host_summary: Optional[str] = None,
    ) -> str:
        """Build the full prompt for the agent."""
        parts = [
            f"## 토론 주제\n{topic}\n",
            f"## 현재 라운드\n{round_number}라운드\n",
        ]

        if context:
            parts.append(f"## 최근 토론 내용\n{context}\n")

        if host_summary:
            parts.append(f"### Forum Host Latest Summary\n{host_summary}\n")

        arguments_text = "\n".join(
            f"- {arg}" for arg in self.config.key_arguments
        )
        parts.append(f"## 당신의 핵심 논점\n{arguments_text}\n")

        parts.append(
            "## 응답 지침\n"
            "- 위 핵심 논점에 기반하여 주장하세요.\n"
            "- 이전 발언에 구체적으로 반응하면서 시작하세요.\n"
            "- 3~5문장으로 간결하되 설득력 있게 작성하세요.\n"
            "- 근거를 제시하며 논리적으로 주장하세요.\n\n"
            "당신의 발언을 작성하세요:"
        )

        return "\n".join(parts)

    def _generate_fallback(self) -> str:
        """Fallback using cluster key_arguments (not generic templates)."""
        if not self.config.key_arguments:
            return (
                f"'{self.config.label}' 입장에서 볼 때, "
                "이 주제에 대해 더 깊은 논의가 필요합니다."
            )

        chosen_arg = random.choice(self.config.key_arguments)
        return (
            f"'{self.config.label}' 입장에서 강조하고 싶은 점은 다음과 같습니다. "
            f"{chosen_arg} "
            f"이 논점은 전체 여론의 {self.config.weight * 100:.0f}%가 "
            f"공감하는 핵심 주장입니다."
        )
