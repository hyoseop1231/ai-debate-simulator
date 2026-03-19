"""Health, status, and metrics endpoints."""

import os
from datetime import datetime

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from api.state import active_debates, metrics

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/status")
async def get_status():
    """Server status."""
    return {
        "status": "online",
        "active_debates": len(active_debates),
        "version": "4.1",
        "environment": "production",
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/metrics")
async def get_metrics():
    """System metrics."""
    return {"metrics": metrics.get_stats(), "timestamp": datetime.now().isoformat()}


@router.get("/health")
async def health_check():
    """Health check endpoint."""
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


@router.get("/openrouter/status")
async def get_openrouter_status():
    """OpenRouter API status check."""
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_api_url = os.getenv(
        "OPENROUTER_API_URL", "https://openrouter.ai/api/v1"
    )

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


@router.get("/ollama/status")
async def get_ollama_status():
    """Ollama status (redirects to OpenRouter status)."""
    return await get_openrouter_status()
