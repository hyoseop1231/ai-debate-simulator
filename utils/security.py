"""
보안 관련 유틸리티 및 검증 함수들
"""

import re
import html
import hashlib
import hmac
import secrets
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator
from datetime import datetime, timedelta
from collections import defaultdict
import time
import logging

logger = logging.getLogger(__name__)


class SecureDebateRequest(BaseModel):
    """보안이 강화된 토론 요청 모델"""
    
    topic: str = Field(..., min_length=5, max_length=500, description="토론 주제")
    format: str = Field(..., regex="^(adversarial|collaborative|competitive|custom)$", description="토론 형식")
    max_rounds: int = Field(default=5, ge=1, le=10, description="최대 라운드 수")
    model: str = Field(default="llama3.2:3b", description="사용할 AI 모델")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="모델 온도")
    custom_agents: Optional[List[Dict[str, str]]] = Field(default=None, description="커스텀 에이전트")
    
    @validator('topic')
    def sanitize_topic(cls, v):
        """토론 주제 검증 및 정리"""
        if not v or not v.strip():
            raise ValueError("토론 주제는 비어있을 수 없습니다.")
        
        # HTML 태그 제거
        clean_topic = html.escape(v.strip())
        
        # 기본적인 XSS 패턴 필터링
        xss_patterns = [
            r'<script[^>]*>.*?</script>',
            r'javascript:',
            r'on\w+\s*=',
            r'<iframe[^>]*>.*?</iframe>',
            r'<object[^>]*>.*?</object>',
            r'<embed[^>]*>.*?</embed>',
        ]
        
        for pattern in xss_patterns:
            clean_topic = re.sub(pattern, '', clean_topic, flags=re.IGNORECASE | re.DOTALL)
        
        # 연속된 공백 정리
        clean_topic = re.sub(r'\s+', ' ', clean_topic)
        
        # 최종 길이 검증
        if len(clean_topic) < 5:
            raise ValueError("토론 주제는 최소 5자 이상이어야 합니다.")
        
        return clean_topic
    
    @validator('custom_agents')
    def validate_custom_agents(cls, v):
        """커스텀 에이전트 검증"""
        if v is None:
            return v
        
        if not isinstance(v, list):
            raise ValueError("커스텀 에이전트는 리스트여야 합니다.")
        
        if len(v) > 10:
            raise ValueError("커스텀 에이전트는 최대 10개까지 허용됩니다.")
        
        for agent in v:
            if not isinstance(agent, dict):
                raise ValueError("각 에이전트는 딕셔너리여야 합니다.")
            
            required_fields = ['name', 'role', 'emoji']
            for field in required_fields:
                if field not in agent:
                    raise ValueError(f"에이전트에는 '{field}' 필드가 필요합니다.")
                
                # 에이전트 이름 검증
                if field == 'name':
                    agent_name = html.escape(agent[field].strip())
                    if not agent_name or len(agent_name) > 50:
                        raise ValueError("에이전트 이름은 1-50자여야 합니다.")
                    agent[field] = agent_name
        
        return v


class InputSanitizer:
    """입력 데이터 정리 및 검증"""
    
    @staticmethod
    def sanitize_html(text: str) -> str:
        """HTML 태그 및 악성 코드 제거"""
        if not text:
            return ""
        
        # HTML 엔티티 변환
        text = html.escape(text)
        
        # 기본적인 정리
        text = text.strip()
        text = re.sub(r'\s+', ' ', text)
        
        return text
    
    @staticmethod
    def validate_session_id(session_id: str) -> bool:
        """세션 ID 검증"""
        if not session_id:
            return False
        
        # UUID v4 형식 검증
        pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
        return bool(re.match(pattern, session_id.lower()))
    
    @staticmethod
    def validate_ip_address(ip: str) -> bool:
        """IP 주소 검증"""
        if not ip:
            return False
        
        # IPv4 패턴
        ipv4_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        if re.match(ipv4_pattern, ip):
            parts = ip.split('.')
            return all(0 <= int(part) <= 255 for part in parts)
        
        # IPv6 패턴 (간단한 검증)
        ipv6_pattern = r'^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$'
        return bool(re.match(ipv6_pattern, ip))


class RateLimiter:
    """레이트 리미터 구현"""
    
    def __init__(self, max_requests: int = 10, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
        self.blocked_ips = defaultdict(float)  # IP: 차단 해제 시간
        self.lock = defaultdict(lambda: False)
    
    def is_allowed(self, client_id: str, ip: str = None) -> tuple[bool, Dict[str, Any]]:
        """요청 허용 여부 확인"""
        now = time.time()
        
        # IP 차단 확인
        if ip and ip in self.blocked_ips:
            if now < self.blocked_ips[ip]:
                return False, {
                    'error': 'IP temporarily blocked',
                    'retry_after': int(self.blocked_ips[ip] - now)
                }
            else:
                del self.blocked_ips[ip]
        
        # 동시성 제어
        if self.lock[client_id]:
            return False, {'error': 'Request in progress'}
        
        # 오래된 요청 기록 제거
        self.requests[client_id] = [
            req_time for req_time in self.requests[client_id]
            if now - req_time < self.time_window
        ]
        
        # 요청 수 확인
        if len(self.requests[client_id]) >= self.max_requests:
            # 과도한 요청 시 IP 일시 차단
            if ip:
                self.blocked_ips[ip] = now + 300  # 5분 차단
            
            return False, {
                'error': 'Rate limit exceeded',
                'retry_after': self.time_window
            }
        
        # 요청 기록 추가
        self.requests[client_id].append(now)
        self.lock[client_id] = True
        
        return True, {'remaining': self.max_requests - len(self.requests[client_id])}
    
    def release_lock(self, client_id: str):
        """클라이언트 락 해제"""
        self.lock[client_id] = False
    
    def get_stats(self) -> Dict[str, Any]:
        """레이트 리미터 통계"""
        now = time.time()
        active_clients = len([
            client for client, requests in self.requests.items()
            if any(now - req_time < self.time_window for req_time in requests)
        ])
        
        return {
            'active_clients': active_clients,
            'blocked_ips': len(self.blocked_ips),
            'total_requests': sum(len(requests) for requests in self.requests.values())
        }


class SecurityHeaders:
    """보안 헤더 관리"""
    
    @staticmethod
    def get_security_headers() -> Dict[str, str]:
        """보안 헤더 반환"""
        return {
            'X-Content-Type-Options': 'nosniff',
            'X-Frame-Options': 'DENY',
            'X-XSS-Protection': '1; mode=block',
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
            'Referrer-Policy': 'strict-origin-when-cross-origin',
            'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        }


class SessionManager:
    """세션 관리 및 보안"""
    
    def __init__(self):
        self.sessions = {}
        self.session_timeout = 3600  # 1시간
    
    def create_session(self, client_info: Dict[str, Any]) -> str:
        """세션 생성"""
        session_id = secrets.token_hex(16)
        
        self.sessions[session_id] = {
            'created_at': datetime.now(),
            'last_activity': datetime.now(),
            'client_info': client_info,
            'is_active': True
        }
        
        return session_id
    
    def validate_session(self, session_id: str) -> bool:
        """세션 검증"""
        if not session_id or session_id not in self.sessions:
            return False
        
        session = self.sessions[session_id]
        
        # 세션 만료 확인
        if datetime.now() - session['last_activity'] > timedelta(seconds=self.session_timeout):
            self.invalidate_session(session_id)
            return False
        
        # 마지막 활동 시간 업데이트
        session['last_activity'] = datetime.now()
        return session['is_active']
    
    def invalidate_session(self, session_id: str):
        """세션 무효화"""
        if session_id in self.sessions:
            self.sessions[session_id]['is_active'] = False
    
    def cleanup_expired_sessions(self):
        """만료된 세션 정리"""
        now = datetime.now()
        expired_sessions = [
            session_id for session_id, session in self.sessions.items()
            if now - session['last_activity'] > timedelta(seconds=self.session_timeout)
        ]
        
        for session_id in expired_sessions:
            del self.sessions[session_id]
        
        logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")


# 전역 인스턴스
rate_limiter = RateLimiter()
session_manager = SessionManager()
security_headers = SecurityHeaders()
input_sanitizer = InputSanitizer()