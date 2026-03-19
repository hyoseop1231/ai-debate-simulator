"""All debate endpoints, session management, and debate logic."""

import asyncio
import html
import logging
import random
import re
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, validator

from api.middleware import rate_limit_dependency
from api.state import DEBATE_FORMATS, active_debates, metrics
from debate_agent import AgentRole, Argument, DebateAgent, DebateStance
from debate_controller import DebateConfig, DebateController, DebateFormat
from debate_evaluator import DebateEvaluator

logger = logging.getLogger(__name__)

router = APIRouter(tags=["debate"])


class DebateSession:
    def __init__(self, session_id: str, config: DebateConfig) -> None:
        self.session_id = session_id
        self.config = config
        self.controller: Optional[DebateController] = None
        self.support_agents: list = []
        self.oppose_agents: list = []
        self.organizer: Optional[DebateAgent] = None
        self.evaluator = DebateEvaluator()
        self.clients: list = []
        self.current_round: int = 0
        self.is_active: bool = True


class DebateRequest(BaseModel):
    topic: str = Field(..., min_length=5, max_length=500, description="Debate topic")
    format: str = Field(
        "adversarial",
        pattern="^(adversarial|collaborative|competitive|custom)$",
        description="Debate format",
    )
    max_rounds: int = Field(5, ge=1, le=10, description="Max rounds")
    model: str = Field("anthropic/claude-sonnet-4", description="AI model to use")
    language: str = Field("한국어", description="Language")
    support_agents: List[Dict] = Field([], description="Support agents")
    oppose_agents: List[Dict] = Field([], description="Oppose agents")
    custom_config: Optional[Dict] = Field(None, description="Custom config")

    @validator("topic")
    def sanitize_topic(cls, v: str) -> str:
        """Validate and sanitize debate topic."""
        if not v or not v.strip():
            raise ValueError("토론 주제는 비어있을 수 없습니다.")

        clean_topic = html.escape(v.strip())

        xss_patterns = [
            r"<script[^>]*>.*?</script>",
            r"javascript:",
            r"on\w+\s*=",
            r"<iframe[^>]*>.*?</iframe>",
        ]

        for pattern in xss_patterns:
            clean_topic = re.sub(
                pattern, "", clean_topic, flags=re.IGNORECASE | re.DOTALL
            )

        clean_topic = re.sub(r"\s+", " ", clean_topic)

        if len(clean_topic) < 5:
            raise ValueError("토론 주제는 최소 5자 이상이어야 합니다.")

        return clean_topic


@router.get("/", response_class=HTMLResponse)
async def home():
    """Main page - load templates/index.html."""
    import pathlib

    template_path = pathlib.Path(__file__).parent.parent.parent / "templates" / "index.html"
    try:
        html_content = template_path.read_text(encoding="utf-8")
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Error: templates/index.html not found</h1>",
            status_code=500,
        )


@router.get("/favicon.ico")
async def favicon():
    return HTMLResponse("", status_code=204)


@router.post("/api/debate/start", dependencies=[Depends(rate_limit_dependency)])
async def start_debate(request: DebateRequest, background_tasks: BackgroundTasks):
    """Start a debate session."""
    try:
        session_id = str(uuid.uuid4())

        metrics.record_debate_start()

        config = DebateConfig(
            topic=request.topic,
            format=DebateFormat[request.format.upper()],
            max_rounds=request.max_rounds,
        )

        korean_prompt = "한국어로 답변해주세요. " if request.language == "ko" else ""

        format_data = DEBATE_FORMATS[request.format]

        organizer_config = format_data["organizer"]
        organizer = DebateAgent(
            name=organizer_config["name"],
            role=AgentRole.ORGANIZER,
            stance=DebateStance.NEUTRAL,
            model=request.model,
            persona_prompt=korean_prompt + f"당신은 {organizer_config['name']}입니다.",
            temperature=0.7,
        )

        support_agents = []
        for agent_config in request.support_agents:
            if request.custom_config and agent_config.get("persona"):
                enhanced_persona = f"""
{korean_prompt}

🎭 **캐릭터 정의**: 당신은 {agent_config["name"]}입니다.

📝 **전문 페르소나**: {agent_config["persona"]}

🎯 **역할 특화**: {agent_config["role"]} 역할을 담당하며, 다음과 같은 특성을 가집니다:
- 일관된 성격과 어조 유지
- 전문 분야에 대한 깊은 지식
- 상대방과의 상호작용에서 캐릭터 특성 반영
- 논증 스타일과 접근 방식에서 개성 표현

💬 **응답 가이드라인**:
- 캐릭터의 배경과 전문성을 자연스럽게 반영
- 일관된 어조와 관점 유지
- {agent_config["emoji"]} 이모티콘을 적절히 활용
- 3-5문장으로 명확하고 설득력 있게 표현
            """
            else:
                enhanced_persona = (
                    korean_prompt + f"당신은 {agent_config['name']}입니다."
                )

            agent = DebateAgent(
                name=agent_config["name"],
                role=AgentRole[agent_config["role"].upper()],
                stance=DebateStance.SUPPORT,
                model=request.model,
                persona_prompt=enhanced_persona,
                temperature=0.8,
            )
            support_agents.append(agent)

        oppose_agents = []
        for agent_config in request.oppose_agents:
            if request.custom_config and agent_config.get("persona"):
                enhanced_persona = f"""
{korean_prompt}

🎭 **캐릭터 정의**: 당신은 {agent_config["name"]}입니다.

📝 **전문 페르소나**: {agent_config["persona"]}

🎯 **역할 특화**: {agent_config["role"]} 역할을 담당하며, 다음과 같은 특성을 가집니다:
- 일관된 성격과 어조 유지
- 전문 분야에 대한 깊은 지식
- 상대방과의 상호작용에서 캐릭터 특성 반영
- 논증 스타일과 접근 방식에서 개성 표현

💬 **응답 가이드라인**:
- 캐릭터의 배경과 전문성을 자연스럽게 반영
- 일관된 어조와 관점 유지
- {agent_config["emoji"]} 이모티콘을 적절히 활용
- 3-5문장으로 명확하고 설득력 있게 표현
            """
            else:
                enhanced_persona = (
                    korean_prompt + f"당신은 {agent_config['name']}입니다."
                )

            agent = DebateAgent(
                name=agent_config["name"],
                role=AgentRole[agent_config["role"].upper()],
                stance=DebateStance.OPPOSE,
                model=request.model,
                persona_prompt=enhanced_persona,
                temperature=0.8,
            )
            oppose_agents.append(agent)

        controller = DebateController(config, support_agents, oppose_agents)

        session = DebateSession(session_id, config)
        session.controller = controller
        session.support_agents = support_agents
        session.oppose_agents = oppose_agents
        session.organizer = organizer
        active_debates[session_id] = session

        controller.start_debate()

        background_tasks.add_task(conduct_debate_async, session, request.language)

        return {"session_id": session_id, "status": "started"}

    except KeyError as e:
        logger.error("KeyError in start_debate: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail="잘못된 설정값입니다.")
    except Exception as e:
        logger.error("Error in start_debate: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500, detail="내부 오류가 발생했습니다."
        )


# ---------------------------------------------------------------------------
# Debate analysis helpers
# ---------------------------------------------------------------------------


async def perform_comprehensive_debate_analysis(
    debate_history: List[Argument], topic: str, total_rounds: int
) -> Dict:
    """Perform comprehensive analysis of a debate."""
    support_args = [arg for arg in debate_history if arg.stance.value == "support"]
    oppose_args = [arg for arg in debate_history if arg.stance.value == "oppose"]

    analysis = {
        "statistics": await generate_debate_statistics(
            debate_history, support_args, oppose_args, total_rounds
        ),
        "team_analysis": await analyze_team_strategies(
            support_args, oppose_args, topic
        ),
        "dimension_scores": await calculate_dimensional_scores(
            support_args, oppose_args
        ),
        "debate_flow": await analyze_debate_flow(debate_history, total_rounds),
        "key_moments": await identify_key_moments(debate_history),
        "argument_quality": await evaluate_argument_quality(debate_history),
    }

    return analysis


async def generate_debate_statistics(
    debate_history: List[Argument],
    support_args: List[Argument],
    oppose_args: List[Argument],
    total_rounds: int,
) -> str:
    """Generate debate statistics."""
    total_arguments = len(debate_history)
    support_count = len(support_args)
    oppose_count = len(oppose_args)

    avg_support_quality = sum(
        getattr(arg, "quality_score", 0.7) for arg in support_args
    ) / max(len(support_args), 1)
    avg_oppose_quality = sum(
        getattr(arg, "quality_score", 0.7) for arg in oppose_args
    ) / max(len(oppose_args), 1)

    support_evidence = sum(1 for arg in support_args if getattr(arg, "evidence", []))
    oppose_evidence = sum(1 for arg in oppose_args if getattr(arg, "evidence", []))

    statistics = f"""
📊 **토론 참여 통계**
- 총 발언 수: {total_arguments}개 ({total_rounds}라운드)
- 지지측 발언: {support_count}개
- 반대측 발언: {oppose_count}개
- 라운드당 평균 발언: {total_arguments / max(total_rounds, 1):.1f}개

📈 **논증 품질 점수**
- 지지측 평균 품질: {avg_support_quality:.2f}/1.0
- 반대측 평균 품질: {avg_oppose_quality:.2f}/1.0
- 전체 평균 품질: {(avg_support_quality + avg_oppose_quality) / 2:.2f}/1.0

🔍 **증거 제시 현황**
- 지지측 증거 제시: {support_evidence}회
- 반대측 증거 제시: {oppose_evidence}회
- 증거 제시율: {((support_evidence + oppose_evidence) / max(total_arguments, 1) * 100):.1f}%
"""
    return statistics


async def analyze_team_strategies(
    support_args: List[Argument], oppose_args: List[Argument], topic: str
) -> str:
    """Analyze each team's strategy and key arguments."""

    def extract_key_themes(arguments: list) -> list:
        all_text = " ".join([arg.content for arg in arguments])

        themes = {
            "경제적 관점": [
                "경제", "비용", "돈", "투자", "효율", "수익", "예산", "경비",
            ],
            "사회적 관점": ["사회", "사람들", "공동체", "시민", "공공", "복지", "평등"],
            "윤리적 관점": ["윤리", "도덕", "옳은", "잘못", "가치", "원칙", "정의"],
            "실용적 관점": ["실용", "현실", "실제", "구체적", "방법", "해결", "개선"],
            "미래지향적": ["미래", "발전", "진보", "혁신", "변화", "성장", "발달"],
            "안전/보안": ["안전", "보안", "위험", "리스크", "보호", "예방"],
        }

        team_themes = []
        for theme_name, keywords in themes.items():
            count = sum(all_text.count(keyword) for keyword in keywords)
            if count > 0:
                team_themes.append(f"{theme_name}({count}회)")

        return team_themes[:3]

    support_themes = extract_key_themes(support_args)
    oppose_themes = extract_key_themes(oppose_args)

    support_avg_length = sum(len(arg.content) for arg in support_args) / max(
        len(support_args), 1
    )
    oppose_avg_length = sum(len(arg.content) for arg in oppose_args) / max(
        len(oppose_args), 1
    )

    analysis = f"""
🎯 **지지측 전략 분석**
- 주요 접근 방식: {", ".join(support_themes) if support_themes else "일반적 논증"}
- 평균 논증 길이: {support_avg_length:.0f}자
- 논증 스타일: {"상세한 설명 중심" if support_avg_length > 200 else "간결한 논증 중심"}

🎯 **반대측 전략 분석**
- 주요 접근 방식: {", ".join(oppose_themes) if oppose_themes else "일반적 논증"}
- 평균 논증 길이: {oppose_avg_length:.0f}자
- 논증 스타일: {"상세한 설명 중심" if oppose_avg_length > 200 else "간결한 논증 중심"}

⚖️ **전략 비교**
- 논증 접근법: {"유사한 테마" if len(set(support_themes) & set(oppose_themes)) > 0 else "차별화된 접근"}
- 논증 길이 차이: {abs(support_avg_length - oppose_avg_length):.0f}자
"""
    return analysis


async def calculate_dimensional_scores(
    support_args: List[Argument], oppose_args: List[Argument]
) -> str:
    """Calculate multi-dimensional evaluation scores."""

    def calculate_team_dimensions(arguments: list) -> dict:
        if not arguments:
            return {}

        logical_keywords = [
            "따라서", "그러므로", "왜냐하면", "첫째", "둘째", "결론적으로",
        ]
        logic_score = 0
        for arg in arguments:
            logic_score += sum(
                1 for keyword in logical_keywords if keyword in arg.content
            )
        logic_score = min(logic_score / len(arguments) * 0.2 + 0.6, 1.0)

        evidence_keywords = ["연구", "데이터", "통계", "조사", "실험", "사례", "예시"]
        evidence_score = 0
        for arg in arguments:
            evidence_score += sum(
                1 for keyword in evidence_keywords if keyword in arg.content
            )
            evidence_score += len(getattr(arg, "evidence", [])) * 0.5
        evidence_score = min(evidence_score / len(arguments) * 0.15 + 0.5, 1.0)

        persuasive_keywords = ["반드시", "중요한", "명백히", "분명히", "절대적으로"]
        persuasion_score = 0
        for arg in arguments:
            persuasion_score += sum(
                1 for keyword in persuasive_keywords if keyword in arg.content
            )
        persuasion_score = min(persuasion_score / len(arguments) * 0.2 + 0.6, 1.0)

        quality_score = sum(
            getattr(arg, "quality_score", 0.7) for arg in arguments
        ) / len(arguments)

        return {
            "논리성": logic_score,
            "증거성": evidence_score,
            "설득력": persuasion_score,
            "전체품질": quality_score,
        }

    support_scores = calculate_team_dimensions(support_args)
    oppose_scores = calculate_team_dimensions(oppose_args)

    dimensions_text = "⚖️ **다차원 평가 결과**\n"

    for dimension in ["논리성", "증거성", "설득력", "전체품질"]:
        s_score = support_scores.get(dimension, 0.5)
        o_score = oppose_scores.get(dimension, 0.5)
        winner = (
            "지지측" if s_score > o_score else "반대측" if o_score > s_score else "동점"
        )

        dimensions_text += f"- **{dimension}**: 지지측 {s_score:.2f} vs 반대측 {o_score:.2f} → {winner} 우세\n"

    return dimensions_text


async def analyze_debate_flow(
    debate_history: List[Argument], total_rounds: int
) -> str:
    """Analyze debate flow and turning points."""
    round_analysis = []

    for round_num in range(1, total_rounds + 1):
        round_args = [arg for arg in debate_history if arg.round_number == round_num]
        if not round_args:
            continue

        avg_quality = sum(
            getattr(arg, "quality_score", 0.7) for arg in round_args
        ) / len(round_args)
        round_themes = []

        all_content = " ".join([arg.content for arg in round_args])
        if "따라서" in all_content or "결론" in all_content:
            round_themes.append("결론 제시")
        if "반박" in all_content or "그러나" in all_content:
            round_themes.append("반박 활발")
        if "새로운" in all_content or "다른" in all_content:
            round_themes.append("새로운 관점")

        round_analysis.append(
            {
                "round": round_num,
                "quality": avg_quality,
                "themes": round_themes,
                "arg_count": len(round_args),
            }
        )

    flow_text = "🌊 **토론 흐름 분석**\n"

    for i, round_data in enumerate(round_analysis):
        flow_text += f"- **{round_data['round']}라운드**: "
        flow_text += (
            f"품질 {round_data['quality']:.2f}, {round_data['arg_count']}개 발언"
        )
        if round_data["themes"]:
            flow_text += f" ({', '.join(round_data['themes'])})"
        flow_text += "\n"

    if len(round_analysis) > 1:
        quality_changes = []
        for i in range(1, len(round_analysis)):
            quality_diff = (
                round_analysis[i]["quality"] - round_analysis[i - 1]["quality"]
            )
            if abs(quality_diff) > 0.1:
                direction = "상승" if quality_diff > 0 else "하락"
                quality_changes.append(
                    f"{round_analysis[i]['round']}라운드에서 품질 {direction}"
                )

        if quality_changes:
            flow_text += f"\n🔄 **주요 전환점**: {', '.join(quality_changes)}"

    return flow_text


async def identify_key_moments(debate_history: List[Argument]) -> str:
    """Identify decisive moments and best arguments."""
    if not debate_history:
        return "💡 **분석할 논증이 없습니다.**"

    best_arg = max(debate_history, key=lambda x: getattr(x, "quality_score", 0.7))
    worst_arg = min(debate_history, key=lambda x: getattr(x, "quality_score", 0.7))

    longest_arg = max(debate_history, key=lambda x: len(x.content))
    shortest_arg = min(debate_history, key=lambda x: len(x.content))

    evidence_arg = max(
        debate_history, key=lambda x: len(getattr(x, "evidence", []))
    )

    key_moments = f"""
💡 **결정적 순간들**

🏆 **최고 품질 논증**
- 발언자: {best_arg.agent_name} ({best_arg.stance.value})
- 라운드: {best_arg.round_number}
- 품질 점수: {getattr(best_arg, "quality_score", 0.7):.2f}
- 내용 미리보기: {best_arg.content[:100]}...

📊 **가장 상세한 논증**
- 발언자: {longest_arg.agent_name} ({longest_arg.stance.value})
- 길이: {len(longest_arg.content)}자
- 라운드: {longest_arg.round_number}

🔍 **가장 많은 증거 제시**
- 발언자: {evidence_arg.agent_name} ({evidence_arg.stance.value})
- 증거 개수: {len(getattr(evidence_arg, "evidence", []))}개
- 라운드: {evidence_arg.round_number}
"""

    return key_moments


async def evaluate_argument_quality(debate_history: List[Argument]) -> str:
    """Evaluate overall argument quality."""
    if not debate_history:
        return "분석할 논증이 없습니다."

    total_quality = sum(getattr(arg, "quality_score", 0.7) for arg in debate_history)
    avg_quality = total_quality / len(debate_history)

    high_quality_count = sum(
        1 for arg in debate_history if getattr(arg, "quality_score", 0.7) >= 0.8
    )
    low_quality_count = sum(
        1 for arg in debate_history if getattr(arg, "quality_score", 0.7) <= 0.5
    )

    quality_assessment = f"""
📈 **전체 논증 품질 평가**

⭐ **품질 점수 분포**
- 전체 평균: {avg_quality:.2f}/1.0
- 고품질 논증(0.8↑): {high_quality_count}개 ({high_quality_count / len(debate_history) * 100:.1f}%)
- 저품질 논증(0.5↓): {low_quality_count}개 ({low_quality_count / len(debate_history) * 100:.1f}%)

🎯 **품질 수준 판정**
- 토론 수준: {"매우 높음" if avg_quality >= 0.8 else "높음" if avg_quality >= 0.7 else "보통" if avg_quality >= 0.6 else "개선 필요"}
- 논증 균질성: {"일정함" if max(getattr(arg, "quality_score", 0.7) for arg in debate_history) - min(getattr(arg, "quality_score", 0.7) for arg in debate_history) < 0.3 else "편차 큼"}
"""

    return quality_assessment


async def analyze_current_round(
    round_args: List[Argument], round_num: int, topic: str
) -> str:
    """Analyze the current round."""
    if not round_args:
        return f"라운드 {round_num}에 논증이 없습니다."

    support_round_args = [arg for arg in round_args if arg.stance.value == "support"]
    oppose_round_args = [arg for arg in round_args if arg.stance.value == "oppose"]

    total_args = len(round_args)
    avg_quality = sum(getattr(arg, "quality_score", 0.7) for arg in round_args) / len(
        round_args
    )

    support_quality = sum(
        getattr(arg, "quality_score", 0.7) for arg in support_round_args
    ) / max(len(support_round_args), 1)
    oppose_quality = sum(
        getattr(arg, "quality_score", 0.7) for arg in oppose_round_args
    ) / max(len(oppose_round_args), 1)

    support_evidence = sum(
        1 for arg in support_round_args if getattr(arg, "evidence", [])
    )
    oppose_evidence = sum(
        1 for arg in oppose_round_args if getattr(arg, "evidence", [])
    )

    avg_support_length = sum(len(arg.content) for arg in support_round_args) / max(
        len(support_round_args), 1
    )
    avg_oppose_length = sum(len(arg.content) for arg in oppose_round_args) / max(
        len(oppose_round_args), 1
    )

    all_content = " ".join([arg.content for arg in round_args])
    round_characteristics = []

    if "반박" in all_content or "그러나" in all_content or "하지만" in all_content:
        round_characteristics.append("활발한 반박")
    if "증거" in all_content or "연구" in all_content or "데이터" in all_content:
        round_characteristics.append("증거 기반")
    if "새로운" in all_content or "다른" in all_content:
        round_characteristics.append("새로운 관점 제시")
    if "결론" in all_content or "따라서" in all_content:
        round_characteristics.append("결론 도출")

    analysis = f"""
📊 **라운드 {round_num} 통계**
- 총 발언 수: {total_args}개 (지지측: {len(support_round_args)}개, 반대측: {len(oppose_round_args)}개)
- 평균 품질 점수: {avg_quality:.2f}/1.0
- 라운드 특성: {", ".join(round_characteristics) if round_characteristics else "일반적 토론"}

⚖️ **팀별 성과**
- 지지측: 품질 {support_quality:.2f}, 증거 {support_evidence}회, 평균길이 {avg_support_length:.0f}자
- 반대측: 품질 {oppose_quality:.2f}, 증거 {oppose_evidence}회, 평균길이 {avg_oppose_length:.0f}자
- 라운드 우세팀: {"지지측" if support_quality > oppose_quality else "반대측" if oppose_quality > support_quality else "균등"}

🔍 **주요 논점 키워드**
- 주제 관련도: {"높음" if topic.split()[0] in all_content else "보통"}
- 논리적 구조: {"우수" if "따라서" in all_content or "왜냐하면" in all_content else "보통"}
- 감정적 호소: {"강함" if "중요" in all_content or "반드시" in all_content else "보통"}
"""

    return analysis


# ---------------------------------------------------------------------------
# Broadcast helpers
# ---------------------------------------------------------------------------


async def broadcast_argument(session: DebateSession, argument: Argument) -> None:
    """Broadcast an argument (with quality score)."""
    message = {
        "type": "argument",
        "data": {
            "agent_name": argument.agent_name,
            "stance": argument.stance.value,
            "content": argument.content,
            "round": argument.round_number,
            "confidence_score": argument.confidence_score,
            "quality_score": getattr(argument, "quality_score", 0.7),
            "evidence": getattr(argument, "evidence", []),
        },
    }
    await broadcast_message(session, message)


async def broadcast_argument_streaming(
    session: DebateSession, agent, topic: str, context: list, round_num: int, prompt: str
) -> Argument:
    """Stream an argument via WebSocket with retry logic."""
    thinking_chunks: list = []
    content_chunks: list = []
    max_retries = 3
    retry_delay = 2

    import time as _time

    message_id = f"{agent.name}-{round_num}-thinking-{int(_time.time() * 1000)}"

    async def stream_callback(message_type: str, chunk: str) -> None:
        try:
            if message_type == "thinking_start":
                await broadcast_message(
                    session,
                    {
                        "type": "thinking_start",
                        "data": {
                            "agent_name": agent.name,
                            "stance": agent.stance.value,
                            "round": round_num,
                            "message_id": message_id,
                        },
                    },
                )
            elif message_type == "thinking_chunk":
                thinking_chunks.append(chunk)
                await broadcast_message(
                    session,
                    {
                        "type": "thinking_chunk",
                        "data": {
                            "agent_name": agent.name,
                            "chunk": chunk,
                            "message_id": message_id,
                        },
                    },
                )
            elif message_type == "thinking_complete":
                await broadcast_message(
                    session,
                    {
                        "type": "thinking_complete",
                        "data": {
                            "agent_name": agent.name,
                            "thinking_content": "".join(thinking_chunks),
                            "message_id": message_id,
                        },
                    },
                )
                thinking_chunks.clear()
            elif message_type == "content_chunk":
                content_chunks.append(chunk)
                if agent.role.value == "ORGANIZER" and round_num > 5:
                    for mini_chunk in [
                        chunk[i : i + 50] for i in range(0, len(chunk), 50)
                    ]:
                        if mini_chunk.strip():
                            await broadcast_message(
                                session,
                                {
                                    "type": "content_chunk",
                                    "data": {
                                        "agent_name": agent.name,
                                        "chunk": mini_chunk,
                                        "stance": agent.stance.value,
                                    },
                                },
                            )
                            await asyncio.sleep(0.05)
                else:
                    await broadcast_message(
                        session,
                        {
                            "type": "content_chunk",
                            "data": {
                                "agent_name": agent.name,
                                "chunk": chunk,
                                "stance": agent.stance.value,
                            },
                        },
                    )
        except Exception as e:
            logger.warning("Streaming callback error: %s", e)

    argument = None
    last_error = None

    for attempt in range(max_retries):
        try:
            timeout_duration = (
                120.0 if agent.role.value == "ORGANIZER" and round_num > 5 else 45.0
            )
            argument = await asyncio.wait_for(
                agent.generate_argument(
                    topic, context, round_num, prompt, stream_callback=stream_callback
                ),
                timeout=timeout_duration,
            )

            if argument and argument.content:
                break

        except asyncio.TimeoutError:
            last_error = "응답 시간 초과"
            logger.warning(
                "%s response timeout (attempt %d/%d)",
                agent.name, attempt + 1, max_retries,
            )

        except Exception as e:
            last_error = str(e)
            logger.error(
                "%s response generation failed (attempt %d/%d): %s",
                agent.name, attempt + 1, max_retries, e,
            )

        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
            retry_delay *= 1.5

            await broadcast_message(
                session,
                {
                    "type": "system",
                    "data": {
                        "message": f"🔄 {agent.name}의 응답을 재시도하고 있습니다... (시도 {attempt + 2}/{max_retries})"
                    },
                },
            )

    if not argument or not argument.content:
        logger.warning("%s using fallback response", agent.name)

        argument = Argument(
            content=f"[기술적 문제로 {agent.name}의 응답이 일시적으로 지연되었습니다. 다음 라운드에서 더 나은 논증을 제시하겠습니다.]",
            agent_name=agent.name,
            stance=agent.stance,
            round_number=round_num,
            evidence=[],
            confidence_score=0.5,
            quality_score=0.5,
        )

        await broadcast_message(
            session,
            {
                "type": "system",
                "data": {
                    "message": f"⚠️ {agent.name}의 응답 생성에 문제가 발생했습니다. 임시 응답으로 대체합니다.",
                    "error": last_error,
                },
            },
        )

    await broadcast_message(
        session,
        {
            "type": "argument_complete",
            "data": {
                "agent_name": argument.agent_name,
                "stance": argument.stance.value,
                "content": argument.content,
                "round": argument.round_number,
                "confidence_score": argument.confidence_score,
                "quality_score": getattr(argument, "quality_score", 0.7),
                "evidence": getattr(argument, "evidence", []),
                "thinking_content": getattr(argument, "thinking_content", ""),
            },
        },
    )

    return argument


async def broadcast_evaluation(session: DebateSession, scores: dict) -> None:
    """Broadcast evaluation scores."""
    message = {"type": "evaluation", "data": scores}
    await broadcast_message(session, message)


async def broadcast_message(session: DebateSession, message: dict) -> None:
    """Enhanced message broadcast with metadata."""
    disconnected = []
    broadcast_start = asyncio.get_event_loop().time()
    successful_sends = 0

    enhanced_message = {
        **message,
        "metadata": {
            "timestamp": broadcast_start * 1000,
            "session_id": session.session_id,
            "broadcast_id": str(uuid.uuid4())[:8],
        },
    }

    send_tasks = []
    for client in session.clients:
        task = asyncio.create_task(safe_send_message(client, enhanced_message))
        send_tasks.append((client, task))

    for client, task in send_tasks:
        try:
            success = await asyncio.wait_for(task, timeout=5.0)
            if success:
                successful_sends += 1
            else:
                disconnected.append(client)
        except asyncio.TimeoutError:
            logger.warning("Client %s timeout", id(client))
            disconnected.append(client)
        except Exception as e:
            logger.error("Client %s send failed: %s", id(client), e)
            disconnected.append(client)

    for client in disconnected:
        if client in session.clients:
            session.clients.remove(client)

    broadcast_time = (asyncio.get_event_loop().time() - broadcast_start) * 1000
    if broadcast_time > 100:
        logger.warning(
            "Slow broadcast: %.2fms, success: %d/%d",
            broadcast_time, successful_sends, len(send_tasks),
        )


async def safe_send_message(client, message: dict) -> bool:
    """Safe message send."""
    try:
        await client.send_json(message)
        return True
    except Exception as e:
        logger.debug("Client send failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Main debate conductor
# ---------------------------------------------------------------------------


async def conduct_debate_async(session: DebateSession, language: str) -> None:
    """Conduct the debate with random turn-taking and organizer interjections."""
    controller = session.controller
    korean_context = "한국어로 토론하세요. " if language == "ko" else ""

    await asyncio.sleep(2)

    # Organizer opening
    organizer_intro = await broadcast_argument_streaming(
        session,
        session.organizer,
        controller.config.topic,
        [],
        0,
        f"{korean_context}토론을 시작하겠습니다. 주제: '{controller.config.topic}'. 모든 참가자는 자유롭게 의견을 표현해주세요.",
    )
    await asyncio.sleep(3)

    support_score = 0.5
    oppose_score = 0.5

    for round_num in range(1, controller.config.max_rounds + 1):
        if session.session_id not in active_debates:
            logger.info("Session %s terminated, stopping debate", session.session_id)
            break

        logger.info("Round %d start (session: %s)", round_num, session.session_id)
        controller.current_round = round_num

        await broadcast_message(
            session, {"type": "round_start", "data": {"round": round_num}}
        )

        await asyncio.sleep(2)

        all_agents = []

        for agent in session.support_agents:
            all_agents.append(("support", agent))
        for agent in session.oppose_agents:
            all_agents.append(("oppose", agent))

        random.shuffle(all_agents)

        speaker_names = [agent[1].name for agent in all_agents]
        await broadcast_message(
            session,
            {
                "type": "system",
                "data": {
                    "message": f"🎲 라운드 {round_num} 발언 순서: {' → '.join(speaker_names)}"
                },
            },
        )
        await asyncio.sleep(2)

        for idx, (team, agent) in enumerate(all_agents):
            if idx > 0 and idx % 2 == 0 and idx < len(all_agents) - 1:
                await asyncio.sleep(2)

                organizer_prompt = f"{korean_context}지금까지 {speaker_names[idx - 2]}와 {speaker_names[idx - 1]}의 발언을 간단히 정리하고, 다음 발언자에게 논점을 제시해주세요."

                organizer_interjection = await broadcast_argument_streaming(
                    session,
                    session.organizer,
                    controller.config.topic,
                    controller.debate_history,
                    round_num,
                    organizer_prompt,
                )
                await asyncio.sleep(2)

            await broadcast_message(
                session,
                {"type": "typing", "data": {"agent_name": agent.name, "stance": team}},
            )

            await asyncio.sleep(2)

            if idx == 0:
                prompt = f"{korean_context}라운드 {round_num}의 첫 발언자입니다. '{controller.config.topic}'에 대한 당신의 입장을 명확히 제시하세요."
            else:
                last_speaker = all_agents[idx - 1][1].name
                prompt = f"{korean_context}{last_speaker}의 발언에 이어서, 당신의 관점을 제시하세요. 이전 발언을 고려하여 응답하세요."

            arg = await broadcast_argument_streaming(
                session,
                agent,
                controller.config.topic,
                controller.debate_history,
                round_num,
                prompt,
            )

            controller.debate_history.append(arg)

            await asyncio.sleep(3)

        # Round evaluation
        try:
            round_arguments = [
                arg
                for arg in controller.debate_history
                if arg.round_number == round_num
            ]

            support_args = [
                arg for arg in round_arguments if arg.stance == DebateStance.SUPPORT
            ]
            oppose_args = [
                arg for arg in round_arguments if arg.stance == DebateStance.OPPOSE
            ]

            support_score = 0.5
            oppose_score = 0.5

            if support_args:
                support_score = sum(arg.quality_score for arg in support_args) / len(
                    support_args
                )
            if oppose_args:
                oppose_score = sum(arg.quality_score for arg in oppose_args) / len(
                    oppose_args
                )

            support_score += random.uniform(-0.02, 0.02)
            oppose_score += random.uniform(-0.02, 0.02)

        except Exception as e:
            logger.error("Evaluation error: %s", e)
            support_score = 0.6 + random.uniform(-0.05, 0.05)
            oppose_score = 0.6 + random.uniform(-0.05, 0.05)

        await broadcast_evaluation(
            session,
            {
                "support_team": min(max(support_score, 0.3), 0.95),
                "oppose_team": min(max(oppose_score, 0.3), 0.95),
            },
        )

        await broadcast_message(
            session, {"type": "round_complete", "data": {"round": round_num}}
        )

        # Organizer round summary
        await asyncio.sleep(2)

        await broadcast_message(
            session,
            {
                "type": "system",
                "data": {
                    "message": f"🎯 진행자가 라운드 {round_num} 종합 정리를 시작합니다..."
                },
            },
        )

        round_args = [
            arg for arg in controller.debate_history if arg.round_number == round_num
        ]
        round_analysis_text = await analyze_current_round(
            round_args, round_num, controller.config.topic
        )

        round_summary_prompt = f"""{korean_context}라운드 {round_num} 종합 정리:

**📊 이번 라운드 분석:**
{round_analysis_text}

**다음 구조로 라운드를 요약해주세요:**

## 🔄 라운드 {round_num} 종합 요약

### 📌 주요 논점 및 쟁점
- **지지측 핵심 주장**:
- **반대측 핵심 주장**:
- **새로 제기된 쟁점**:

### ⚖️ 라운드 평가
- **가장 강력한 논증**:
- **논리적 발전 정도**:
- **상대방 반박 효과**:

### 🔮 다음 라운드 전망
- **예상 논점**:
- **주목할 포인트**:

간결하고 정확한 분석을 제공해주세요."""

        organizer_summary = await broadcast_argument_streaming(
            session,
            session.organizer,
            controller.config.topic,
            controller.debate_history,
            round_num,
            round_summary_prompt,
        )

        await asyncio.sleep(3)

        if round_num < controller.config.max_rounds:
            await broadcast_message(
                session,
                {
                    "type": "system",
                    "data": {
                        "message": f"🔄 잠시 후 라운드 {round_num + 1}이 시작됩니다..."
                    },
                },
            )
            await asyncio.sleep(2)

    # Debate complete - organizer final verdict
    await asyncio.sleep(2)
    winner = "support" if support_score > oppose_score else "oppose"

    await broadcast_message(
        session,
        {
            "type": "system",
            "data": {
                "message": "🏆 토론 종료! 진행자가 전체 토론을 종합하여 최종 결론을 발표합니다..."
            },
        },
    )
    await asyncio.sleep(1)

    await broadcast_message(
        session,
        {
            "type": "system",
            "data": {"message": "📊 토론 데이터를 종합 분석 중입니다..."},
        },
    )
    await asyncio.sleep(2)

    comprehensive_analysis = await perform_comprehensive_debate_analysis(
        controller.debate_history,
        controller.config.topic,
        controller.config.max_rounds,
    )

    detailed_prompt = f"""{korean_context}토론 최종 종합 평가:

**📊 토론 개요:**
- 주제: {controller.config.topic}
- 총 라운드: {controller.config.max_rounds}
- 현재 점수: 지지팀 {support_score:.2f} vs 반대팀 {oppose_score:.2f}

**🔍 분석 결과:**
{comprehensive_analysis["statistics"]}

{comprehensive_analysis["team_analysis"]}

{comprehensive_analysis["dimension_scores"]}

**📋 다음 구조로 간결하고 명확한 최종 평가를 작성해주세요 (총 800자 이내):**

## 🏆 토론 최종 결론

### 1️⃣ 핵심 논점 요약 (200자)
- **지지측**: [핵심 주장 1-2문장]
- **반대측**: [핵심 주장 1-2문장]

### 2️⃣ 승부 판정 (200자)
- **승리팀**: [지지측/반대측]
- **승리 근거**: [주요 이유 2가지]
- **최종 점수**: 지지측 ___점 vs 반대측 ___점

### 3️⃣ 토론 평가 (200자)
- **전체 수준**: [높음/보통/낮음]
- **가장 인상적인 점**: [1문장]
- **아쉬운 점**: [1문장]

### 4️⃣ 마무리 의견 (200자)
- **이 토론의 의의**: [1-2문장]
- **향후 논의 방향**: [1-2문장]

**요구사항**: 간결하고 명확하게, 핵심만 담아 800자 이내로 작성해주세요."""

    organizer_conclusion = await broadcast_argument_streaming(
        session,
        session.organizer,
        controller.config.topic,
        controller.debate_history,
        controller.config.max_rounds + 1,
        detailed_prompt,
    )
    await asyncio.sleep(3)

    await broadcast_message(
        session,
        {
            "type": "debate_complete",
            "data": {
                "winner": winner,
                "support_score": support_score,
                "oppose_score": oppose_score,
            },
        },
    )
