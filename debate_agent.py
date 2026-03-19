"""
토론 에이전트 구현 - GitHub 저장소들의 베스트 프랙티스 통합
"""

from typing import List, Dict, Optional, Tuple
from enum import Enum
from dataclasses import dataclass, field
import json
import logging
import asyncio
import os


class AgentRole(Enum):
    """Agent4Debate의 역할 기반 접근법"""

    SEARCHER = "searcher"  # 정보 검색 담당
    ANALYZER = "analyzer"  # 논증 분석 담당
    WRITER = "writer"  # 논증 생성 담당
    REVIEWER = "reviewer"  # 품질 검토 담당
    DEVIL = "devil"  # MAD의 반대 입장
    ANGEL = "angel"  # MAD의 지지 입장
    ORGANIZER = "organizer"  # 토론 진행자 (새로 추가)


class DebateStance(Enum):
    """토론 입장"""

    SUPPORT = "support"
    OPPOSE = "oppose"
    NEUTRAL = "neutral"


@dataclass
class Argument:
    """논증 데이터 구조 (KITECH 방식 품질 점수 추가)"""

    content: str
    agent_name: str
    stance: DebateStance
    round_number: int
    evidence: List[str] = field(default_factory=list)
    confidence_score: float = 0.0
    quality_score: float = 0.7  # KITECH 방식 품질 점수


# Available Models (OpenRouter + Bigboy Ollama)
OPENROUTER_MODELS = {
    # Bigboy Ollama Local Models
    "qwen2.5-coder:32b": {"name": "Qwen2.5 Coder 32B", "provider": "Bigboy/Ollama", "context": 32768, "size": "19.8GB"},
    "gpt-oss:20b": {"name": "GPT-OSS 20B", "provider": "Bigboy/Ollama", "context": 32768, "size": "13.8GB"},
    "glm-4.7-flash:latest": {"name": "GLM 4.7 Flash", "provider": "Bigboy/Ollama", "context": 32768, "size": "19GB"},
    "qwen2.5:7b": {"name": "Qwen2.5 7B", "provider": "Bigboy/Ollama", "context": 32768, "size": "4.7GB"},
    "qwen2.5vl:7b": {"name": "Qwen2.5 VL 7B", "provider": "Bigboy/Ollama", "context": 32768, "size": "6GB"},
    "qwen2.5:1.5b": {"name": "Qwen2.5 1.5B", "provider": "Bigboy/Ollama", "context": 32768, "size": "986MB"},
    "qwen3-vl:2b": {"name": "Qwen3 VL 2B", "provider": "Bigboy/Ollama", "context": 32768, "size": "1.9GB"},
    "gpt-oss:120b": {"name": "GPT-OSS 120B", "provider": "Bigboy/Ollama", "context": 32768, "size": "65GB"},

    # OpenRouter Cloud Models (API Key required)
    "openai/gpt-4.1": {"name": "GPT-4.1", "provider": "OpenAI", "context": 128000},
    "openai/o3": {"name": "OpenAI o3", "provider": "OpenAI", "context": 200000},
    "anthropic/claude-sonnet-4": {
        "name": "Claude Sonnet 4",
        "provider": "Anthropic",
        "context": 200000,
    },
    "anthropic/claude-3.5-sonnet": {
        "name": "Claude 3.5 Sonnet",
        "provider": "Anthropic",
        "context": 200000,
    },
    "google/gemini-2.5-flash-preview": {
        "name": "Gemini 2.5 Flash",
        "provider": "Google",
        "context": 1000000,
    },
    "google/gemini-2.0-flash-001": {
        "name": "Gemini 2.0 Flash",
        "provider": "Google",
        "context": 1000000,
    },
    "meta-llama/llama-3.3-70b-instruct": {
        "name": "Llama 3.3 70B",
        "provider": "Meta",
        "context": 131072,
    },
    "deepseek/deepseek-chat-v3-0324": {
        "name": "DeepSeek V3",
        "provider": "DeepSeek",
        "context": 131072,
    },
    "qwen/qwen-2.5-72b-instruct": {
        "name": "Qwen 2.5 72B",
        "provider": "Alibaba",
        "context": 131072,
    },
}

DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5-coder:32b")


class DebateAgent:
    def __init__(
        self,
        name: str,
        role: AgentRole,
        stance: DebateStance,
        model: str = DEFAULT_MODEL,
        persona_prompt: str = None,
        temperature: float = 0.7,
    ):
        self.openrouter_api_url = os.getenv(
            "OPENROUTER_API_URL", "https://openrouter.ai/api/v1"
        )
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.name = name
        self.role = role
        self.stance = stance
        self.model = model
        self.persona_prompt = persona_prompt or self._get_default_persona()
        self.temperature = temperature
        self.argument_history: List[Argument] = []
        self.logger = logging.getLogger(f"DebateAgent.{name}")

    def _get_default_persona(self) -> str:
        """역할별 기본 페르소나 프롬프트 (표현력 강화)"""
        personas = {
            AgentRole.SEARCHER: """🔍 당신은 정보 찾기를 좋아하는 사람입니다. 
            "아! 이것 봐요" "자료를 찾아보니까요" 같은 말을 자주 해요. 구체적인 사실이나 데이터로 이야기하세요.""",
            AgentRole.ANALYZER: """🧠 당신은 논리적으로 생각하는 걸 좋아해요. 
            "잠깐, 그건 좀 이상한데요?" "논리적으로 보면요" 같은 식으로 말하면서 상대방 주장의 문제점을 찾아주세요.""",
            AgentRole.WRITER: """✍️ 당신은 설득을 잘하는 사람이에요. 
            감정적으로 호소하면서도 "생각해보세요" "이게 바로 그 이유에요" 같은 말로 사람들을 설득하세요.""",
            AgentRole.REVIEWER: """📋 당신은 정리를 잘하는 사람이에요. 
            "정리해보면요" "핵심은 이거에요" 같은 말을 하면서 중요한 포인트들을 짚어주세요.""",
            AgentRole.DEVIL: """😈 당신은 반대 의견을 제시하는 걸 좋아해요. 
            "근데 말이죠" "정말 그럴까요?" 같은 말로 상대방 주장에 의문을 제기하고 반박하세요.""",
            AgentRole.ANGEL: """😇 당신은 긍정적이고 희망적인 사람이에요. 
            "맞아요!" "그 점이 정말 좋네요" 같은 말로 좋은 면을 부각시키고 지지해주세요.""",
            AgentRole.ORGANIZER: """🎯 당신은 토론을 진행하는 사람이에요. 
            "자, 정리해볼까요?" "양쪽 의견을 들어보니" 같은 말로 공정하게 진행하고 요약해주세요.""",
        }

        base_instruction = """
        
친구와 대화하듯이 자연스럽게 말하세요. 3-4문장 정도로 간단히 하되 설득력 있게 해주세요.
        """

        return (
            personas.get(self.role, "당신은 사려 깊은 토론 참가자입니다. 🤔")
            + base_instruction
        )

    async def generate_argument(
        self,
        topic: str,
        context: List[Argument],
        round_number: int,
        focus_instruction: str = None,
        stream_callback=None,
    ) -> Argument:
        """
        논증 생성 - Society of Minds의 컨텍스트 기반 접근법 적용
        스트리밍 지원 추가
        """
        # 컨텍스트에서 관련 정보 추출
        relevant_context = self._extract_relevant_context(context)

        # 역할별 특화된 프롬프트 생성
        prompt = self._build_argument_prompt(
            topic, relevant_context, round_number, focus_instruction
        )

        # Context7 연구 기반: 비동기 LLM 호출 (스트리밍 옵션)
        response = await self._call_llm(prompt, stream_callback)

        # 논증 생성 및 저장 (KITECH 방식 품질 점수 포함)
        argument = Argument(
            content=response["content"],
            agent_name=self.name,
            stance=self.stance,
            round_number=round_number,
            evidence=response.get("evidence", []),
            confidence_score=response.get("confidence", 0.7),
            quality_score=response.get("quality_score", 0.7),  # KITECH 품질 점수
        )

        # thinking 내용이 있으면 속성으로 추가
        if "thinking_content" in response:
            argument.thinking_content = response["thinking_content"]

        self.argument_history.append(argument)
        return argument

    def _extract_relevant_context(self, context: List[Argument]) -> List[Argument]:
        """관련 컨텍스트 추출 - 향상된 대화 맥락 이해"""
        if not context:
            return []

        # 1. 직전 발언자의 논증 (직접 응답을 위해)
        last_argument = context[-1] if context else None

        # 2. 현재 라운드의 모든 논증 (대화 흐름 이해)
        current_round = context[-1].round_number if context else 1
        current_round_args = [
            arg for arg in context if arg.round_number == current_round
        ]

        # 3. 이전 라운드의 핵심 논증 (논의 연속성)
        previous_round_args = []
        if current_round > 1:
            previous_round_args = [
                arg for arg in context if arg.round_number == current_round - 1
            ][-3:]

        # 4. 반대 입장의 최근 논증 (반박 대상)
        opposing_args = [
            arg
            for arg in context
            if arg.stance != self.stance and arg.stance != DebateStance.NEUTRAL
        ][-2:]

        # 5. 같은 팀의 최근 논증 (일관성 유지)
        team_args = [
            arg
            for arg in context
            if arg.stance == self.stance and arg.agent_name != self.name
        ][-2:]

        # 6. 진행자의 최근 정리 (토론 방향 이해)
        organizer_args = [arg for arg in context if arg.stance == DebateStance.NEUTRAL][
            -1:
        ]

        # 7. 높은 품질의 논증 (중요 포인트)
        high_quality_args = sorted(
            [
                arg
                for arg in context
                if hasattr(arg, "quality_score") and arg.quality_score > 0.8
            ],
            key=lambda x: x.quality_score,
            reverse=True,
        )[:2]

        # 모든 관련 논증을 시간순으로 정렬 (중복 제거)
        all_relevant = []
        seen_contents = set()

        # 우선순위: 직전 발언 > 현재 라운드 > 반대 입장 > 같은 팀 > 진행자 > 이전 라운드 > 고품질
        for arg in (
            ([last_argument] if last_argument else [])
            + current_round_args
            + opposing_args
            + team_args
            + organizer_args
            + previous_round_args
            + high_quality_args
        ):
            if arg and arg.content not in seen_contents:
                all_relevant.append(arg)
                seen_contents.add(arg.content)
                if len(all_relevant) >= 8:  # 최대 8개까지만
                    break

        return all_relevant

    def _build_argument_prompt(
        self,
        topic: str,
        context: List[Argument],
        round_number: int,
        focus_instruction: str = None,
    ) -> str:
        """역할별 특화된 프롬프트 생성 - 향상된 대화 맥락 이해"""
        # 직전 발언자 정보 추출
        last_speaker = None
        last_content = None
        if context:
            last_speaker = context[-1].agent_name
            last_content = (
                context[-1].content[:200] + "..."
                if len(context[-1].content) > 200
                else context[-1].content
            )

        # 대화 맥락 요약
        context_summary = self._summarize_context(context)

        base_prompt = f"""
{self.persona_prompt}

🎯 **토론 정보**
- 주제: {topic}
- 당신의 입장: {self.stance.value}
- 현재 라운드: {round_number}

💬 **대화 맥락**
{context_summary}

📝 **이전 발언들**
{self._format_context(context)}

🎪 **응답 가이드라인**
1. 직전 발언자({last_speaker if last_speaker else "없음"})의 주장에 직접적으로 응답하세요.
2. 대화의 흐름을 자연스럽게 이어가면서 당신의 논점을 제시하세요.
3. 같은 팀원의 주장은 지지하고 보완하세요.
4. 반대 팀의 주장은 논리적으로 반박하세요.
5. 진행자의 정리나 지시사항이 있다면 반영하세요.

"""

        # 역할별 특화 지시사항 (한국어로 개선)
        role_instructions = {
            AgentRole.SEARCHER: "🔍 구체적인 증거와 사실을 찾아 제시하세요. '연구에 따르면', '데이터를 보면' 등의 표현을 사용하세요.",
            AgentRole.ANALYZER: "🧠 상대방 논증의 논리적 구조를 분석하고 약점을 찾아내세요. '하지만', '그러나' 등으로 전환하세요.",
            AgentRole.WRITER: "✍️ 설득력 있는 논증을 명확한 논리로 구성하세요. 감정과 이성의 균형을 맞추세요.",
            AgentRole.REVIEWER: "📋 전체 논의를 검토하고 핵심을 강화하세요. '정리하자면', '핵심은' 등을 활용하세요.",
            AgentRole.DEVIL: "😈 가정과 전제에 도전하고 강력한 반박을 제시하세요. '과연 그럴까요?', '다른 관점에서' 등을 사용하세요.",
            AgentRole.ANGEL: "😇 긍정적 측면을 지지하고 강화하세요. '더 나아가', '이것이 바로' 등의 표현을 활용하세요.",
            AgentRole.ORGANIZER: "🎯 양측의 논점을 공정하게 정리하고 토론의 방향을 제시하세요. '지금까지의 논의를 보면' 등을 사용하세요.",
        }

        prompt = (
            base_prompt
            + "\n🎭 **역할별 특별 지시**: "
            + role_instructions.get(self.role, "당신의 역할에 충실하게 응답하세요.")
        )

        # 직전 발언에 대한 구체적 응답 지시
        if last_speaker and last_content:
            prompt += f'\n\n💡 **직전 발언 응답 포인트**:\n{last_speaker}의 주장: "{last_content}"\n→ 이 주장에 대해 구체적으로 언급하며 시작하세요.'

        if focus_instruction:
            prompt += f"\n\n⚡ **특별 지시사항**: {focus_instruction}"

        prompt += "\n\n당신의 논증을 생성하세요:"

        return prompt

    def _summarize_context(self, context: List[Argument]) -> str:
        """대화 맥락 요약"""
        if not context:
            return "토론이 막 시작되었습니다."

        summary_parts = []

        # 현재 라운드 정보
        current_round = context[-1].round_number
        summary_parts.append(f"- 현재 {current_round}라운드 진행 중")

        # 각 팀의 최근 입장
        support_args = [
            arg for arg in context[-5:] if arg.stance == DebateStance.SUPPORT
        ]
        oppose_args = [arg for arg in context[-5:] if arg.stance == DebateStance.OPPOSE]

        if support_args:
            summary_parts.append(
                f"- 지지 팀 최근 주장: {len(support_args)}개 논증 제시"
            )
        if oppose_args:
            summary_parts.append(f"- 반대 팀 최근 주장: {len(oppose_args)}개 논증 제시")

        # 주요 쟁점 파악 (간단한 키워드 추출)
        all_content = " ".join([arg.content for arg in context[-5:]])
        if "하지만" in all_content or "그러나" in all_content:
            summary_parts.append("- 현재 의견 대립이 활발함")
        if "동의" in all_content or "맞습니다" in all_content:
            summary_parts.append("- 일부 합의점 발견")

        return "\n".join(summary_parts)

    def _format_context(self, context: List[Argument]) -> str:
        """컨텍스트 포맷팅 - 향상된 대화 흐름 표시"""
        if not context:
            return "아직 이전 발언이 없습니다."

        formatted = []
        current_round = -1

        for i, arg in enumerate(context):
            # 라운드 변경 시 구분선 추가
            if arg.round_number != current_round:
                current_round = arg.round_number
                formatted.append(f"\n--- 라운드 {current_round} ---")

            # 발언 순서 표시
            order_emoji = "💬" if i == len(context) - 1 else "💭"  # 마지막 발언 강조

            # 팀 표시
            team_indicator = ""
            if arg.stance == DebateStance.SUPPORT:
                team_indicator = "🟢"
            elif arg.stance == DebateStance.OPPOSE:
                team_indicator = "🔴"
            else:  # NEUTRAL (진행자)
                team_indicator = "🟡"

            # 발언 내용 (긴 내용은 요약)
            content = arg.content
            if len(content) > 300:
                content = content[:297] + "..."

            # 품질 점수가 있으면 표시
            quality_indicator = ""
            if hasattr(arg, "quality_score"):
                if arg.quality_score >= 0.8:
                    quality_indicator = " ⭐"
                elif arg.quality_score >= 0.6:
                    quality_indicator = " ✓"

            formatted.append(
                f"{order_emoji} {team_indicator} [{arg.agent_name}]{quality_indicator}: {content}"
            )

        return "\n".join(formatted)

    async def _check_api_health(self) -> bool:
        import httpx

        if not self.openrouter_api_key:
            self.logger.warning("OPENROUTER_API_KEY not set")
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.openrouter_api_url}/models",
                    headers={"Authorization": f"Bearer {self.openrouter_api_key}"},
                )
                return response.status_code == 200
        except Exception:
            return False

    async def _call_llm(self, prompt: str, stream_callback=None) -> Dict:
        import httpx
        import json
        import asyncio

        if not await self._check_api_health():
            self.logger.warning("OpenRouter API 연결 실패")
            return await self._generate_intelligent_fallback_async()

        api_url = f"{self.openrouter_api_url}/chat/completions"

        system_prompt = f"""{self.persona_prompt}

토론 응답 가이드라인:
- 자연스럽고 대화하듯이 응답하세요
- 3-5문장 정도로 간결하되 설득력 있게
- 구체적인 예시나 경험을 들어주세요
- 상대방 말에 직접 반응하면서 시작

응답 구조:
1. 상대방 의견에 대한 반응 (1문장)
2. 나의 핵심 주장 (1-2문장)
3. 근거나 예시 (1-2문장)
4. 마무리 (선택사항, 1문장)
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"토론 상황: {prompt}\n\n논리적이고 설득력 있는 응답을 생성해주세요.",
            },
        ]

        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://ai-debate-simulator.local",
            "X-Title": "AI Debate Simulator",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": bool(stream_callback),
            "temperature": self.temperature,
            "top_p": 0.95,
            "max_tokens": 800,
        }

        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(60.0, connect=15.0),
                    limits=httpx.Limits(
                        max_keepalive_connections=5, max_connections=10
                    ),
                    follow_redirects=True,
                ) as client:
                    if stream_callback:
                        actual_content = await self._handle_streaming_response(
                            client, api_url, headers, payload, stream_callback
                        )

                        analysis_result = await self._analyze_response_quality_async(
                            actual_content
                        )

                        return {
                            "content": analysis_result["cleaned_content"],
                            "evidence": analysis_result["evidence"],
                            "confidence": analysis_result["confidence"],
                            "quality_score": analysis_result["quality_score"],
                        }
                    else:
                        response = await client.post(
                            api_url, headers=headers, json=payload
                        )
                        response.raise_for_status()

                        data = response.json()
                        content = (
                            data.get("choices", [{}])[0]
                            .get("message", {})
                            .get("content", "")
                            .strip()
                        )

                        if not content:
                            raise ValueError("빈 응답 수신")

                        analysis_result = await self._analyze_response_quality_async(
                            content
                        )

                        return {
                            "content": analysis_result["cleaned_content"],
                            "evidence": analysis_result["evidence"],
                            "confidence": analysis_result["confidence"],
                            "quality_score": analysis_result["quality_score"],
                        }

            except Exception as e:
                self.logger.warning(f"LLM 호출 시도 {attempt + 1} 실패: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    self.logger.error(f"LLM 호출 최종 실패: {e}")

        return await self._generate_intelligent_fallback_async()

    async def _handle_streaming_response(
        self, client, api_url, headers, payload, stream_callback
    ):
        actual_content = ""
        self.logger.debug(f"스트리밍 시작: {self.name}")

        async with client.stream(
            "POST", api_url, headers=headers, json=payload
        ) as response:
            response.raise_for_status()
            self.logger.debug(f"스트리밍 응답 수신 시작: status={response.status_code}")

            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                if not line.startswith("data: "):
                    continue

                data_str = line[6:]
                if data_str == "[DONE]":
                    self.logger.debug("스트리밍 완료 신호")
                    break

                try:
                    chunk_data = json.loads(data_str)
                    choices = chunk_data.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    chunk = delta.get("content", "")

                    if chunk:
                        actual_content += chunk
                        self.logger.debug(f"청크 전송: {len(chunk)}자")
                        await stream_callback("content_chunk", chunk)
                        await asyncio.sleep(0.03)
                except json.JSONDecodeError:
                    continue

        if not actual_content.strip():
            default_msg = "[응답 생성 중 오류가 발생했습니다]"
            await stream_callback("content_chunk", default_msg)
            actual_content = default_msg

        self.logger.info(f"스트리밍 완료 - {len(actual_content)}자")
        return actual_content

    def _extract_response_from_thinking(self, thinking_content: str) -> str:
        """thinking 내용에서 실제 응답 추출"""
        if not thinking_content:
            return ""

        # thinking 내용이 실제로는 응답인 경우가 있음
        # 일부 모델은 thinking 태그 없이 직접 응답하거나, thinking 태그를 잘못 사용함

        # 1. thinking 내용이 대화체인지 확인
        conversational_indicators = [
            "그런데",
            "하지만",
            "사실",
            "정말",
            "진짜",
            "아니",
            "맞아",
            "그래",
            "네",
            "예",
            "생각해보면",
            "그렇지만",
            "그러나",
            "따라서",
            "그래서",
            "그러므로",
            "어요",
            "습니다",
            "죠",
            "거야",
            "거죠",
            "잖아",
            "거든",
            "해요",
        ]

        # 2. 질문이나 반박의 형태인지 확인
        question_indicators = ["?", "까요", "인가요", "일까요", "가요", "죠?"]

        # 3. 의견 표현인지 확인
        opinion_indicators = ["생각", "의견", "관점", "입장", "견해", "판단"]

        is_conversational = any(
            indicator in thinking_content for indicator in conversational_indicators
        )
        is_question = any(
            indicator in thinking_content for indicator in question_indicators
        )
        is_opinion = any(
            indicator in thinking_content for indicator in opinion_indicators
        )

        # 4. thinking 내용이 실제 응답처럼 보이는지 확인
        if is_conversational or is_question or is_opinion:
            # thinking 내용을 정리하여 응답으로 변환
            response = thinking_content.strip()

            # 너무 길면 요약
            if len(response) > 300:
                sentences = response.split(".")
                response = ". ".join(sentences[:3]) + "."

            # 메타 언급 제거 (thinking에 대한 언급)
            meta_phrases = [
                "생각해보니",
                "생각해보면",
                "생각을 해보면",
                "고민해보니",
                "고민해보면",
                "분석해보니",
                "분석해보면",
                "판단해보니",
                "판단해보면",
            ]

            for phrase in meta_phrases:
                if response.startswith(phrase):
                    response = response[len(phrase) :].strip()
                    if response.startswith(","):
                        response = response[1:].strip()
                    break

            return response

        # 5. thinking 내용이 너무 메타적이면 기본 응답 생성
        if len(thinking_content) > 50:
            # thinking 내용의 핵심 키워드를 추출하여 응답 생성
            keywords = []
            important_words = thinking_content.split()

            for word in important_words[:20]:  # 처음 20개 단어만 확인
                if len(word) > 2 and word not in [
                    "그런데",
                    "하지만",
                    "생각",
                    "아니",
                    "진짜",
                ]:
                    keywords.append(word)
                    if len(keywords) >= 3:
                        break

            if keywords:
                return f"흥미로운 점이 있네요. {' '.join(keywords[:2])}에 대해 생각해보면 복잡한 문제인 것 같습니다. 좀 더 자세히 살펴볼 필요가 있을 것 같아요."

        return ""

    async def _analyze_response_quality_async(self, content: str) -> Dict:
        """Context7 방식: 비동기 응답 품질 분석"""
        return self._analyze_response_quality(content)

    async def _generate_intelligent_fallback_async(self) -> Dict:
        """Context7 방식: 비동기 지능형 폴백"""
        return self._generate_intelligent_fallback()

    def _analyze_response_quality(self, content: str) -> Dict:
        """KITECH 방식: 응답 품질 분석 및 개선"""

        # 기본 정리
        cleaned_content = content.strip()

        # 증거 추출 (강화된 패턴)
        evidence = []
        evidence_patterns = [
            "연구에 따르면",
            "데이터에 의하면",
            "통계적으로",
            "전문가들은",
            "보고서에서",
            "조사 결과",
            "실험을 통해",
            "분석에 따르면",
            "예를 들어",
            "실제로",
            "구체적으로",
            "사실",
        ]

        sentences = cleaned_content.replace("!", ".").replace("?", ".").split(".")
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and any(pattern in sentence for pattern in evidence_patterns):
                evidence.append(sentence)
                if len(evidence) >= 3:
                    break

        # 품질 점수 계산 (KITECH 평가 기준)
        quality_score = 0.5

        # 길이 적절성 (50-300자 최적)
        if 50 <= len(cleaned_content) <= 300:
            quality_score += 0.1

        # 논리 구조 (접속사 사용)
        logical_connectors = [
            "따라서",
            "그러므로",
            "왜냐하면",
            "또한",
            "하지만",
            "그러나",
            "반면에",
        ]
        if any(conn in cleaned_content for conn in logical_connectors):
            quality_score += 0.1

        # 구체성 (숫자, 고유명사 포함)
        import re

        if re.search(r"\d+", cleaned_content) or any(
            char.isupper() for char in cleaned_content
        ):
            quality_score += 0.1

        # 감정적 어조 적절성
        emotional_words = ["놀랍게도", "확실히", "분명히", "당연히", "절대적으로"]
        if any(word in cleaned_content for word in emotional_words):
            quality_score += 0.05

        # 신뢰도 계산
        confidence = quality_score
        if evidence:
            confidence += 0.15
        if len(cleaned_content) > 100:
            confidence += 0.05

        return {
            "cleaned_content": cleaned_content,
            "evidence": evidence[:3],
            "confidence": min(confidence, 0.95),
            "quality_score": min(quality_score, 1.0),
        }

    def _generate_intelligent_fallback(self) -> Dict:
        """KITECH 방식: 역할별 지능형 폴백 응답"""
        fallback_templates = {
            AgentRole.SEARCHER: "🔍 **현재 관련 자료를 분석 중입니다.** 기존 연구들을 종합해보면, 이 주제에 대한 다양한 관점들이 존재합니다. 더 구체적인 데이터 수집이 필요한 상황입니다.",
            AgentRole.ANALYZER: "🧠 **논리적 분석을 진행하겠습니다.** 제시된 논증의 구조를 살펴보면, 전제와 결론 사이의 연결고리를 더 명확히 할 필요가 있어 보입니다.",
            AgentRole.WRITER: "✍️ **설득력 있는 관점을 제시하겠습니다.** 이 문제의 핵심은 다각도로 접근해야 한다는 점입니다. 실용적 측면에서 볼 때 중요한 고려사항들이 있습니다.",
            AgentRole.REVIEWER: "📋 **품질 검토 관점에서 말씀드리면,** 현재 논의에서 더 보완이 필요한 부분들이 있습니다. 논증의 완성도를 높이기 위한 추가 고려사항을 제안드립니다.",
            AgentRole.DEVIL: "😈 **잠깐, 이 부분은 문제가 있어 보입니다!** 🤨 제시된 주장에는 몇 가지 **중대한 허점**이 있습니다. 과연 이것이 최선의 접근방식일까요?",
            AgentRole.ANGEL: "😇 **긍정적인 관점에서 보겠습니다!** ✨ 이 접근방식에는 분명한 **장점들**이 있습니다. 특히 장기적 관점에서 매우 **희망적인** 결과를 기대할 수 있습니다! 💖",
            AgentRole.ORGANIZER: "🎯 **토론 진행자로서 말씀드리겠습니다.** 📋 현재까지의 논의를 종합해보면, 양측 모두 **의미 있는 관점**들을 제시하고 있습니다. 이제 다음 단계로 나아가겠습니다! 🎪",
        }

        fallback_content = fallback_templates.get(
            self.role,
            "🤔 **신중한 검토가 필요한 시점입니다.** 더 심도 있는 분석을 통해 더 나은 답변을 제공하겠습니다.",
        )

        return {
            "content": fallback_content,
            "evidence": ["시스템 복구 중 임시 응답"],
            "confidence": 0.6,
            "quality_score": 0.7,
        }

    def evaluate_opponent_argument(self, argument: Argument) -> Dict[str, float]:
        """
        상대 논증 평가 - M-MAD의 다차원 평가 적용
        """
        dimensions = {
            "logical_coherence": 0.0,
            "evidence_quality": 0.0,
            "persuasiveness": 0.0,
            "relevance": 0.0,
            "originality": 0.0,
        }

        # 역할별 특화된 평가
        if self.role == AgentRole.ANALYZER:
            # 분석가는 논리적 일관성에 중점
            dimensions["logical_coherence"] = self._evaluate_logic(argument)
        elif self.role == AgentRole.REVIEWER:
            # 검토자는 전반적인 품질 평가
            dimensions = self._comprehensive_evaluation(argument)

        return dimensions

    def _evaluate_logic(self, argument: Argument) -> float:
        """논리적 일관성 평가"""
        # 실제 구현 필요
        return 0.7

    def _comprehensive_evaluation(self, argument: Argument) -> Dict[str, float]:
        """종합적 평가"""
        # 실제 구현 필요
        return {
            "logical_coherence": 0.8,
            "evidence_quality": 0.7,
            "persuasiveness": 0.75,
            "relevance": 0.9,
            "originality": 0.6,
        }
