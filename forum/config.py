"""ForumEngine configuration with format presets."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ForumEngineConfig(BaseModel):
    """ForumEngine configuration.

    Replaces the old DebateFormat enum. Different debate styles
    are now parameter presets, not separate code paths.
    """

    max_rounds: int = Field(5, ge=1, description="Maximum number of forum rounds")
    speech_trigger: int = Field(
        5, ge=1, description="Moderator intervenes every N speeches"
    )
    convergence_threshold: float = Field(
        0.85,
        ge=0.0,
        le=1.0,
        description="Embedding similarity threshold for repeat detection",
    )
    confrontation_level: str = Field(
        "medium", description="Confrontation level: low/medium/high"
    )
    allow_cross_team: bool = Field(
        True, description="Allow cross-cluster interactions"
    )
    team_integration: bool = Field(
        False, description="Enable team-based integration mode"
    )

    # Swarm env.step pattern
    simulate_time: bool = Field(
        False, description="Enable time-based agent selection"
    )
    minutes_per_round: int = Field(60, ge=1, description="Minutes per round")

    # Topic storage
    topic: str = Field("", description="Debate topic")

    @classmethod
    def adversarial(cls) -> ForumEngineConfig:
        """Preset: ADVERSARIAL (was DebateFormat.ADVERSARIAL)."""
        return cls(confrontation_level="high", allow_cross_team=True, max_rounds=5)

    @classmethod
    def collaborative(cls) -> ForumEngineConfig:
        """Preset: COLLABORATIVE (was DebateFormat.COLLABORATIVE)."""
        return cls(confrontation_level="low", team_integration=True, max_rounds=3)

    @classmethod
    def competitive(cls) -> ForumEngineConfig:
        """Preset: COMPETITIVE (was DebateFormat.COMPETITIVE)."""
        return cls(confrontation_level="medium", max_rounds=5, speech_trigger=3)
