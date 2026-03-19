"""Model listing endpoint."""

import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["models"])


def _load_models() -> list[dict[str, Any]]:
    """Load model definitions from config/models.yaml with legacy fallback."""
    yaml_path = Path(__file__).parent.parent.parent / "config" / "models.yaml"
    if yaml_path.exists():
        with open(yaml_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        models: list[dict[str, Any]] = []
        for provider_group in config.get("models", {}).values():
            for m in provider_group:
                models.append(m)
        return models
    # Fallback to legacy hardcoded dict
    logger.warning("config/models.yaml not found, falling back to debate_agent.OPENROUTER_MODELS")
    from debate_agent import OPENROUTER_MODELS

    return [{"id": k, **v} for k, v in OPENROUTER_MODELS.items()]


@router.get("/models")
async def get_models():
    """Return available LLM models."""
    models = _load_models()
    result = []
    for m in models:
        result.append(
            {
                "name": m.get("id", ""),
                "display_name": m.get("name", ""),
                "provider": m.get("provider", ""),
                "context": m.get("context_length", m.get("context", 0)),
            }
        )
    return {"models": result, "success": True}
