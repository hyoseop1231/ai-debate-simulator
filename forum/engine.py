"""BettaFish-style forum engine with pub/sub log pattern.

Replaces DebateController. Agents communicate through log files,
not direct calls. Moderator (ForumHost) intervenes every N speeches.
Uses Swarm env.step pattern for agent selection.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

from models.schemas import ForumPost, LogEntry

from forum.config import ForumEngineConfig

logger = logging.getLogger(__name__)


# @MX:NOTE: Protocol defines the moderator interface expected by ForumEngine.
# Any object implementing these methods can serve as moderator (duck typing).
class ModeratorProtocol(Protocol):
    """Protocol for moderator objects used by ForumEngine."""

    def record_speech(self) -> None: ...

    def should_intervene(self) -> bool: ...

    async def generate_moderation(
        self,
        recent_entries: List[LogEntry],
        topic: str,
    ) -> str: ...


class ForumLogWriter:
    """Writes agent posts to individual JSONL log files.

    BettaFish pattern: each agent has its own log file.
    The consolidated forum.log uses [SOURCE] tags.
    """

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def write(self, agent_id: str, post: ForumPost) -> None:
        """Append a post to the agent's log file."""
        log_file = self.log_dir / f"{agent_id}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(
                json.dumps(post.model_dump(), default=str, ensure_ascii=False) + "\n"
            )

    def write_to_forum(
        self,
        source: str,
        content: str,
        round_number: int,
        entry_type: str = "argument",
    ) -> None:
        """Write to consolidated forum.log with [SOURCE] tag."""
        forum_file = self.log_dir / "forum.log"
        timestamp = datetime.now().strftime("%H:%M:%S")
        content_oneline = content.replace("\n", "\\n")
        entry = f"[{timestamp}] [{source.upper()}] {content_oneline}\n"
        with open(forum_file, "a", encoding="utf-8") as f:
            f.write(entry)


class ForumReader:
    """Reads latest moderator summary from forum.log.

    BettaFish pattern: agents read [HOST] entries and inject
    into their LLM prompt as "### Forum Host Latest Summary".
    Caches last entry to prevent duplicate injection.
    """

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self._last_host_entry: Optional[str] = None

    def get_latest_host_summary(self) -> Optional[str]:
        """Reverse-scan forum.log for latest [HOST] entry."""
        forum_file = self.log_dir / "forum.log"
        if not forum_file.exists():
            return None

        with open(forum_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for line in reversed(lines):
            if "[HOST]" in line:
                match = re.match(
                    r"\[\d{2}:\d{2}:\d{2}\]\s*\[HOST\]\s*(.+)", line.strip()
                )
                if match:
                    content = match.group(1).replace("\\n", "\n").strip()
                    if content != self._last_host_entry:
                        self._last_host_entry = content
                        return content
        return None

    def build_prompt_injection(self) -> str:
        """Build prompt section for host summary injection."""
        summary = self.get_latest_host_summary()
        if not summary:
            return ""
        return f"\n### Forum Host Latest Summary\n{summary}\n---\n"

    def get_all_entries(self) -> List[str]:
        """Read all entries from forum.log."""
        forum_file = self.log_dir / "forum.log"
        if not forum_file.exists():
            return []
        with open(forum_file, "r", encoding="utf-8") as f:
            return f.readlines()


class ForumEngine:
    """BettaFish-style forum engine with pub/sub log pattern.

    Replaces DebateController. Agents communicate through
    log files, not direct calls. Moderator intervenes every
    N speeches via ForumHost.

    Swarm env.step pattern controls agent selection per round.
    """

    def __init__(
        self,
        config: ForumEngineConfig,
        agents: list,
        moderator: Any,
        session_dir: Optional[Path] = None,
        stream_callback: Optional[Callable] = None,
    ) -> None:
        self.config = config
        self.agents = agents
        self.moderator = moderator
        self.session_id = str(uuid.uuid4())[:8]
        self.session_dir = session_dir or Path(f"forum_sessions/{self.session_id}")
        self.log_writer = ForumLogWriter(self.session_dir / "logs")
        self.forum_reader = ForumReader(self.session_dir / "logs")
        self.stream_callback = stream_callback

        self.current_round = 0
        self.all_posts: List[ForumPost] = []
        self.round_results: List[Dict[str, Any]] = []
        self.is_active = False
        self.status = "pending"
        self._error: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> Dict[str, Any]:
        """Run the full forum debate.

        Returns debate result with all posts, evaluations, transcript.
        """
        self.is_active = True
        self.status = "running"
        self.current_round = 0

        try:
            briefing = self._generate_briefing()
            self.log_writer.write_to_forum(
                source="SYSTEM",
                content=briefing,
                round_number=0,
                entry_type="briefing",
            )

            if self.stream_callback:
                await self.stream_callback("briefing", {"content": briefing})

            while self.is_active and self.current_round < self.config.max_rounds:
                self.current_round += 1
                round_result = await self._conduct_round()
                self.round_results.append(round_result)

                if self._should_terminate(round_result):
                    self.is_active = False

            self.status = "completed"
            return self._build_result()

        except Exception as e:
            logger.exception("ForumEngine run failed: %s", e)
            self.status = "error"
            self._error = str(e)
            return self._build_result()

    # ------------------------------------------------------------------
    # Round execution
    # ------------------------------------------------------------------

    async def _conduct_round(self) -> Dict[str, Any]:
        """Conduct one round of forum debate.

        Swarm env.step pattern:
        1. Select active agents (by activity_level)
        2. Each agent generates response
        3. Write to log files
        4. Check if moderator should intervene
        5. If yes, generate moderation and write [HOST] to forum.log
        """
        round_posts: List[ForumPost] = []

        active_agents = self._select_active_agents()
        logger.info(
            "Round %d: %d active agents of %d total",
            self.current_round,
            len(active_agents),
            len(self.agents),
        )

        for agent in active_agents:
            # Get host summary for prompt injection (BettaFish ForumReader)
            host_summary = self.forum_reader.build_prompt_injection()

            # Get recent context (last few posts)
            context = self._get_recent_context(max_posts=8)

            # Agent generates response
            post = await agent.generate_response(
                topic=self._get_topic(),
                context=context,
                round_number=self.current_round,
                host_summary=host_summary if host_summary else None,
                stream_callback=self.stream_callback,
            )

            # Write to agent's log file AND forum.log
            self.log_writer.write(agent.config.agent_id, post)
            self.log_writer.write_to_forum(
                source=agent.config.agent_id,
                content=post.content,
                round_number=self.current_round,
            )

            round_posts.append(post)
            self.all_posts.append(post)

            # Record speech for moderator trigger
            self.moderator.record_speech()

            # Check if moderator should intervene
            if self.moderator.should_intervene():
                await self._moderator_intervention()

            # Notify stream callback
            if self.stream_callback:
                await self.stream_callback("post", post.model_dump(mode="json"))

        return {"round": self.current_round, "posts": round_posts}

    # ------------------------------------------------------------------
    # Moderator
    # ------------------------------------------------------------------

    async def _moderator_intervention(self) -> None:
        """Trigger moderator to generate summary/guidance."""
        recent = self._get_recent_log_entries(count=self.config.speech_trigger)

        moderation = await self.moderator.generate_moderation(
            recent_entries=recent,
            topic=self._get_topic(),
        )

        self.log_writer.write_to_forum(
            source="HOST",
            content=moderation,
            round_number=self.current_round,
            entry_type="intervention",
        )

        logger.info("Moderator intervention at round %d", self.current_round)

        if self.stream_callback:
            await self.stream_callback("moderation", {"content": moderation})

    # ------------------------------------------------------------------
    # Swarm env.step: agent selection
    # ------------------------------------------------------------------

    def _select_active_agents(self) -> list:
        """Select agents for this round using Swarm env.step pattern.

        Uses activity_level as selection probability.
        Guarantees at least 2 agents participate.
        Sorts by influence_weight (higher influence speaks first).
        """
        active = []
        for agent in self.agents:
            if random.random() < agent.config.activity_level:
                active.append(agent)

        # Ensure at least 2 agents participate
        if len(active) < 2 and len(self.agents) >= 2:
            active = random.sample(self.agents, min(2, len(self.agents)))

        # Sort by influence_weight (higher influence speaks first)
        active.sort(key=lambda a: a.config.influence_weight, reverse=True)

        return active

    # ------------------------------------------------------------------
    # Termination conditions
    # ------------------------------------------------------------------

    def _should_terminate(self, round_result: Dict[str, Any]) -> bool:
        """Check termination conditions.

        1. Max rounds reached
        2. Moderator declared consensus or deadlock
        3. Repetition detection (placeholder for Phase 3 embedding similarity)
        """
        if self.current_round >= self.config.max_rounds:
            return True

        # Check latest host entry for consensus/deadlock keywords
        host_summary = self.forum_reader.get_latest_host_summary()
        if host_summary:
            consensus_keywords = [
                "합의", "수렴", "동의", "consensus", "agreement",
                "교착", "평행선", "반복", "deadlock", "stalemate",
            ]
            lower_summary = host_summary.lower()
            if any(kw in lower_summary for kw in consensus_keywords):
                logger.info("Moderator declared consensus/deadlock. Terminating.")
                return True

        # Repetition detection via embedding similarity (Phase 3)
        if self.current_round >= 2:
            current_round_texts = [
                p.content for p in self.all_posts if p.round == self.current_round
            ]
            prev_round_texts = [
                p.content for p in self.all_posts if p.round == self.current_round - 1
            ]
            if current_round_texts and prev_round_texts:
                try:
                    from evaluation.embeddings import EmbeddingSimilarity

                    sim = EmbeddingSimilarity()
                    if sim.detect_repetition(
                        current_round_texts,
                        prev_round_texts,
                        self.config.convergence_threshold,
                    ):
                        logger.info("Repetition detected between rounds. Terminating.")
                        return True
                except Exception:
                    pass  # Embedding not available, skip

        return False

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _get_topic(self) -> str:
        """Get the debate topic from config."""
        return self.config.topic

    def _get_recent_context(self, max_posts: int = 8) -> str:
        """Get recent posts as context string for agents.

        Returns formatted text of the last N posts, including
        agent labels and content.
        """
        if not self.all_posts:
            return ""

        recent = self.all_posts[-max_posts:]
        context_parts: list[str] = []

        for post in recent:
            # Find the agent label for display
            agent_label = post.agent_id
            for agent in self.agents:
                if agent.config.agent_id == post.agent_id:
                    agent_label = agent.config.label
                    break

            context_parts.append(
                f"[{agent_label}] (Round {post.round}): {post.content}"
            )

        return "\n\n".join(context_parts)

    def _get_recent_log_entries(self, count: int = 5) -> List[LogEntry]:
        """Get recent log entries from all_posts as LogEntry objects.

        Used by moderator for generating intervention summaries.
        """
        recent_posts = self.all_posts[-count:] if self.all_posts else []
        entries: list[LogEntry] = []

        for post in recent_posts:
            entries.append(
                LogEntry(
                    timestamp=post.timestamp,
                    source=post.agent_id,
                    content=post.content,
                    round_number=post.round,
                    entry_type="argument",
                )
            )

        return entries

    def _generate_briefing(self) -> str:
        """Generate initial debate briefing with topic and participant info."""
        agent_info_parts: list[str] = []
        for agent in self.agents:
            agent_info_parts.append(
                f"  - {agent.config.label} "
                f"(weight: {agent.config.weight:.1%}, "
                f"activity: {agent.config.activity_level:.1f})"
            )
        agent_info = "\n".join(agent_info_parts)

        preset_name = self.config.confrontation_level.upper()

        return (
            f"=== FORUM DEBATE BRIEFING ===\n"
            f"Topic: {self.config.topic}\n"
            f"Max Rounds: {self.config.max_rounds}\n"
            f"Confrontation Level: {preset_name}\n"
            f"Speech Trigger: Every {self.config.speech_trigger} speeches\n"
            f"Participants:\n{agent_info}\n"
            f"============================="
        )

    def _build_result(self) -> Dict[str, Any]:
        """Build the final debate result dictionary.

        Includes session metadata, all posts, round summaries,
        transcript content, and error information if applicable.
        """
        # Build transcript from forum.log
        transcript_lines = self.forum_reader.get_all_entries()
        transcript = "".join(transcript_lines)

        # Build per-agent summary
        agent_summaries: list[dict[str, Any]] = []
        for agent in self.agents:
            agent_posts = [p for p in self.all_posts if p.agent_id == agent.config.agent_id]
            agent_summaries.append(
                {
                    "agent_id": agent.config.agent_id,
                    "label": agent.config.label,
                    "cluster_id": agent.config.cluster_id,
                    "weight": agent.config.weight,
                    "post_count": len(agent_posts),
                    "influence_weight": agent.config.influence_weight,
                }
            )

        # Build round summaries
        round_summaries: list[dict[str, Any]] = []
        for rr in self.round_results:
            posts_in_round = rr.get("posts", [])
            round_summaries.append(
                {
                    "round": rr["round"],
                    "post_count": len(posts_in_round),
                    "agents": [p.agent_id for p in posts_in_round],
                    "key_points": [
                        {
                            "agent_id": p.agent_id,
                            "content_preview": (
                                p.content[:200] + "..."
                                if len(p.content) > 200
                                else p.content
                            ),
                        }
                        for p in posts_in_round
                    ],
                }
            )

        return {
            "session_id": self.session_id,
            "status": self.status,
            "topic": self.config.topic,
            "total_rounds": self.current_round,
            "total_posts": len(self.all_posts),
            "posts": [p.model_dump(mode="json") for p in self.all_posts],
            "agent_summaries": agent_summaries,
            "round_summaries": round_summaries,
            "transcript": transcript,
            "config": {
                "max_rounds": self.config.max_rounds,
                "speech_trigger": self.config.speech_trigger,
                "confrontation_level": self.config.confrontation_level,
                "convergence_threshold": self.config.convergence_threshold,
                "allow_cross_team": self.config.allow_cross_team,
                "team_integration": self.config.team_integration,
            },
            "error": self._error,
        }

    # ------------------------------------------------------------------
    # State inspection (for API endpoints)
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Return current engine status for API polling."""
        return {
            "session_id": self.session_id,
            "status": self.status,
            "current_round": self.current_round,
            "max_rounds": self.config.max_rounds,
            "total_posts": len(self.all_posts),
            "is_active": self.is_active,
        }
