"""Model listing endpoint."""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/models")
async def get_models():
    """Return available LLM models."""
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
