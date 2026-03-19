"""API endpoints for the ForumEngine pipeline.

Provides REST endpoints to start forum debates, poll status,
retrieve results, and read transcripts.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from api.middleware import rate_limit_dependency
from forum.config import ForumEngineConfig
from forum.engine import ForumEngine

router = APIRouter(prefix="/api/forum", tags=["forum"])
logger = logging.getLogger(__name__)

# Active forum sessions: session_id -> {"engine": ForumEngine, "task": asyncio.Task, "created_at": float}
active_forums: Dict[str, Dict[str, Any]] = {}

SESSION_TTL = 3600  # 1 hour
MAX_SESSIONS = 50


def _cleanup_expired_sessions() -> None:
    """Remove expired forum sessions."""
    now = time.time()
    expired = [
        sid for sid, data in active_forums.items()
        if now - data.get("created_at", now) > SESSION_TTL
        or data.get("status") == "completed"
    ]
    for sid in expired:
        del active_forums[sid]


# ------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------


class ForumStartRequest(BaseModel):
    """Request body for starting a new forum debate."""

    topic: str = Field(..., min_length=1, max_length=500, description="Debate topic")
    sources: Optional[List[str]] = Field(
        default=["user"], description="Data sources for seed collection"
    )
    seed_texts: Optional[List[str]] = Field(
        None, max_length=10, description="User-provided seed texts"
    )

    @field_validator("topic")
    @classmethod
    def sanitize_topic(cls, v: str) -> str:
        """Remove XSS patterns from topic."""
        v = re.sub(r'<[^>]*>', '', v)  # Strip HTML tags
        v = re.sub(r'[<>"\'&]', '', v)  # Remove dangerous chars
        return v.strip()

    @field_validator("seed_texts")
    @classmethod
    def sanitize_seeds(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate and sanitize seed texts."""
        if v is None:
            return v
        sanitized = []
        for text in v:
            if len(text) > 2000:
                text = text[:2000]
            text = re.sub(r'<[^>]*>', '', text)
            sanitized.append(text)
        return sanitized
    max_rounds: int = Field(5, ge=1, le=20, description="Maximum debate rounds")
    preset: Optional[str] = Field(
        None, description="Config preset: adversarial, collaborative, competitive"
    )
    agent_model: Optional[str] = Field(
        "gpt-oss:20b", description="LLM model for debate agents (gpt-oss:20b+ recommended)"
    )
    moderator_model: Optional[str] = Field(
        "glm-4.7-flash:latest",
        description="LLM model for moderator (anti-homogenization)",
    )
    n_clusters: Optional[int] = Field(
        None, description="Number of clusters (None = auto via HDBSCAN)"
    )
    nodes: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Ollama node list for distributed agents. Format: [{name, api_url, models?, priority?}]",
    )
    node_mapping: Optional[Dict[str, str]] = Field(
        None,
        description="Cluster-to-node mapping. Format: {'0': 'bigboy1', '1': 'thor'}",
    )


class ForumStartResponse(BaseModel):
    """Response body after starting a forum debate."""

    session_id: str
    status: str
    topic: str
    max_rounds: int
    preset: str


class ForumStatusResponse(BaseModel):
    """Response body for forum status polling."""

    session_id: str
    status: str
    current_round: int
    max_rounds: int
    total_posts: int
    is_active: bool


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.post("/start", response_model=ForumStartResponse, dependencies=[Depends(rate_limit_dependency)])
async def start_forum(request: ForumStartRequest) -> ForumStartResponse:
    """Start a new forum debate pipeline.

    Full pipeline: collect -> cluster -> create agents -> forum debate.

    For Phase 2, seed_texts are used directly as cluster key_arguments
    when the clustering engine (L1) is not yet available.
    """
    # 0. Cleanup expired sessions
    _cleanup_expired_sessions()

    # 1. Build ForumEngineConfig from preset or defaults
    config = _build_config(request)

    # 2. Create representative agents from seed texts or defaults
    try:
        agents = await _create_agents(
            topic=request.topic,
            seed_texts=request.seed_texts,
            model=request.agent_model or "gpt-oss:20b",
            nodes=request.nodes,
            node_mapping=request.node_mapping,
        )
    except Exception as e:
        logger.error("Failed to create agents: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="내부 오류가 발생했습니다.")

    # 3. Create moderator (different model for anti-homogenization)
    try:
        moderator = _create_moderator(
            model=request.moderator_model or "glm-4.7-flash:latest",
            agent_model=request.agent_model or "qwen2.5-coder:32b",
            speech_trigger=config.speech_trigger,
        )
    except Exception as e:
        logger.error("Failed to create moderator: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="내부 오류가 발생했습니다.")

    # 4. Create ForumEngine
    engine = ForumEngine(
        config=config,
        agents=agents,
        moderator=moderator,
    )

    # 5. Launch debate as background task
    task = asyncio.create_task(_run_forum(engine))
    active_forums[engine.session_id] = {
        "engine": engine,
        "task": task,
        "created_at": time.time(),
    }

    preset_name = request.preset or "default"
    logger.info(
        "Forum started: session=%s topic=%s preset=%s",
        engine.session_id,
        request.topic,
        preset_name,
    )

    return ForumStartResponse(
        session_id=engine.session_id,
        status="running",
        topic=request.topic,
        max_rounds=config.max_rounds,
        preset=preset_name,
    )


@router.get("/{session_id}/status", response_model=ForumStatusResponse)
async def get_forum_status(session_id: str) -> ForumStatusResponse:
    """Get forum debate status."""
    session = active_forums.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    engine: ForumEngine = session["engine"]
    status = engine.get_status()

    return ForumStatusResponse(**status)


@router.get("/{session_id}/result")
async def get_forum_result(session_id: str) -> Dict[str, Any]:
    """Get forum debate result.

    Returns full result if debate is completed, or partial
    result with current status if still running.
    """
    session = active_forums.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    engine: ForumEngine = session["engine"]

    if engine.status == "running":
        # Return partial result with running status
        return {
            "session_id": engine.session_id,
            "status": "running",
            "current_round": engine.current_round,
            "total_posts": len(engine.all_posts),
            "message": "Debate is still in progress. Poll /status for updates.",
        }

    # Debate completed or errored
    return engine._build_result()


@router.get("/{session_id}/transcript")
async def get_forum_transcript(session_id: str) -> Dict[str, Any]:
    """Get forum debate transcript (forum.log content).

    Returns the raw forum.log entries as a list of lines
    and a formatted text block.
    """
    session = active_forums.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    engine: ForumEngine = session["engine"]
    entries = engine.forum_reader.get_all_entries()

    return {
        "session_id": session_id,
        "status": engine.status,
        "entry_count": len(entries),
        "entries": [line.strip() for line in entries if line.strip()],
        "transcript": "".join(entries),
    }


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _build_config(request: ForumStartRequest) -> ForumEngineConfig:
    """Build ForumEngineConfig from request, applying preset if specified."""
    preset_map = {
        "adversarial": ForumEngineConfig.adversarial,
        "collaborative": ForumEngineConfig.collaborative,
        "competitive": ForumEngineConfig.competitive,
    }

    if request.preset and request.preset in preset_map:
        config = preset_map[request.preset]()
    else:
        config = ForumEngineConfig()

    # Override max_rounds from request
    config.max_rounds = request.max_rounds
    config.topic = request.topic

    return config


async def _create_agents(
    topic: str,
    seed_texts: Optional[List[str]],
    model: str,
    nodes: Optional[List[Dict[str, Any]]] = None,
    node_mapping: Optional[Dict[str, str]] = None,
) -> list:
    """Create debate agents, optionally distributed across multiple Ollama nodes.

    When clustering engine (L1) is available, this will use
    PersonaFactory.create_agents(clusters). For now, create
    agents directly from seed texts or generate default opposing views.
    """
    from models.schemas import ClusterProfile

    # Build synthetic clusters from seed_texts or create defaults
    if seed_texts and len(seed_texts) >= 2:
        clusters = _clusters_from_seeds(seed_texts)
    else:
        clusters = _default_clusters(topic, seed_texts)

    # Build NodeRegistry if multi-node config provided
    node_registry = None
    int_mapping = None

    if nodes:
        from config.nodes import NodeRegistry
        node_registry = NodeRegistry.from_config(nodes)
        await node_registry.health_check_all()
        logger.info("Node health: %s", node_registry.summary())

        if node_mapping:
            int_mapping = {int(k): v for k, v in node_mapping.items()}

    # Use PersonaFactory to create agents
    from agents.factory import PersonaFactory

    factory = PersonaFactory(
        default_model=model,
        node_registry=node_registry,
        node_mapping=int_mapping,
    )
    agents = await factory.create_agents(clusters, use_llm_persona=False)

    return agents


def _clusters_from_seeds(seed_texts: List[str]) -> list:
    """Build synthetic ClusterProfile list from user seed texts."""
    from models.schemas import ClusterProfile

    clusters: list[ClusterProfile] = []
    weight = 1.0 / len(seed_texts)

    for i, text in enumerate(seed_texts):
        label = f"view-{i + 1}"
        sentiment = 0.3 if i % 2 == 0 else -0.3

        clusters.append(
            ClusterProfile(
                cluster_id=i,
                label=label,
                weight=weight,
                document_count=1,
                key_arguments=[text],
                keywords=text.split()[:5],
                sentiment=sentiment,
            )
        )

    return clusters


def _default_clusters(topic: str, seed_texts: Optional[List[str]]) -> list:
    """Create default pro/con clusters when no seed texts provided."""
    from models.schemas import ClusterProfile

    seed_text = seed_texts[0] if seed_texts else topic

    return [
        ClusterProfile(
            cluster_id=0,
            label="support",
            weight=0.5,
            document_count=1,
            key_arguments=[
                f"{seed_text} - this position has significant merit and evidence."
            ],
            keywords=topic.split()[:3],
            sentiment=0.5,
        ),
        ClusterProfile(
            cluster_id=1,
            label="oppose",
            weight=0.5,
            document_count=1,
            key_arguments=[
                f"{seed_text} - this position has notable risks and concerns."
            ],
            keywords=topic.split()[:3],
            sentiment=-0.5,
        ),
    ]


def _create_moderator(model: str, agent_model: str, speech_trigger: int = 5) -> Any:
    """Create a ForumHost moderator.

    Uses agents.moderator.ForumHost if available, otherwise
    creates a minimal moderator implementation.
    """
    try:
        from agents.moderator import ForumHost

        return ForumHost(model=model, debate_agent_model=agent_model, speech_trigger=speech_trigger)
    except ImportError:
        logger.warning(
            "agents.moderator.ForumHost not found, using inline moderator"
        )
        return _InlineModerator(model=model, speech_trigger=speech_trigger)


class _InlineModerator:
    """Minimal moderator implementation for when ForumHost is not available.

    Implements the ModeratorProtocol expected by ForumEngine.
    """

    def __init__(self, model: str, speech_trigger: int = 5) -> None:
        from agents.base import BaseLLMAgent

        self._llm = BaseLLMAgent(model=model)
        self._speech_trigger = speech_trigger
        self._speech_count = 0

    def record_speech(self) -> None:
        """Record that a speech occurred."""
        self._speech_count += 1

    def should_intervene(self) -> bool:
        """Check if moderator should intervene (every N speeches)."""
        if self._speech_count >= self._speech_trigger:
            self._speech_count = 0
            return True
        return False

    async def generate_moderation(
        self,
        recent_entries: list,
        topic: str,
    ) -> str:
        """Generate moderation summary from recent debate entries."""
        entries_text = "\n".join(
            f"[{e.source}]: {e.content}" for e in recent_entries
        )

        prompt = (
            f"You are the forum moderator for a debate on: {topic}\n\n"
            f"Recent debate entries:\n{entries_text}\n\n"
            f"Provide a brief moderation summary (3-5 sentences):\n"
            f"1. Summarize key points raised\n"
            f"2. Identify areas of agreement or disagreement\n"
            f"3. Suggest direction for continued discussion\n"
            f"4. Note any logical issues or factual concerns"
        )

        result = await self._llm._call_llm(
            prompt,
            system_prompt=(
                "You are an impartial forum moderator. Summarize the debate "
                "objectively. Point out logical fallacies or factual errors. "
                "If consensus or deadlock is reached, state it clearly."
            ),
            max_tokens=500,
        )

        content = result.get("content", "")
        if not content or content.startswith("["):
            return (
                f"Moderator summary: The debate on '{topic}' continues "
                f"with {len(recent_entries)} recent contributions. "
                f"Participants are encouraged to address each other's points directly."
            )

        return content


async def _run_forum(engine: ForumEngine) -> Dict[str, Any]:
    """Background task wrapper for running a forum debate."""
    try:
        result = await engine.run()
        logger.info("Forum %s completed: %d posts", engine.session_id, len(engine.all_posts))
        return result
    except Exception as e:
        logger.exception("Forum %s failed: %s", engine.session_id, e)
        engine.status = "error"
        engine._error = str(e)
        return engine._build_result()
