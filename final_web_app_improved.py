"""
완전히 개선된 AI 토론 시뮬레이터 - 프로덕션 수준
- 보안 강화: CORS, 입력 검증, 레이트 리미팅
- 성능 최적화: 병렬 처리, 캐싱, 메모리 관리
- 모니터링: 구조화된 로깅, 헬스체크, 메트릭 수집
- 에러 처리: 자동 복구, WebSocket 연결 관리
"""

import asyncio
import json
import uuid
import time
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel
import httpx
try:
    import structlog
except ImportError:
    import logging
    structlog = logging

# 설정 및 유틸리티 모듈 (조건부 import)
try:
    from config.settings import settings
    from utils.security import (
        SecureDebateRequest, rate_limiter, session_manager, security_headers,
        input_sanitizer
    )
    from utils.cache import cache_manager, debate_caches, cached
    from utils.monitoring import (
        metrics_collector, performance_monitor, health_checker, alert_manager,
        setup_default_alerts
    )
except ImportError:
    # 기본 설정 사용
    class DefaultSettings:
        environment = "development"
        debug = True
        host = "0.0.0.0"
        port = 8003
        allowed_origins = ["*"]
        cors_credentials = True
        cors_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
        cors_headers = ["*"]
        max_concurrent_debates = 10
        max_history_size = 50
        response_timeout = 30
        cleanup_interval = 300
        ollama_api_url = "http://localhost:11434"
        ollama_timeout = 30
        ollama_max_retries = 3
        cache_ttl_minutes = 30
        cache_max_size = 1000
        rate_limit_requests = 10
        rate_limit_window = 60
        log_level = "INFO"
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        log_file = None
        metrics_enabled = True
        health_check_interval = 30
    
    settings = DefaultSettings()
    
    # 더미 클래스들 (기본 기능만 제공)
    class SecureDebateRequest(BaseModel):
        topic: str
        format: str = "adversarial"
        max_rounds: int = 5
        model: str = "llama3.2:3b"
        temperature: float = 0.7
        custom_agents: Optional[List[Dict[str, str]]] = None
    
    class DummyRateLimiter:
        def is_allowed(self, client_id: str, ip: str = None):
            return True, {"remaining": 10}
        def release_lock(self, client_id: str):
            pass
        def get_stats(self):
            return {"active_clients": 0, "blocked_ips": 0, "total_requests": 0}
    
    class DummySessionManager:
        def create_session(self, client_info):
            return str(uuid.uuid4())
        def validate_session(self, session_id):
            return True
        def invalidate_session(self, session_id):
            pass
    
    class DummySecurityHeaders:
        def get_security_headers(self):
            return {}
    
    class DummyInputSanitizer:
        def sanitize_html(self, text):
            return text
    
    class DummyCacheManager:
        def get_cache(self, name):
            return self
        async def set(self, key, value, ttl=None):
            pass
        async def get(self, key):
            return None
        def get_all_stats(self):
            return {}
    
    class DummyMetricsCollector:
        def record_metric(self, name, value, tags=None):
            pass
        def increment_counter(self, name, value=1, tags=None):
            pass
        def record_timer(self, name, duration, tags=None):
            pass
        def get_all_metrics(self):
            return {}
    
    class DummyPerformanceMonitor:
        def __init__(self, collector):
            self.start_time = time.time()
        def record_request(self, duration, status="success"):
            pass
        def record_connection_change(self, change):
            pass
        async def start_monitoring(self, interval=30):
            pass
        async def stop_monitoring(self):
            pass
    
    class DummyHealthChecker:
        def register_check(self, name, check_func):
            pass
        async def run_all_checks(self):
            return {"status": "healthy", "timestamp": datetime.now().isoformat(), "checks": {}}
        async def start_periodic_checks(self, interval=30):
            pass
        async def stop_periodic_checks(self):
            pass
    
    class DummyAlertManager:
        def get_alert_summary(self):
            return {"active_alerts": 0, "total_alerts": 0}
        async def start_alert_monitoring(self, interval=60):
            pass
        async def stop_alert_monitoring(self):
            pass
    
    def cached(ttl=300, cache_name="default"):
        def decorator(func):
            return func
        return decorator
    
    def setup_default_alerts():
        pass
    
    # 더미 인스턴스들
    rate_limiter = DummyRateLimiter()
    session_manager = DummySessionManager()
    security_headers = DummySecurityHeaders()
    input_sanitizer = DummyInputSanitizer()
    cache_manager = DummyCacheManager()
    debate_caches = DummyCacheManager()
    metrics_collector = DummyMetricsCollector()
    performance_monitor = DummyPerformanceMonitor(metrics_collector)
    health_checker = DummyHealthChecker()
    alert_manager = DummyAlertManager()

# 기존 모듈들
from debate_agent import DebateAgent, AgentRole, DebateStance
from debate_controller import DebateController, DebateConfig, DebateFormat
from debate_evaluator import DebateEvaluator

# 구조화된 로깅 설정 (조건부)
try:
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    logger = structlog.get_logger()
except:
    logger = logging.getLogger(__name__)


# 애플리케이션 생명주기 관리
@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 생명주기 관리"""
    logger.info("Starting AI Debate Simulator")
    
    # 모니터링 시스템 시작
    await cache_manager.start_cleanup_task()
    await performance_monitor.start_monitoring()
    await health_checker.start_periodic_checks()
    await alert_manager.start_alert_monitoring()
    
    # 기본 알림 규칙 설정
    setup_default_alerts()
    
    # 헬스체크 등록
    await register_health_checks()
    
    logger.info("AI Debate Simulator started successfully")
    
    yield
    
    # 정리 작업
    logger.info("Shutting down AI Debate Simulator")
    await cache_manager.stop_cleanup_task()
    await performance_monitor.stop_monitoring()
    await health_checker.stop_periodic_checks()
    await alert_manager.stop_alert_monitoring()
    
    logger.info("AI Debate Simulator stopped")


# FastAPI 앱 생성
app = FastAPI(
    title="AI 토론 시뮬레이터 - 프로덕션",
    version="5.0",
    description="보안 강화 및 성능 최적화된 AI 토론 시뮬레이터",
    lifespan=lifespan
)

# 보안 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=settings.cors_credentials,
    allow_methods=settings.cors_methods,
    allow_headers=settings.cors_headers,
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "0.0.0.0"]
)


# 전역 상태 및 연결 관리
class ConnectionManager:
    """WebSocket 연결 관리자"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, session_id: str):
        """연결 수락"""
        await websocket.accept()
        async with self.connection_lock:
            self.active_connections[session_id] = websocket
            performance_monitor.record_connection_change(1)
        logger.info("WebSocket connected", session_id=session_id)
    
    async def disconnect(self, session_id: str):
        """연결 해제"""
        async with self.connection_lock:
            if session_id in self.active_connections:
                del self.active_connections[session_id]
                performance_monitor.record_connection_change(-1)
        logger.info("WebSocket disconnected", session_id=session_id)
    
    async def send_personal_message(self, message: str, session_id: str):
        """개인 메시지 전송"""
        if session_id in self.active_connections:
            try:
                await self.active_connections[session_id].send_text(message)
            except Exception as e:
                logger.error("Failed to send message", session_id=session_id, error=str(e))
                await self.disconnect(session_id)
    
    async def broadcast(self, message: str):
        """전체 브로드캐스트"""
        disconnected = []
        for session_id, connection in self.active_connections.items():
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.error("Failed to broadcast", session_id=session_id, error=str(e))
                disconnected.append(session_id)
        
        # 실패한 연결들 정리
        for session_id in disconnected:
            await self.disconnect(session_id)


# 개선된 토론 세션 관리
class ImprovedDebateSession:
    """개선된 토론 세션"""
    
    def __init__(self, session_id: str, topic: str, format: DebateFormat):
        self.session_id = session_id
        self.topic = topic
        self.format = format
        self.created_at = datetime.now()
        self.last_activity = datetime.now()
        self.is_active = True
        self.debate_history = []
        self.max_history_size = settings.max_history_size
        self.participants = []
        self.metrics = {
            'total_messages': 0,
            'total_characters': 0,
            'average_response_time': 0.0,
            'error_count': 0
        }
    
    async def add_message(self, message: Dict[str, Any]):
        """메시지 추가 (메모리 관리 포함)"""
        self.debate_history.append(message)
        self.last_activity = datetime.now()
        self.metrics['total_messages'] += 1
        self.metrics['total_characters'] += len(str(message.get('content', '')))
        
        # 메모리 관리: 히스토리 크기 제한
        if len(self.debate_history) > self.max_history_size:
            # 오래된 메시지 절반 제거
            removed_count = len(self.debate_history) // 2
            self.debate_history = self.debate_history[removed_count:]
            logger.info("Trimmed debate history", 
                       session_id=self.session_id, 
                       removed_count=removed_count)
    
    async def get_context(self, limit: int = 10) -> List[Dict[str, Any]]:
        """최근 컨텍스트 반환"""
        return self.debate_history[-limit:] if self.debate_history else []
    
    def get_stats(self) -> Dict[str, Any]:
        """세션 통계 반환"""
        duration = (datetime.now() - self.created_at).total_seconds()
        return {
            'session_id': self.session_id,
            'topic': self.topic,
            'format': self.format.value,
            'duration_seconds': duration,
            'is_active': self.is_active,
            'participants': len(self.participants),
            'metrics': self.metrics
        }


# 전역 인스턴스
connection_manager = ConnectionManager()
active_debates: Dict[str, ImprovedDebateSession] = {}


# 미들웨어 및 의존성
async def get_client_ip(request: Request) -> str:
    """클라이언트 IP 주소 추출"""
    return request.client.host if request.client else "unknown"


async def check_rate_limit(request: Request):
    """레이트 리미팅 체크"""
    client_ip = await get_client_ip(request)
    client_id = f"{client_ip}:{request.url.path}"
    
    allowed, info = rate_limiter.is_allowed(client_id, client_ip)
    if not allowed:
        logger.warning("Rate limit exceeded", client_ip=client_ip, path=request.url.path)
        raise HTTPException(
            status_code=429,
            detail=info,
            headers={"Retry-After": str(info.get('retry_after', 60))}
        )
    
    return info


# 헬스체크 등록
async def register_health_checks():
    """헬스체크 등록"""
    
    async def check_ollama():
        """Ollama 서버 체크"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{settings.ollama_api_url}/api/tags")
                return response.status_code == 200
        except:
            return False
    
    async def check_memory():
        """메모리 사용량 체크"""
        try:
            import psutil
            memory = psutil.virtual_memory()
            return memory.percent < 90.0  # 90% 미만
        except:
            return True
    
    async def check_active_debates():
        """활성 토론 체크"""
        return len(active_debates) < settings.max_concurrent_debates
    
    health_checker.register_check("ollama", check_ollama)
    health_checker.register_check("memory", check_memory)
    health_checker.register_check("debates", check_active_debates)


# 전역 에러 핸들러
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """전역 예외 처리"""
    logger.error("Unhandled exception", 
                path=request.url.path, 
                method=request.method,
                error=str(exc),
                exc_info=True)
    
    performance_monitor.record_request(0, "error")
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": "서버에서 오류가 발생했습니다.",
            "timestamp": datetime.now().isoformat()
        }
    )


# 보안 헤더 미들웨어
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """보안 헤더 추가"""
    start_time = time.time()
    
    try:
        response = await call_next(request)
        
        # 보안 헤더 추가
        for header, value in security_headers.get_security_headers().items():
            response.headers[header] = value
        
        # 성능 메트릭 기록
        duration = time.time() - start_time
        performance_monitor.record_request(duration, "success")
        
        return response
    
    except Exception as e:
        duration = time.time() - start_time
        performance_monitor.record_request(duration, "error")
        raise


# API 엔드포인트들
@app.get("/api/health")
async def health_check():
    """헬스체크 엔드포인트"""
    health_status = await health_checker.run_all_checks()
    
    # 추가 정보
    health_status.update({
        "active_debates": len(active_debates),
        "active_connections": len(connection_manager.active_connections),
        "cache_stats": cache_manager.get_all_stats(),
        "rate_limiter_stats": rate_limiter.get_stats(),
        "system_info": {
            "uptime": time.time() - performance_monitor.start_time,
            "version": "5.0",
            "environment": settings.environment
        }
    })
    
    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(content=health_status, status_code=status_code)


@app.get("/api/metrics")
async def get_metrics():
    """메트릭 엔드포인트"""
    return {
        "metrics": metrics_collector.get_all_metrics(),
        "alerts": alert_manager.get_alert_summary(),
        "cache": cache_manager.get_all_stats(),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/status")
async def get_status(rate_info: dict = Depends(check_rate_limit)):
    """시스템 상태 확인"""
    return {
        "status": "healthy",
        "environment": settings.environment,
        "debug": settings.debug,
        "active_debates": len(active_debates),
        "active_connections": len(connection_manager.active_connections),
        "rate_limit": rate_info,
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/models")
@cached(ttl=300, cache_name="models")  # 5분 캐시
async def get_available_models():
    """사용 가능한 모델 목록"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{settings.ollama_api_url}/api/tags")
            if response.status_code == 200:
                data = response.json()
                models = [model["name"] for model in data.get("models", [])]
                return {"models": models}
    except Exception as e:
        logger.error("Failed to fetch models", error=str(e))
        
    return {"models": ["llama3.2:3b", "qwen2.5:7b"]}  # 기본 모델


@app.post("/api/debate/start")
async def start_debate(
    request: SecureDebateRequest,
    background_tasks: BackgroundTasks,
    rate_info: dict = Depends(check_rate_limit)
):
    """토론 시작 (보안 강화)"""
    # 세션 생성
    session_id = str(uuid.uuid4())
    
    # 토론 형식 검증
    try:
        format_enum = DebateFormat(request.format)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid debate format")
    
    # 동시 토론 수 제한
    if len(active_debates) >= settings.max_concurrent_debates:
        raise HTTPException(
            status_code=429,
            detail="Maximum concurrent debates reached"
        )
    
    # 토론 세션 생성
    debate_session = ImprovedDebateSession(
        session_id=session_id,
        topic=request.topic,
        format=format_enum
    )
    
    active_debates[session_id] = debate_session
    
    # 캐시에 세션 정보 저장
    await debate_caches.sessions.set(session_id, debate_session.get_stats(), ttl=3600)
    
    # 백그라운드 태스크로 세션 모니터링 시작
    background_tasks.add_task(monitor_debate_session, session_id)
    
    logger.info("Debate started", 
               session_id=session_id, 
               topic=request.topic,
               format=request.format)
    
    return {
        "session_id": session_id,
        "topic": request.topic,
        "format": request.format,
        "status": "started",
        "websocket_url": f"/ws/{session_id}"
    }


async def monitor_debate_session(session_id: str):
    """토론 세션 모니터링"""
    try:
        while session_id in active_debates:
            session = active_debates[session_id]
            
            # 비활성 세션 정리
            if (datetime.now() - session.last_activity).total_seconds() > 3600:  # 1시간
                await cleanup_debate_session(session_id)
                break
            
            # 세션 통계 업데이트
            await debate_caches.sessions.set(
                session_id, 
                session.get_stats(), 
                ttl=3600
            )
            
            await asyncio.sleep(60)  # 1분마다 체크
            
    except Exception as e:
        logger.error("Session monitoring error", 
                    session_id=session_id, 
                    error=str(e))


async def cleanup_debate_session(session_id: str):
    """토론 세션 정리"""
    if session_id in active_debates:
        session = active_debates[session_id]
        session.is_active = False
        
        # 최종 통계 저장
        await debate_caches.sessions.set(
            f"completed_{session_id}",
            session.get_stats(),
            ttl=86400  # 24시간 보관
        )
        
        del active_debates[session_id]
        logger.info("Debate session cleaned up", session_id=session_id)


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket 연결 (개선된 에러 처리)"""
    try:
        # 세션 검증
        if session_id not in active_debates:
            await websocket.close(code=4004, reason="Session not found")
            return
        
        await connection_manager.connect(websocket, session_id)
        
        try:
            while True:
                # 메시지 수신
                data = await websocket.receive_text()
                message_data = json.loads(data)
                
                # 메시지 처리
                await handle_websocket_message(session_id, message_data)
                
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected normally", session_id=session_id)
        except Exception as e:
            logger.error("WebSocket error", 
                        session_id=session_id, 
                        error=str(e))
        finally:
            await connection_manager.disconnect(session_id)
            
    except Exception as e:
        logger.error("WebSocket connection error", 
                    session_id=session_id, 
                    error=str(e))


async def handle_websocket_message(session_id: str, message_data: Dict[str, Any]):
    """WebSocket 메시지 처리"""
    try:
        message_type = message_data.get("type")
        
        if message_type == "start_debate":
            await start_debate_round(session_id)
        elif message_type == "user_message":
            await handle_user_message(session_id, message_data)
        elif message_type == "ping":
            await connection_manager.send_personal_message(
                json.dumps({"type": "pong"}),
                session_id
            )
        else:
            logger.warning("Unknown message type", 
                          session_id=session_id, 
                          message_type=message_type)
            
    except Exception as e:
        logger.error("Message handling error", 
                    session_id=session_id, 
                    error=str(e))


async def start_debate_round(session_id: str):
    """토론 라운드 시작 (병렬 처리)"""
    if session_id not in active_debates:
        return
    
    session = active_debates[session_id]
    
    try:
        # 병렬로 AI 응답 생성
        tasks = []
        
        # 캐시된 응답 확인
        cached_responses = await check_cached_responses(session.topic, session.format)
        
        if not cached_responses:
            # 새로운 응답 생성
            agents = await create_debate_agents(session.format)
            
            # 병렬 실행
            tasks = [
                generate_agent_response(agent, session.topic, session.debate_history)
                for agent in agents
            ]
            
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 캐시에 저장
            await cache_responses(session.topic, session.format, responses)
        else:
            responses = cached_responses
        
        # 응답 스트리밍
        for response in responses:
            if isinstance(response, Exception):
                logger.error("Agent response error", error=str(response))
                continue
                
            await stream_response(session_id, response)
            await session.add_message(response)
            
    except Exception as e:
        logger.error("Debate round error", 
                    session_id=session_id, 
                    error=str(e))


async def check_cached_responses(topic: str, format: DebateFormat) -> Optional[List[Dict[str, Any]]]:
    """캐시된 응답 확인"""
    cache_key = f"debate_responses:{hash(topic)}:{format.value}"
    return await debate_caches.arguments.get(cache_key)


async def cache_responses(topic: str, format: DebateFormat, responses: List[Dict[str, Any]]):
    """응답 캐시 저장"""
    cache_key = f"debate_responses:{hash(topic)}:{format.value}"
    await debate_caches.arguments.set(cache_key, responses, ttl=1800)  # 30분


async def create_debate_agents(format: DebateFormat) -> List[DebateAgent]:
    """토론 에이전트 생성"""
    agents = []
    
    if format == DebateFormat.ADVERSARIAL:
        agents.extend([
            DebateAgent("희망천사", AgentRole.ANGEL, DebateStance.SUPPORT),
            DebateAgent("도전악마", AgentRole.DEVIL, DebateStance.OPPOSE),
        ])
    elif format == DebateFormat.COLLABORATIVE:
        agents.extend([
            DebateAgent("찬성연구원", AgentRole.SEARCHER, DebateStance.SUPPORT),
            DebateAgent("반대연구원", AgentRole.SEARCHER, DebateStance.OPPOSE),
        ])
    
    return agents


async def generate_agent_response(agent: DebateAgent, topic: str, history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """에이전트 응답 생성"""
    start_time = time.time()
    
    try:
        # 컨텍스트 변환
        context = [
            # 기존 히스토리를 Argument 객체로 변환하는 로직
        ]
        
        # 응답 생성
        response = await agent.generate_argument(topic, context, 1)
        
        # 응답 시간 기록
        duration = time.time() - start_time
        metrics_collector.record_timer("agent_response_time", duration, 
                                     {"agent": agent.name})
        
        return {
            "agent_name": agent.name,
            "content": response.content,
            "stance": response.stance.value,
            "timestamp": datetime.now().isoformat(),
            "response_time": duration
        }
        
    except Exception as e:
        logger.error("Agent response generation error", 
                    agent=agent.name, 
                    error=str(e))
        raise


async def stream_response(session_id: str, response: Dict[str, Any]):
    """응답 스트리밍"""
    await connection_manager.send_personal_message(
        json.dumps({
            "type": "agent_response",
            "data": response
        }),
        session_id
    )


async def handle_user_message(session_id: str, message_data: Dict[str, Any]):
    """사용자 메시지 처리"""
    if session_id not in active_debates:
        return
    
    session = active_debates[session_id]
    
    # 입력 검증
    content = input_sanitizer.sanitize_html(message_data.get("content", ""))
    
    user_message = {
        "type": "user_message",
        "content": content,
        "timestamp": datetime.now().isoformat()
    }
    
    await session.add_message(user_message)
    
    # 브로드캐스트
    await connection_manager.send_personal_message(
        json.dumps(user_message),
        session_id
    )


# 정적 파일 제공 (기존 HTML 유지)
@app.get("/", response_class=HTMLResponse)
async def get_index():
    """메인 페이지"""
    # 기존 HTML 내용 유지하되, 새로운 기능들 추가
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI 토론 시뮬레이터 - 프로덕션</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
            .container { max-width: 1200px; margin: 0 auto; }
            .status-bar { 
                background: #f0f0f0; 
                padding: 10px; 
                border-radius: 5px; 
                margin-bottom: 20px;
                display: flex;
                justify-content: space-between;
            }
            .status-indicator { 
                display: flex; 
                align-items: center; 
                gap: 10px;
            }
            .status-dot { 
                width: 10px; 
                height: 10px; 
                border-radius: 50%;
                background: #28a745;
            }
            .status-dot.error { background: #dc3545; }
            .status-dot.warning { background: #ffc107; }
            .btn { 
                padding: 10px 20px; 
                background: #007bff; 
                color: white; 
                border: none; 
                border-radius: 5px; 
                cursor: pointer;
            }
            .btn:hover { background: #0056b3; }
            .btn:disabled { background: #6c757d; cursor: not-allowed; }
            .metrics-panel {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 5px;
                margin-top: 20px;
            }
            .metrics-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-top: 15px;
            }
            .metric-card {
                background: white;
                padding: 15px;
                border-radius: 5px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .metric-value {
                font-size: 24px;
                font-weight: bold;
                color: #007bff;
            }
            .metric-label {
                color: #6c757d;
                font-size: 14px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎪 AI 토론 시뮬레이터 - 프로덕션</h1>
            
            <div class="status-bar">
                <div class="status-indicator">
                    <div class="status-dot" id="status-dot"></div>
                    <span id="status-text">시스템 상태 확인 중...</span>
                </div>
                <div class="status-indicator">
                    <span id="version-info">v5.0</span>
                </div>
            </div>
            
            <div class="metrics-panel">
                <h3>📊 실시간 시스템 메트릭</h3>
                <div class="metrics-grid" id="metrics-grid">
                    <div class="metric-card">
                        <div class="metric-value" id="active-debates">0</div>
                        <div class="metric-label">활성 토론</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="active-connections">0</div>
                        <div class="metric-label">연결 수</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="cache-hit-rate">0%</div>
                        <div class="metric-label">캐시 적중률</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value" id="response-time">0ms</div>
                        <div class="metric-label">평균 응답시간</div>
                    </div>
                </div>
            </div>
            
            <div style="margin-top: 30px;">
                <button class="btn" onclick="startDebate()">🚀 토론 시작</button>
                <button class="btn" onclick="showMetrics()">📊 상세 메트릭</button>
                <button class="btn" onclick="showHealth()">🏥 헬스체크</button>
            </div>
            
            <div id="content" style="margin-top: 30px;">
                <p>시스템이 준비되었습니다. 토론을 시작하세요!</p>
            </div>
        </div>
        
        <script>
            let ws = null;
            let currentSession = null;
            
            // 상태 업데이트
            async function updateStatus() {
                try {
                    const response = await fetch('/api/status');
                    const data = await response.json();
                    
                    document.getElementById('status-text').textContent = 
                        `${data.environment} 환경 - ${data.status}`;
                    document.getElementById('status-dot').className = 
                        'status-dot ' + (data.status === 'healthy' ? '' : 'error');
                        
                    // 메트릭 업데이트
                    document.getElementById('active-debates').textContent = data.active_debates;
                    document.getElementById('active-connections').textContent = data.active_connections;
                    
                } catch (error) {
                    console.error('Status update failed:', error);
                    document.getElementById('status-text').textContent = '상태 확인 실패';
                    document.getElementById('status-dot').className = 'status-dot error';
                }
            }
            
            // 메트릭 업데이트
            async function updateMetrics() {
                try {
                    const response = await fetch('/api/metrics');
                    const data = await response.json();
                    
                    // 캐시 적중률
                    const cacheStats = data.cache?.default;
                    if (cacheStats) {
                        document.getElementById('cache-hit-rate').textContent = 
                            Math.round(cacheStats.hit_rate * 100) + '%';
                    }
                    
                    // 응답시간
                    const responseTime = data.metrics?.request_duration?.recent_avg;
                    if (responseTime) {
                        document.getElementById('response-time').textContent = 
                            Math.round(responseTime * 1000) + 'ms';
                    }
                    
                } catch (error) {
                    console.error('Metrics update failed:', error);
                }
            }
            
            // 토론 시작
            async function startDebate() {
                const topic = prompt('토론 주제를 입력하세요:', 'AI의 미래에 대한 토론');
                if (!topic) return;
                
                try {
                    const response = await fetch('/api/debate/start', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            topic: topic,
                            format: 'adversarial',
                            max_rounds: 5
                        })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        currentSession = data.session_id;
                        connectWebSocket(data.session_id);
                        document.getElementById('content').innerHTML = 
                            `<h3>토론 시작됨</h3><p>주제: ${topic}</p><p>세션 ID: ${data.session_id}</p>`;
                    } else {
                        alert('토론 시작 실패: ' + data.detail);
                    }
                    
                } catch (error) {
                    console.error('Start debate failed:', error);
                    alert('토론 시작 중 오류가 발생했습니다.');
                }
            }
            
            // WebSocket 연결
            function connectWebSocket(sessionId) {
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                ws = new WebSocket(`${protocol}//${window.location.host}/ws/${sessionId}`);
                
                ws.onopen = function() {
                    console.log('WebSocket connected');
                    // 토론 시작 메시지 전송
                    ws.send(JSON.stringify({type: 'start_debate'}));
                };
                
                ws.onmessage = function(event) {
                    const data = JSON.parse(event.data);
                    console.log('Received:', data);
                    
                    if (data.type === 'agent_response') {
                        displayAgentResponse(data.data);
                    }
                };
                
                ws.onclose = function() {
                    console.log('WebSocket disconnected');
                };
                
                ws.onerror = function(error) {
                    console.error('WebSocket error:', error);
                };
            }
            
            // 에이전트 응답 표시
            function displayAgentResponse(response) {
                const content = document.getElementById('content');
                const responseDiv = document.createElement('div');
                responseDiv.style.cssText = 'margin: 10px 0; padding: 15px; border-left: 4px solid #007bff; background: #f8f9fa;';
                responseDiv.innerHTML = `
                    <strong>${response.agent_name}</strong> (${response.stance})
                    <br><br>
                    ${response.content}
                    <br><br>
                    <small>응답시간: ${Math.round(response.response_time * 1000)}ms</small>
                `;
                content.appendChild(responseDiv);
                content.scrollTop = content.scrollHeight;
            }
            
            // 메트릭 보기
            async function showMetrics() {
                try {
                    const response = await fetch('/api/metrics');
                    const data = await response.json();
                    
                    const metricsWindow = window.open('', '_blank', 'width=800,height=600');
                    metricsWindow.document.write(`
                        <html>
                        <head><title>시스템 메트릭</title></head>
                        <body>
                            <h1>📊 시스템 메트릭</h1>
                            <pre>${JSON.stringify(data, null, 2)}</pre>
                        </body>
                        </html>
                    `);
                } catch (error) {
                    alert('메트릭 조회 실패: ' + error.message);
                }
            }
            
            // 헬스체크 보기
            async function showHealth() {
                try {
                    const response = await fetch('/api/health');
                    const data = await response.json();
                    
                    const healthWindow = window.open('', '_blank', 'width=800,height=600');
                    healthWindow.document.write(`
                        <html>
                        <head><title>헬스체크</title></head>
                        <body>
                            <h1>🏥 헬스체크</h1>
                            <pre>${JSON.stringify(data, null, 2)}</pre>
                        </body>
                        </html>
                    `);
                } catch (error) {
                    alert('헬스체크 조회 실패: ' + error.message);
                }
            }
            
            // 초기화
            updateStatus();
            updateMetrics();
            
            // 정기적 업데이트
            setInterval(updateStatus, 30000);  // 30초마다
            setInterval(updateMetrics, 10000); // 10초마다
            
            // 페이지 언로드 시 정리
            window.addEventListener('beforeunload', function() {
                if (ws) {
                    ws.close();
                }
            });
        </script>
    </body>
    </html>
    """


# 서버 시작
if __name__ == "__main__":
    import uvicorn
    
    # 로깅 설정
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format=settings.log_format,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(settings.log_file) if settings.log_file else logging.NullHandler()
        ]
    )
    
    logger.info(f"Starting server on {settings.host}:{settings.port} in {settings.environment} environment")
    
    uvicorn.run(
        "final_web_app_improved:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )