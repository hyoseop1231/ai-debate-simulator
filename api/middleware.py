"""Security headers and CORS middleware configuration."""

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_settings


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
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:"
            )

            metrics.record_request()

            return response

        except Exception as e:
            metrics.record_error()
            raise
