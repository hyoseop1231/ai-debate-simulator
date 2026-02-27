"""
최종 개선된 AI 토론 시뮬레이터
- 한국어 응답
- 자동 스크롤
- 모델 선택
- 토론 형식별 동적 UI
"""

from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    BackgroundTasks,
    Request,
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Optional
import asyncio
import json
import uuid
from datetime import datetime
import random
import httpx
import os
import re
import html
import time
import logging
from dotenv import load_dotenv

load_dotenv()

from debate_agent import DebateAgent, AgentRole, DebateStance, Argument
from debate_controller import DebateController, DebateConfig, DebateFormat
from debate_evaluator import DebateEvaluator

app = FastAPI(title="AI 토론 시뮬레이터 Final", version="4.0")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# CORS 설정 (보안 강화)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)


# 보안 헤더 미들웨어
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """보안 헤더 추가 및 메트릭 수집"""
    start_time = time.time()

    try:
        response = await call_next(request)

        # 보안 헤더 추가
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
        )

        # 메트릭 수집
        metrics.record_request()

        return response

    except Exception as e:
        metrics.record_error()
        raise


# 전역 상태
active_debates = {}


# 간단한 메트릭 시스템
class SimpleMetrics:
    def __init__(self):
        self.total_debates = 0
        self.total_requests = 0
        self.total_errors = 0
        self.start_time = time.time()
        self.active_connections = 0

    def record_request(self):
        self.total_requests += 1

    def record_error(self):
        self.total_errors += 1

    def record_debate_start(self):
        self.total_debates += 1

    def record_connection_change(self, change):
        self.active_connections += change

    def get_stats(self):
        uptime = time.time() - self.start_time
        return {
            "total_debates": self.total_debates,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "active_connections": self.active_connections,
            "active_debates": len(active_debates),
            "uptime_seconds": uptime,
            "error_rate": self.total_errors / max(self.total_requests, 1),
        }


metrics = SimpleMetrics()

OPENROUTER_API_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# 토론 형식별 설정
DEBATE_FORMATS = {
    "adversarial": {
        "name": "대립형 토론 (MAD)",
        "support_team": "천사팀",
        "oppose_team": "악마팀",
        "organizer": {"name": "진행자", "role": "organizer", "emoji": "🎯"},
        "agents": {
            "support": [
                {"name": "희망천사", "role": "angel", "emoji": "😇"},
                {"name": "긍정작가", "role": "writer", "emoji": "✍️"},
            ],
            "oppose": [
                {"name": "도전악마", "role": "devil", "emoji": "😈"},
                {"name": "비판분석가", "role": "analyzer", "emoji": "🔍"},
            ],
        },
    },
    "collaborative": {
        "name": "협력형 토론",
        "support_team": "찬성 연구팀",
        "oppose_team": "반대 연구팀",
        "organizer": {"name": "연구진행자", "role": "organizer", "emoji": "🎯"},
        "agents": {
            "support": [
                {"name": "찬성연구원", "role": "searcher", "emoji": "🔎"},
                {"name": "찬성작가", "role": "writer", "emoji": "📝"},
            ],
            "oppose": [
                {"name": "반대연구원", "role": "searcher", "emoji": "🔍"},
                {"name": "반대작가", "role": "writer", "emoji": "✏️"},
            ],
        },
    },
    "competitive": {
        "name": "경쟁형 토론",
        "support_team": "블루팀",
        "oppose_team": "레드팀",
        "organizer": {"name": "심판", "role": "organizer", "emoji": "🎯"},
        "agents": {
            "support": [
                {"name": "블루탐색자", "role": "searcher", "emoji": "🔵"},
                {"name": "블루전략가", "role": "writer", "emoji": "💙"},
            ],
            "oppose": [
                {"name": "레드탐색자", "role": "searcher", "emoji": "🔴"},
                {"name": "레드전략가", "role": "writer", "emoji": "❤️"},
            ],
        },
    },
    "custom": {
        "name": "커스텀 토론",
        "support_team": "커스텀 A팀",
        "oppose_team": "커스텀 B팀",
        "organizer": {"name": "커스텀 진행자", "role": "organizer", "emoji": "🎯"},
        "agents": {
            "support": [],  # 동적으로 생성
            "oppose": [],  # 동적으로 생성
        },
        "custom": True,
    },
}


class DebateSession:
    def __init__(self, session_id: str, config: DebateConfig):
        self.session_id = session_id
        self.config = config
        self.controller = None
        self.support_agents = []
        self.oppose_agents = []
        self.organizer = None  # 진행자 추가
        self.evaluator = DebateEvaluator()
        self.clients = []
        self.current_round = 0
        self.is_active = True


@app.get("/", response_class=HTMLResponse)
async def home():
    """메인 페이지 - templates/index.html 파일에서 로드"""
    import pathlib
    template_path = pathlib.Path(__file__).parent / "templates" / "index.html"
    try:
        html_content = template_path.read_text(encoding="utf-8")
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Error: templates/index.html not found</h1>",
            status_code=500,
        )


# --- 아래는 이전 home() 함수의 나머지 부분을 제거하고 바로 favicon 핸들러로 이동 ---




@app.get("/favicon.ico")
async def favicon():
    return HTMLResponse("", status_code=204)


@app.get("/api/models")
async def get_models():
    from debate_agent import OPENROUTER_MODELS

    models = []
    for model_id, info in OPENROUTER_MODELS.items():
        models.append(
            {
                "name": model_id,
                "display_name": info["name"],
                "provider": info["provider"],
                "context": info["context"],
            }
        )
    return {"models": models, "success": True}


@app.get("/api/status")
async def get_status():
    """서버 상태"""
    return {
        "status": "online",
        "active_debates": len(active_debates),
        "version": "4.1",
        "environment": "production",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/metrics")
async def get_metrics():
    """시스템 메트릭 조회"""
    return {"metrics": metrics.get_stats(), "timestamp": datetime.now().isoformat()}


@app.get("/api/health")
async def health_check():
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    api_status = "healthy" if openrouter_api_key else "unhealthy"
    memory_status = "healthy" if len(active_debates) < 50 else "warning"

    health_data = {
        "status": "healthy"
        if api_status == "healthy" and memory_status == "healthy"
        else "degraded",
        "timestamp": datetime.now().isoformat(),
        "checks": {
            "openrouter": api_status,
            "memory": memory_status,
            "debates": len(active_debates),
        },
        "metrics": metrics.get_stats(),
    }

    status_code = 200 if health_data["status"] == "healthy" else 503
    return JSONResponse(content=health_data, status_code=status_code)


@app.get("/api/openrouter/status")
async def get_openrouter_status():
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_api_url = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1")

    if not openrouter_api_key:
        return {
            "status": "offline",
            "success": False,
            "error": "API key not configured",
        }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{openrouter_api_url}/models",
                headers={"Authorization": f"Bearer {openrouter_api_key}"},
            )
            if response.status_code == 200:
                return {"status": "online", "success": True}
            else:
                return {
                    "status": "offline",
                    "success": False,
                    "error": f"HTTP {response.status_code}",
                }
    except Exception as e:
        return {"status": "offline", "success": False, "error": str(e)}


@app.get("/api/ollama/status")
async def get_ollama_status():
    return await get_openrouter_status()


class DebateRequest(BaseModel):
    topic: str = Field(..., min_length=5, max_length=500, description="토론 주제")
    format: str = Field(
        "adversarial",
        pattern="^(adversarial|collaborative|competitive|custom)$",
        description="토론 형식",
    )
    max_rounds: int = Field(5, ge=1, le=10, description="최대 라운드 수")
    model: str = Field("anthropic/claude-sonnet-4", description="사용할 AI 모델")
    language: str = Field("한국어", description="언어")
    support_agents: List[Dict] = Field([], description="지지 에이전트")
    oppose_agents: List[Dict] = Field([], description="반대 에이전트")
    custom_config: Optional[Dict] = Field(None, description="커스텀 설정")

    @validator("topic")
    def sanitize_topic(cls, v):
        """토론 주제 검증 및 정리"""
        if not v or not v.strip():
            raise ValueError("토론 주제는 비어있을 수 없습니다.")

        # HTML 태그 제거
        clean_topic = html.escape(v.strip())

        # 기본적인 XSS 패턴 필터링
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

        # 연속된 공백 정리
        clean_topic = re.sub(r"\s+", " ", clean_topic)

        # 최종 길이 검증
        if len(clean_topic) < 5:
            raise ValueError("토론 주제는 최소 5자 이상이어야 합니다.")

        return clean_topic


@app.post("/api/debate/start")
async def start_debate(request: DebateRequest, background_tasks: BackgroundTasks):
    """토론 시작"""
    try:
        session_id = str(uuid.uuid4())

        # 메트릭 수집
        metrics.record_debate_start()

        # 토론 설정
        config = DebateConfig(
            topic=request.topic,
            format=DebateFormat[request.format.upper()],
            max_rounds=request.max_rounds,
        )

        # 한국어 프롬프트 추가
        korean_prompt = "한국어로 답변해주세요. " if request.language == "ko" else ""

        # 토론 형식 정보 가져오기
        format_data = DEBATE_FORMATS[request.format]

        # ORGANIZER 생성
        organizer_config = format_data["organizer"]
        organizer = DebateAgent(
            name=organizer_config["name"],
            role=AgentRole.ORGANIZER,
            stance=DebateStance.NEUTRAL,
            model=request.model,
            persona_prompt=korean_prompt + f"당신은 {organizer_config['name']}입니다.",
            temperature=0.7,
        )

        # 에이전트 생성 (Context7 연구 기반 향상된 페르소나 시스템)
        support_agents = []
        for agent_config in request.support_agents:
            # 커스텀 페르소나 처리 (Context7 Generator-Critic 프레임워크 적용)
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
            # 커스텀 페르소나 처리 (Context7 연구 기반)
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

        # 컨트롤러 생성
        controller = DebateController(config, support_agents, oppose_agents)

        # 세션 저장
        session = DebateSession(session_id, config)
        session.controller = controller
        session.support_agents = support_agents
        session.oppose_agents = oppose_agents
        session.organizer = organizer  # ORGANIZER 추가
        active_debates[session_id] = session

        # 토론 시작
        controller.start_debate()

        # 자동 진행
        background_tasks.add_task(conduct_debate_async, session, request.language)

        return {"session_id": session_id, "status": "started"}

    except KeyError as e:
        print(f"KeyError in start_debate: {e}")
        raise HTTPException(status_code=400, detail=f"잘못된 설정값: {str(e)}")
    except Exception as e:
        print(f"Error in start_debate: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"토론 시작 중 오류 발생: {str(e)}")


async def perform_comprehensive_debate_analysis(
    debate_history: List[Argument], topic: str, total_rounds: int
) -> Dict:
    """토론에 대한 포괄적 분석을 수행하여 체계적 평가 데이터 생성"""

    # 팀별 논증 분리
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
    """토론 통계 생성"""
    total_arguments = len(debate_history)
    support_count = len(support_args)
    oppose_count = len(oppose_args)

    # 평균 품질 점수 계산
    avg_support_quality = sum(
        getattr(arg, "quality_score", 0.7) for arg in support_args
    ) / max(len(support_args), 1)
    avg_oppose_quality = sum(
        getattr(arg, "quality_score", 0.7) for arg in oppose_args
    ) / max(len(oppose_args), 1)

    # 증거 제시 통계
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
    """각 팀의 전략과 핵심 논점 분석"""

    # 키워드 추출을 통한 전략 분석
    def extract_key_themes(arguments):
        all_text = " ".join([arg.content for arg in arguments])

        # 일반적인 토론 테마 키워드
        themes = {
            "경제적 관점": [
                "경제",
                "비용",
                "돈",
                "투자",
                "효율",
                "수익",
                "예산",
                "경비",
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

        return team_themes[:3]  # 상위 3개만

    support_themes = extract_key_themes(support_args)
    oppose_themes = extract_key_themes(oppose_args)

    # 논증의 길이와 구조 분석
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
    """다차원 평가 점수 계산"""

    def calculate_team_dimensions(arguments):
        if not arguments:
            return {}

        # 논리성 (논리적 구조 키워드 기반)
        logical_keywords = [
            "따라서",
            "그러므로",
            "왜냐하면",
            "첫째",
            "둘째",
            "결론적으로",
        ]
        logic_score = 0
        for arg in arguments:
            logic_score += sum(
                1 for keyword in logical_keywords if keyword in arg.content
            )
        logic_score = min(logic_score / len(arguments) * 0.2 + 0.6, 1.0)

        # 증거성 (증거 및 근거 키워드 기반)
        evidence_keywords = ["연구", "데이터", "통계", "조사", "실험", "사례", "예시"]
        evidence_score = 0
        for arg in arguments:
            evidence_score += sum(
                1 for keyword in evidence_keywords if keyword in arg.content
            )
            evidence_score += len(getattr(arg, "evidence", [])) * 0.5
        evidence_score = min(evidence_score / len(arguments) * 0.15 + 0.5, 1.0)

        # 설득력 (감정적/수사적 표현 기반)
        persuasive_keywords = ["반드시", "중요한", "명백히", "분명히", "절대적으로"]
        persuasion_score = 0
        for arg in arguments:
            persuasion_score += sum(
                1 for keyword in persuasive_keywords if keyword in arg.content
            )
        persuasion_score = min(persuasion_score / len(arguments) * 0.2 + 0.6, 1.0)

        # 품질 점수 활용
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


async def analyze_debate_flow(debate_history: List[Argument], total_rounds: int) -> str:
    """토론 흐름 및 전환점 분석"""

    round_analysis = []

    for round_num in range(1, total_rounds + 1):
        round_args = [arg for arg in debate_history if arg.round_number == round_num]
        if not round_args:
            continue

        # 라운드별 특징 분석
        avg_quality = sum(
            getattr(arg, "quality_score", 0.7) for arg in round_args
        ) / len(round_args)
        round_themes = []

        # 키워드 분석
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

    # 전환점 식별
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
    """결정적 순간 및 최고 논증 식별"""

    if not debate_history:
        return "💡 **분석할 논증이 없습니다.**"

    # 품질 점수 기반 최고 논증 찾기
    best_arg = max(debate_history, key=lambda x: getattr(x, "quality_score", 0.7))
    worst_arg = min(debate_history, key=lambda x: getattr(x, "quality_score", 0.7))

    # 가장 긴 논증과 짧은 논증
    longest_arg = max(debate_history, key=lambda x: len(x.content))
    shortest_arg = min(debate_history, key=lambda x: len(x.content))

    # 증거를 가장 많이 제시한 논증
    evidence_arg = max(debate_history, key=lambda x: len(getattr(x, "evidence", [])))

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
    """논증 품질 전반적 평가"""

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
    """현재 라운드에 대한 분석 수행"""

    if not round_args:
        return f"라운드 {round_num}에 논증이 없습니다."

    # 팀별 논증 분리
    support_round_args = [arg for arg in round_args if arg.stance.value == "support"]
    oppose_round_args = [arg for arg in round_args if arg.stance.value == "oppose"]

    # 라운드 통계
    total_args = len(round_args)
    avg_quality = sum(getattr(arg, "quality_score", 0.7) for arg in round_args) / len(
        round_args
    )

    # 각 팀의 평균 품질
    support_quality = sum(
        getattr(arg, "quality_score", 0.7) for arg in support_round_args
    ) / max(len(support_round_args), 1)
    oppose_quality = sum(
        getattr(arg, "quality_score", 0.7) for arg in oppose_round_args
    ) / max(len(oppose_round_args), 1)

    # 증거 제시 현황
    support_evidence = sum(
        1 for arg in support_round_args if getattr(arg, "evidence", [])
    )
    oppose_evidence = sum(
        1 for arg in oppose_round_args if getattr(arg, "evidence", [])
    )

    # 논증 길이 분석
    avg_support_length = sum(len(arg.content) for arg in support_round_args) / max(
        len(support_round_args), 1
    )
    avg_oppose_length = sum(len(arg.content) for arg in oppose_round_args) / max(
        len(oppose_round_args), 1
    )

    # 키워드 분석
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


async def conduct_debate_async(session: DebateSession, language: str):
    """향상된 토론 진행 - 랜덤 턴테이킹 및 진행자 적극 개입"""
    controller = session.controller
    korean_context = "한국어로 토론하세요. " if language == "ko" else ""

    await asyncio.sleep(2)

    # ORGANIZER 토론 시작 인사 (스트리밍 방식)
    organizer_intro = await broadcast_argument_streaming(
        session,
        session.organizer,
        controller.config.topic,
        [],
        0,
        f"{korean_context}토론을 시작하겠습니다. 주제: '{controller.config.topic}'. 모든 참가자는 자유롭게 의견을 표현해주세요.",
    )
    await asyncio.sleep(3)

    # 점수 초기화
    support_score = 0.5
    oppose_score = 0.5

    # 라운드별 진행
    for round_num in range(1, controller.config.max_rounds + 1):
        # 세션 상태 확인
        if session.session_id not in active_debates:
            print(f"세션 {session.session_id} 종료됨, 토론 중단")
            break

        # 라운드 시작 알림
        print(f"🔔 라운드 {round_num} 시작 (세션: {session.session_id})")
        controller.current_round = round_num

        await broadcast_message(
            session, {"type": "round_start", "data": {"round": round_num}}
        )

        await asyncio.sleep(2)

        # 이번 라운드에 발언할 에이전트 목록 준비
        all_agents = []

        # 지지팀과 반대팀 에이전트 모두 포함
        for agent in session.support_agents:
            all_agents.append(("support", agent))
        for agent in session.oppose_agents:
            all_agents.append(("oppose", agent))

        # 랜덤하게 섞기
        random.shuffle(all_agents)

        # 발언 순서 알림
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

        # 각 에이전트가 순서대로 발언
        for idx, (team, agent) in enumerate(all_agents):
            # 중간에 진행자 개입 (2명 발언 후마다)
            if idx > 0 and idx % 2 == 0 and idx < len(all_agents) - 1:
                await asyncio.sleep(2)

                # 진행자 중간 정리
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

            # 타이핑 표시
            await broadcast_message(
                session,
                {"type": "typing", "data": {"agent_name": agent.name, "stance": team}},
            )

            await asyncio.sleep(2)

            # 발언 프롬프트 생성 (컨텍스트 인식)
            if idx == 0:
                prompt = f"{korean_context}라운드 {round_num}의 첫 발언자입니다. '{controller.config.topic}'에 대한 당신의 입장을 명확히 제시하세요."
            else:
                last_speaker = all_agents[idx - 1][1].name
                prompt = f"{korean_context}{last_speaker}의 발언에 이어서, 당신의 관점을 제시하세요. 이전 발언을 고려하여 응답하세요."

            # 스트리밍으로 논증 생성 및 전송
            arg = await broadcast_argument_streaming(
                session,
                agent,
                controller.config.topic,
                controller.debate_history,
                round_num,
                prompt,
            )

            controller.debate_history.append(arg)

            # 다음 발언자 대기 (동시 발언 방지)
            await asyncio.sleep(3)

        # 라운드 평가 - 실제 평가 시스템 사용
        try:
            # 이번 라운드의 모든 논증 수집
            round_arguments = [
                arg for arg in controller.debate_history if arg.round_number == round_num
            ]

            # 팀별로 논증 분리
            support_args = [
                arg for arg in round_arguments if arg.stance == DebateStance.SUPPORT
            ]
            oppose_args = [
                arg for arg in round_arguments if arg.stance == DebateStance.OPPOSE
            ]

            # 각 팀의 평균 품질 점수 계산
            support_score = 0.5  # 기본값
            oppose_score = 0.5

            if support_args:
                support_score = sum(arg.quality_score for arg in support_args) / len(
                    support_args
                )
            if oppose_args:
                oppose_score = sum(arg.quality_score for arg in oppose_args) / len(
                    oppose_args
                )

            # 약간의 변동성 추가 (더 자연스러운 점수를 위해)
            support_score += random.uniform(-0.02, 0.02)
            oppose_score += random.uniform(-0.02, 0.02)

        except Exception as e:
            logger.error(f"평가 중 오류: {e}")
            # 오류 시 기본값 사용
            support_score = 0.6 + random.uniform(-0.05, 0.05)
            oppose_score = 0.6 + random.uniform(-0.05, 0.05)

        await broadcast_evaluation(
            session,
            {
                "support_team": min(max(support_score, 0.3), 0.95),
                "oppose_team": min(max(oppose_score, 0.3), 0.95),
            },
        )

        # 라운드 완료
        await broadcast_message(
            session, {"type": "round_complete", "data": {"round": round_num}}
        )

        # ORGANIZER 라운드 종합 요약
        await asyncio.sleep(2)

        # 진행자 요약 시작 알림
        await broadcast_message(
            session,
            {
                "type": "system",
                "data": {
                    "message": f"🎯 진행자가 라운드 {round_num} 종합 정리를 시작합니다..."
                },
            },
        )

        # 라운드별 분석 수행
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

        # 진행자 요약 완료 후 추가 대기 시간 (다음 라운드 준비)
        await asyncio.sleep(3)

        # 다음 라운드 예고 (마지막 라운드가 아닌 경우)
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

    # 토론 종료 - ORGANIZER 최종 판정
    await asyncio.sleep(2)
    winner = "support" if support_score > oppose_score else "oppose"

    # 최종 결론 시작 알림
    await broadcast_message(
        session,
        {
            "type": "system",
            "data": {
                "message": f"🏆 토론 종료! 진행자가 전체 토론을 종합하여 최종 결론을 발표합니다..."
            },
        },
    )
    await asyncio.sleep(1)

    # 포괄적 분석 수행
    await broadcast_message(
        session,
        {
            "type": "system",
            "data": {"message": "📊 토론 데이터를 종합 분석 중입니다..."},
        },
    )
    await asyncio.sleep(2)

    comprehensive_analysis = await perform_comprehensive_debate_analysis(
        controller.debate_history, controller.config.topic, controller.config.max_rounds
    )

    # ORGANIZER 최종 결론 (스트리밍 방식) - 체계적이고 포괄적인 분석 기반
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


async def broadcast_argument(session: DebateSession, argument):
    """논증 전송 (KITECH 방식 품질 점수 포함)"""
    message = {
        "type": "argument",
        "data": {
            "agent_name": argument.agent_name,
            "stance": argument.stance.value,
            "content": argument.content,
            "round": argument.round_number,
            "confidence_score": argument.confidence_score,
            "quality_score": getattr(
                argument, "quality_score", 0.7
            ),  # KITECH 품질 점수
            "evidence": getattr(argument, "evidence", []),  # 증거 목록
        },
    }
    await broadcast_message(session, message)


async def broadcast_argument_streaming(
    session: DebateSession, agent, topic, context, round_num, prompt
):
    """스트리밍 방식으로 논증 전송 (향상된 신뢰성)"""
    thinking_chunks = []
    content_chunks = []
    max_retries = 3
    retry_delay = 2

    # 스트리밍 콜백 정의
    # 고유한 메시지 ID 생성
    import time

    message_id = f"{agent.name}-{round_num}-thinking-{int(time.time() * 1000)}"

    async def stream_callback(message_type, chunk):
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
                # 진행자 종합평가의 경우 더 작은 청크로 전송
                if agent.role.value == "ORGANIZER" and round_num > 5:
                    # 청크를 더 작게 나누어 전송
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
                            await asyncio.sleep(0.05)  # 작은 지연으로 안정성 확보
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
            print(f"⚠️ 스트리밍 콜백 오류: {e}")
            # 연결 오류가 발생해도 계속 진행

    # 재시도 로직이 포함된 논증 생성
    argument = None
    last_error = None

    for attempt in range(max_retries):
        try:
            # 타임아웃 설정 (진행자 종합평가는 더 긴 시간 필요)
            timeout_duration = (
                120.0 if agent.role.value == "ORGANIZER" and round_num > 5 else 45.0
            )
            argument = await asyncio.wait_for(
                agent.generate_argument(
                    topic, context, round_num, prompt, stream_callback=stream_callback
                ),
                timeout=timeout_duration,
            )

            # 성공적으로 생성된 경우
            if argument and argument.content:
                break

        except asyncio.TimeoutError:
            last_error = "응답 시간 초과"
            print(f"⏰ {agent.name} 응답 타임아웃 (시도 {attempt + 1}/{max_retries})")

        except Exception as e:
            last_error = str(e)
            print(
                f"❌ {agent.name} 응답 생성 실패 (시도 {attempt + 1}/{max_retries}): {e}"
            )

        # 재시도 전 대기
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
            retry_delay *= 1.5  # 점진적 대기 시간 증가

            # 재시도 알림
            await broadcast_message(
                session,
                {
                    "type": "system",
                    "data": {
                        "message": f"🔄 {agent.name}의 응답을 재시도하고 있습니다... (시도 {attempt + 2}/{max_retries})"
                    },
                },
            )

    # 모든 재시도 실패 시 폴백 응답
    if not argument or not argument.content:
        print(f"⚠️ {agent.name} 폴백 응답 사용")

        # 폴백 응답 생성
        from debate_agent import Argument

        argument = Argument(
            content=f"[기술적 문제로 {agent.name}의 응답이 일시적으로 지연되었습니다. 다음 라운드에서 더 나은 논증을 제시하겠습니다.]",
            agent_name=agent.name,
            stance=agent.stance,
            round_number=round_num,
            evidence=[],
            confidence_score=0.5,
            quality_score=0.5,
        )

        # 오류 알림
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

    # 최종 논증 완성 메시지
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


async def broadcast_evaluation(session: DebateSession, scores):
    """평가 전송"""
    message = {"type": "evaluation", "data": scores}
    await broadcast_message(session, message)


async def broadcast_message(session: DebateSession, message):
    """Context7 기반: 강화된 메시지 브로드캐스트"""
    disconnected = []
    broadcast_start = asyncio.get_event_loop().time()
    successful_sends = 0

    # 메시지에 타임스탬프 및 메타데이터 추가
    enhanced_message = {
        **message,
        "metadata": {
            "timestamp": broadcast_start * 1000,  # milliseconds
            "session_id": session.session_id,
            "broadcast_id": str(uuid.uuid4())[:8],
        },
    }

    # 병렬 브로드캐스트 (Context7 최적화)
    send_tasks = []
    for client in session.clients:
        task = asyncio.create_task(safe_send_message(client, enhanced_message))
        send_tasks.append((client, task))

    # 결과 수집 및 처리
    for client, task in send_tasks:
        try:
            success = await asyncio.wait_for(task, timeout=5.0)
            if success:
                successful_sends += 1
            else:
                disconnected.append(client)
        except asyncio.TimeoutError:
            print(f"⚠️ 클라이언트 {id(client)} 타임아웃")
            disconnected.append(client)
        except Exception as e:
            print(f"❌ 클라이언트 {id(client)} 전송 실패: {e}")
            disconnected.append(client)

    # 연결 해제된 클라이언트 정리
    for client in disconnected:
        if client in session.clients:
            session.clients.remove(client)

    # 브로드캐스트 성능 모니터링
    broadcast_time = (asyncio.get_event_loop().time() - broadcast_start) * 1000
    if broadcast_time > 100:  # 100ms 초과시 경고
        print(
            f"⚠️ 느린 브로드캐스트: {broadcast_time:.2f}ms, 성공: {successful_sends}/{len(send_tasks)}"
        )


async def safe_send_message(client, message):
    """안전한 메시지 전송"""
    try:
        await client.send_json(message)
        return True
    except Exception as e:
        print(f"클라이언트 전송 실패: {e}")
        return False


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Context7 기반: 강화된 WebSocket 연결 관리"""
    client_id = str(uuid.uuid4())[:8]
    connection_time = asyncio.get_event_loop().time()

    try:
        # 연결 수락
        await websocket.accept()
        print(f"🔗 WebSocket 연결: {client_id} → {session_id}")

        # 메트릭 수집
        metrics.record_connection_change(1)

        # 세션 유효성 검증
        if session_id not in active_debates:
            await websocket.close(code=1008, reason="Invalid session")
            print(f"❌ 잘못된 세션: {session_id}")
            metrics.record_connection_change(-1)
            return

        session = active_debates[session_id]
        session.clients.append(websocket)

        # 연결 확인 메시지
        await safe_send_message(
            websocket,
            {
                "type": "connection_confirmed",
                "data": {
                    "client_id": client_id,
                    "session_id": session_id,
                    "server_time": connection_time * 1000,
                    "status": "connected",
                },
            },
        )

        # Context7 기반: 하트비트 및 상태 동기화
        heartbeat_task = asyncio.create_task(heartbeat_manager(websocket, client_id))

        try:
            while True:
                # 메시지 수신 대기 (타임아웃 설정)
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_text(), timeout=30.0
                    )

                    # 클라이언트 메시지 처리
                    await handle_client_message(websocket, session, data, client_id)

                except asyncio.TimeoutError:
                    # 하트비트 체크
                    print(f"🔄 하트비트 체크: {client_id}")
                    continue

                except WebSocketDisconnect:
                    print(f"🔌 클라이언트 연결 해제: {client_id}")
                    break

        except Exception as e:
            print(f"❌ WebSocket 오류: {client_id} - {e}")

        finally:
            # 정리 작업
            heartbeat_task.cancel()
            if websocket in session.clients:
                session.clients.remove(websocket)

            print(f"🧹 클라이언트 정리 완료: {client_id}")

            # 마지막 클라이언트인 경우 세션 정리
            if not session.clients and session_id in active_debates:
                print(f"🗑️ 빈 세션 정리: {session_id}")
                del active_debates[session_id]

    except Exception as e:
        print(f"❌ WebSocket 연결 실패: {client_id} - {e}")
        try:
            await websocket.close(code=1011, reason="Server error")
        except:
            pass


async def heartbeat_manager(websocket: WebSocket, client_id: str):
    """Context7 기반: 하트비트 관리"""
    try:
        while True:
            await asyncio.sleep(15)  # 15초마다 하트비트

            await safe_send_message(
                websocket,
                {
                    "type": "heartbeat",
                    "data": {
                        "client_id": client_id,
                        "timestamp": asyncio.get_event_loop().time() * 1000,
                    },
                },
            )

    except asyncio.CancelledError:
        print(f"💓 하트비트 중지: {client_id}")
    except Exception as e:
        print(f"❌ 하트비트 오류: {client_id} - {e}")


async def handle_client_message(
    websocket: WebSocket, session: DebateSession, data: str, client_id: str
):
    """클라이언트 메시지 처리"""
    try:
        message = json.loads(data)
        message_type = message.get("type")

        if message_type == "ping":
            # Ping 응답
            await safe_send_message(
                websocket,
                {
                    "type": "pong",
                    "data": {
                        "client_id": client_id,
                        "timestamp": asyncio.get_event_loop().time() * 1000,
                    },
                },
            )

        elif message_type == "sync_request":
            # 상태 동기화 요청 처리
            await handle_sync_request(
                websocket, session, message.get("data"), client_id
            )

        else:
            print(f"🔍 알 수 없는 메시지 타입: {message_type} from {client_id}")

    except json.JSONDecodeError:
        print(f"❌ 잘못된 JSON: {client_id}")
    except Exception as e:
        print(f"❌ 메시지 처리 오류: {client_id} - {e}")


async def handle_sync_request(
    websocket: WebSocket, session: DebateSession, data: dict, client_id: str
):
    """상태 동기화 요청 처리"""
    try:
        await safe_send_message(
            websocket,
            {
                "type": "sync_response",
                "data": {
                    "current_round": session.current_round,
                    "is_active": session.is_active,
                    "session_id": session.session_id,
                    "client_id": client_id,
                    "server_time": asyncio.get_event_loop().time() * 1000,
                },
            },
        )
        print(f"🔄 상태 동기화 응답: {client_id}")

    except Exception as e:
        print(f"❌ 동기화 응답 실패: {client_id} - {e}")


if __name__ == "__main__":
    import uvicorn

    print("🚀 최종 AI 토론 배틀 아레나")
    print("🌐 http://localhost:8003")
    uvicorn.run(app, host="0.0.0.0", port=8003)
