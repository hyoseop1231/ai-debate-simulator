"""
환경별 설정 관리 시스템
프로덕션 수준의 보안 및 성능 최적화를 위한 설정
"""

import os
from typing import List, Optional
from pydantic import BaseSettings, Field, validator


class Settings(BaseSettings):
    """애플리케이션 전체 설정"""
    
    # 환경 설정
    environment: str = Field(default="development", description="실행 환경")
    debug: bool = Field(default=True, description="디버그 모드")
    
    # 서버 설정
    host: str = Field(default="0.0.0.0", description="서버 호스트")
    port: int = Field(default=8003, description="서버 포트")
    
    # 보안 설정
    allowed_origins: List[str] = Field(
        default=["http://localhost:8003", "http://localhost:3000"],
        description="허용된 CORS 오리진"
    )
    cors_credentials: bool = Field(default=True, description="CORS 자격증명 허용")
    cors_methods: List[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        description="허용된 HTTP 메서드"
    )
    cors_headers: List[str] = Field(
        default=["Content-Type", "Authorization", "X-Requested-With"],
        description="허용된 HTTP 헤더"
    )
    
    # 성능 설정
    max_concurrent_debates: int = Field(default=10, description="최대 동시 토론 수")
    max_history_size: int = Field(default=50, description="토론 기록 최대 크기")
    response_timeout: int = Field(default=30, description="응답 타임아웃(초)")
    cleanup_interval: int = Field(default=300, description="정리 간격(초)")
    
    # Ollama 설정
    ollama_api_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API URL"
    )
    ollama_timeout: int = Field(default=30, description="Ollama 타임아웃(초)")
    ollama_max_retries: int = Field(default=3, description="Ollama 최대 재시도 횟수")
    
    # 캐싱 설정
    cache_ttl_minutes: int = Field(default=30, description="캐시 TTL(분)")
    cache_max_size: int = Field(default=1000, description="캐시 최대 크기")
    
    # 레이트 리미팅 설정
    rate_limit_requests: int = Field(default=10, description="레이트 리미트 요청 수")
    rate_limit_window: int = Field(default=60, description="레이트 리미트 시간 윈도우(초)")
    
    # 로깅 설정
    log_level: str = Field(default="INFO", description="로그 레벨")
    log_format: str = Field(
        default="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        description="로그 형식"
    )
    log_file: Optional[str] = Field(default=None, description="로그 파일 경로")
    
    # 모니터링 설정
    metrics_enabled: bool = Field(default=True, description="메트릭 수집 활성화")
    health_check_interval: int = Field(default=30, description="헬스체크 간격(초)")
    
    @validator('environment')
    def validate_environment(cls, v):
        allowed_envs = ['development', 'staging', 'production']
        if v not in allowed_envs:
            raise ValueError(f'Environment must be one of: {allowed_envs}')
        return v
    
    @validator('log_level')
    def validate_log_level(cls, v):
        allowed_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in allowed_levels:
            raise ValueError(f'Log level must be one of: {allowed_levels}')
        return v.upper()
    
    @validator('allowed_origins')
    def validate_origins(cls, v):
        if not v:
            raise ValueError('At least one origin must be specified')
        return v
    
    class Config:
        env_file = f".env.{os.getenv('ENVIRONMENT', 'development')}"
        env_file_encoding = 'utf-8'
        case_sensitive = False


# 환경별 설정 인스턴스
settings = Settings()


def get_settings() -> Settings:
    """설정 인스턴스 반환"""
    return settings


# 환경별 기본 설정
def get_production_settings():
    """프로덕션 환경 설정"""
    return Settings(
        environment="production",
        debug=False,
        allowed_origins=["https://yourdomain.com"],
        max_concurrent_debates=50,
        response_timeout=10,
        cache_ttl_minutes=60,
        rate_limit_requests=5,
        rate_limit_window=60,
        log_level="WARNING"
    )


def get_development_settings():
    """개발 환경 설정"""
    return Settings(
        environment="development",
        debug=True,
        allowed_origins=["http://localhost:8003", "http://localhost:3000"],
        max_concurrent_debates=5,
        response_timeout=30,
        cache_ttl_minutes=10,
        rate_limit_requests=20,
        rate_limit_window=60,
        log_level="DEBUG"
    )


def get_testing_settings():
    """테스트 환경 설정"""
    return Settings(
        environment="testing",
        debug=True,
        allowed_origins=["http://localhost:8003"],
        max_concurrent_debates=2,
        response_timeout=5,
        cache_ttl_minutes=1,
        rate_limit_requests=100,
        rate_limit_window=60,
        log_level="DEBUG"
    )