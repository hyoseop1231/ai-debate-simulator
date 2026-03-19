"""ForumEngine configuration with format presets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ForumEngineConfig:
    """ForumEngine configuration.

    Replaces the old DebateFormat enum. Different debate styles
    are now parameter presets, not separate code paths.
    """

    max_rounds: int = 5
    speech_trigger: int = 5  # Moderator intervenes every N speeches
    convergence_threshold: float = 0.85  # Embedding similarity for repeat detection
    confrontation_level: str = "medium"  # low/medium/high
    allow_cross_team: bool = True
    team_integration: bool = False

    # Swarm env.step pattern
    simulate_time: bool = False  # Enable time-based agent selection
    minutes_per_round: int = 60

    # Topic storage
    topic: str = ""

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
