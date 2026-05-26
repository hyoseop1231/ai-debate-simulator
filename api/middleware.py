"""Security headers and CORS middleware configuration."""

import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_settings
from utils.security import RateLimiter


def setup_cors(app: FastAPI) -> None:
    """Configure CORS middleware using Settings-based origins."""
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=settings.cors_credentials,
        allow_methods=settings.cors_methods,
        allow_headers=settings.cors_headers,
    )


def setup_security_headers(app: FastAPI) -> None:
    """Register the security-headers / metrics middleware."""
    from api.state import metrics

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        """Add security headers and collect request metrics."""
        start_time = time.time()

        try:
            response = await call_next(request)

            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self' ws:"
            )
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

            metrics.record_request()

            return response

        except Exception as e:
            metrics.record_error()
            raise


_rate_limiter = RateLimiter()


async def rate_limit_dependency(request: Request) -> None:
    """FastAPI dependency for rate limiting."""
    client_ip = request.client.host if request.client else "unknown"
    allowed, info = _rate_limiter.is_allowed(client_ip, client_ip)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many requests")
    try:
        yield
    finally:
        # 요청 처리 완료 후 lock 해제 -- 미해제 시 동일 client의
        # 다음 요청이 즉시 429를 반환하는 버그 방지
        _rate_limiter.release_lock(client_ip)
