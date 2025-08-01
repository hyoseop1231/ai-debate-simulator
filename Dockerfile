# AI 토론 시뮬레이터 - 프로덕션 수준 Dockerfile
# 멀티스테이지 빌드를 사용한 보안 및 성능 최적화

# 빌드 스테이지
FROM python:3.11-slim as builder

# 빌드 도구 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python 최적화 환경 변수
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 의존성 설치
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 프로덕션 스테이지
FROM python:3.11-slim as production

# 보안 업데이트 및 런타임 의존성 설치
RUN apt-get update && apt-get install -y \
    curl \
    dumb-init \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get autoremove -y \
    && apt-get clean

# 시스템 사용자 생성 (보안 강화)
RUN groupadd -r appuser && \
    useradd -r -g appuser -d /app -s /bin/bash appuser

# 작업 디렉토리 설정
WORKDIR /app

# Python 환경 설정
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/app/.local/bin:$PATH"

# 빌드 스테이지에서 의존성 복사
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 애플리케이션 파일 복사
COPY --chown=appuser:appuser . .

# 로그 디렉토리 생성
RUN mkdir -p /app/logs && \
    chown -R appuser:appuser /app/logs

# 설정 파일 권한 설정
RUN chown -R appuser:appuser /app && \
    chmod -R 755 /app && \
    chmod -R 644 /app/config/*.py

# 보안 강화: 불필요한 파일 제거
RUN find /app -name "*.pyc" -delete && \
    find /app -name "__pycache__" -type d -exec rm -rf {} + || true

# 사용자 전환
USER appuser

# 환경 변수 설정
ENV ENVIRONMENT=production \
    DEBUG=false \
    HOST=0.0.0.0 \
    PORT=8003 \
    OLLAMA_API_URL=http://host.docker.internal:11434 \
    LOG_LEVEL=INFO \
    METRICS_ENABLED=true

# 포트 노출
EXPOSE 8003

# 헬스체크 개선
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8003/api/health || exit 1

# 볼륨 설정
VOLUME ["/app/logs"]

# dumb-init을 사용한 안전한 프로세스 시작
ENTRYPOINT ["dumb-init", "--"]

# 메인 애플리케이션 실행
CMD ["python3", "final_web_app.py"]

# 개발 환경 스테이지
FROM production as development

# 개발 도구 설치
USER root
RUN apt-get update && apt-get install -y \
    vim \
    htop \
    && rm -rf /var/lib/apt/lists/*

# 개발 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 개발 환경 설정
ENV ENVIRONMENT=development \
    DEBUG=true \
    LOG_LEVEL=DEBUG \
    HOT_RELOAD=true

USER appuser

# 개발 서버 실행
CMD ["python3", "final_web_app.py"]

# 테스트 환경 스테이지
FROM development as testing

# 테스트 도구 설치
USER root
RUN pip install --no-cache-dir pytest pytest-asyncio pytest-cov httpx

# 테스트 실행
USER appuser
CMD ["pytest", "-v", "--cov=.", "--cov-report=html"]

# 레이블 추가 (메타데이터)
LABEL maintainer="AI Debate Simulator Team" \
      version="5.0" \
      description="Production-ready AI Debate Simulator" \
      org.opencontainers.image.source="https://github.com/yourusername/ai-debate-simulator" \
      org.opencontainers.image.documentation="https://github.com/yourusername/ai-debate-simulator/README.md" \
      org.opencontainers.image.licenses="MIT"