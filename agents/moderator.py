"""Forum moderator (ForumHost) -- BettaFish ForumHost pattern."""

from __future__ import annotations

import logging
from typing import List

from agents.base import BaseLLMAgent
from models.schemas import ForumPost, LogEntry

logger = logging.getLogger(__name__)


class ForumHost(BaseLLMAgent):
    """Forum moderator -- BettaFish ForumHost pattern.

    CRITICAL: Must use a DIFFERENT model from debate agents
    to prevent opinion homogenization.

    Responsibilities:
    1. Timeline analysis -- extract key events from agent speeches
    2. Error correction -- cross-reference for factual errors
    3. Viewpoint synthesis -- find consensus and divergence
    4. Trend prediction -- forecast opinion development
    5. Discussion guidance -- pose 2-3 questions for deeper investigation
    """

    def __init__(
        self,
        model: str,
        debate_agent_model: str,
        api_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        speech_trigger: int = 5,
    ) -> None:
        # Validate model separation
        if model == debate_agent_model:
            logger.warning(
                "ForumHost model (%s) is same as agent model. "
                "Anti-homogenization requires different models!",
                model,
            )

        super().__init__(
            model=model,
            temperature=0.3,  # Low temperature for stable summaries
            api_url=api_url,
            api_key=api_key,
        )
        self.debate_agent_model = debate_agent_model
        self.speech_trigger = speech_trigger
        self.speeches_since_last = 0

    def should_intervene(self) -> bool:
        """Check if moderator should intervene (every N speeches)."""
        return self.speeches_since_last >= self.speech_trigger

    def record_speech(self) -> None:
        """Record that an agent has spoken."""
        self.speeches_since_last += 1

    async def generate_moderation(
        self,
        recent_entries: List[LogEntry],
        topic: str,
    ) -> str:
        """Generate moderator response based on recent agent speeches.

        Output format (BettaFish pattern, ~1000 chars max):
        1. Timeline summary
        2. Error/contradiction detection
        3. Viewpoint synthesis
        4. 2-3 guiding questions
        """
        self.speeches_since_last = 0  # Reset counter

        prompt = self._build_moderation_prompt(recent_entries, topic)

        result = await self._call_llm(
            prompt,
            system_prompt=(
                "당신은 중립적이고 공정한 토론 사회자입니다. "
                "어떤 입장도 편들지 않으며, 토론의 질을 높이는 데 집중합니다. "
                "사실 오류와 논리적 모순을 지적하고, 건설적 방향을 제시합니다. "
                "반드시 1000자 이내로 작성하세요."
            ),
            max_tokens=600,
        )

        content = result.get("content", "")
        if not content or content.startswith("["):
            content = self._generate_moderation_fallback(recent_entries, topic)

        return content

    def _build_moderation_prompt(
        self,
        recent_entries: List[LogEntry],
        topic: str,
    ) -> str:
        """Build the moderator's prompt."""
        entries_text = self._format_entries(recent_entries)

        return (
            f"## 토론 주제\n{topic}\n\n"
            f"## 최근 에이전트 발언 ({len(recent_entries)}개)\n"
            f"{entries_text}\n\n"
            "## 사회자 역할 지침\n"
            "다음 4개 섹션으로 구성된 중재 발언을 작성하세요:\n\n"
            "### 1. 타임라인 정리\n"
            "최근 발언에서 핵심 사건과 논점을 시간순으로 정리하세요.\n\n"
            "### 2. 오류/모순 지적\n"
            "사실 오류, 논리적 모순, 또는 근거 없는 주장이 있으면 지적하세요. "
            "없다면 '현재까지 명확한 오류는 발견되지 않았습니다'로 표기하세요.\n\n"
            "### 3. 관점 종합\n"
            "각 입장의 핵심 주장을 요약하고, 합의점과 쟁점을 정리하세요.\n\n"
            "### 4. 심화 질문\n"
            "토론을 더 깊이 있게 만들 2~3개의 질문을 제시하세요.\n\n"
            "1000자 이내로 간결하게 작성하세요.\n\n"
            "사회자 발언을 작성하세요:"
        )

    def _format_entries(self, entries: List[LogEntry]) -> str:
        """Format log entries for the moderator prompt."""
        if not entries:
            return "아직 발언이 없습니다."

        formatted_parts: list[str] = []
        for i, entry in enumerate(entries, 1):
            round_info = (
                f" (라운드 {entry.round_number})"
                if entry.round_number is not None
                else ""
            )
            content_preview = entry.content
            if len(content_preview) > 300:
                content_preview = content_preview[:297] + "..."
            formatted_parts.append(
                f"[{i}] {entry.source}{round_info}: {content_preview}"
            )

        return "\n".join(formatted_parts)

    def _generate_moderation_fallback(
        self,
        recent_entries: List[LogEntry],
        topic: str,
    ) -> str:
        """Fallback moderation when LLM call fails."""
        sources = list({entry.source for entry in recent_entries})
        sources_text = ", ".join(sources) if sources else "참가자들"
        entry_count = len(recent_entries)

        return (
            f"### 사회자 정리\n\n"
            f"**타임라인**: 최근 {entry_count}개의 발언이 있었습니다. "
            f"발언자: {sources_text}.\n\n"
            f"**관점 종합**: '{topic}'에 대해 다양한 관점이 제시되었습니다. "
            f"각 입장의 핵심 논점을 더 구체적으로 뒷받침해 주시기 바랍니다.\n\n"
            f"**심화 질문**:\n"
            f"1. 현재 제시된 근거 중 가장 설득력 있는 것은 무엇인가요?\n"
            f"2. 상대 입장의 주장에서 동의할 수 있는 부분이 있나요?"
        )

    def validate_model_separation(self) -> bool:
        """Runtime validation that moderator uses different model."""
        is_separated = self.model != self.debate_agent_model
        if not is_separated:
            logger.warning(
                "Model separation violation: ForumHost (%s) == agent model (%s). "
                "This risks opinion homogenization.",
                self.model,
                self.debate_agent_model,
            )
        return is_separated
