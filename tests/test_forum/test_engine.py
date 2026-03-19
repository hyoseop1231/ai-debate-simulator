"""Tests for forum.engine -- ForumLogWriter, ForumReader, ForumEngineConfig."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

from forum.config import ForumEngineConfig
from forum.engine import ForumLogWriter, ForumReader
from models.schemas import ForumPost


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    """Create a temporary log directory."""
    d = tmp_path / "logs"
    d.mkdir()
    return d


@pytest.fixture
def writer(log_dir: Path) -> ForumLogWriter:
    return ForumLogWriter(log_dir)


@pytest.fixture
def reader(log_dir: Path) -> ForumReader:
    return ForumReader(log_dir)


@pytest.fixture
def sample_post() -> ForumPost:
    return ForumPost(
        post_id="post-test-001",
        agent_id="agent-0-safety",
        round=1,
        timestamp=datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        content="AI alignment is critical for safe deployment of large models.",
        cluster_id=0,
        influence_weight=1.0,
    )


class TestForumLogWriter:
    """test_forum_log_writer: writes JSONL correctly."""

    def test_writes_jsonl_file(
        self, writer: ForumLogWriter, sample_post: ForumPost, log_dir: Path
    ) -> None:
        writer.write("agent-0-safety", sample_post)

        log_file = log_dir / "agent-0-safety.jsonl"
        assert log_file.exists()

        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1

        data = json.loads(lines[0])
        assert data["post_id"] == "post-test-001"
        assert data["agent_id"] == "agent-0-safety"
        assert data["content"] == sample_post.content

    def test_writes_multiple_posts(
        self, writer: ForumLogWriter, log_dir: Path
    ) -> None:
        for i in range(3):
            post = ForumPost(
                post_id=f"post-{i}",
                agent_id="agent-0",
                round=1,
                content=f"Post content {i}",
            )
            writer.write("agent-0", post)

        log_file = log_dir / "agent-0.jsonl"
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 3

    def test_write_to_forum(
        self, writer: ForumLogWriter, log_dir: Path
    ) -> None:
        writer.write_to_forum(
            source="AGENT-0",
            content="Test forum entry content",
            round_number=1,
            entry_type="argument",
        )

        forum_file = log_dir / "forum.log"
        assert forum_file.exists()

        with open(forum_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "[AGENT-0]" in content
        assert "Test forum entry content" in content


class TestForumReaderHostEntry:
    """test_forum_reader_host_entry: finds [HOST] entries."""

    def test_finds_host_entry(
        self, writer: ForumLogWriter, reader: ForumReader
    ) -> None:
        writer.write_to_forum("AGENT-0", "agent speech", 1)
        writer.write_to_forum("HOST", "Moderator summary of the debate so far.", 1)
        writer.write_to_forum("AGENT-1", "another speech", 1)

        summary = reader.get_latest_host_summary()
        assert summary is not None
        assert "Moderator summary" in summary

    def test_returns_latest_host_entry(
        self, writer: ForumLogWriter, reader: ForumReader
    ) -> None:
        writer.write_to_forum("HOST", "First host summary", 1)
        writer.write_to_forum("HOST", "Second host summary", 2)

        summary = reader.get_latest_host_summary()
        assert summary is not None
        assert "Second host summary" in summary


class TestForumReaderNoHost:
    """test_forum_reader_no_host: returns None when no host entries."""

    def test_returns_none_no_host_entries(
        self, writer: ForumLogWriter, reader: ForumReader
    ) -> None:
        writer.write_to_forum("AGENT-0", "agent speech only", 1)
        summary = reader.get_latest_host_summary()
        assert summary is None

    def test_returns_none_no_forum_file(self, reader: ForumReader) -> None:
        summary = reader.get_latest_host_summary()
        assert summary is None

    def test_get_all_entries_empty(self, reader: ForumReader) -> None:
        entries = reader.get_all_entries()
        assert entries == []


class TestForumReaderPromptInjection:
    """Test build_prompt_injection returns formatted section or empty string."""

    def test_with_host_entry(
        self, writer: ForumLogWriter, reader: ForumReader
    ) -> None:
        writer.write_to_forum("HOST", "Summary text here", 1)
        injection = reader.build_prompt_injection()
        assert "### Forum Host Latest Summary" in injection
        assert "Summary text here" in injection

    def test_without_host_entry(self, reader: ForumReader) -> None:
        injection = reader.build_prompt_injection()
        assert injection == ""


class TestForumConfigPresets:
    """test_forum_config_presets: adversarial/collaborative/competitive presets."""

    def test_adversarial_preset(self) -> None:
        config = ForumEngineConfig.adversarial()
        assert config.confrontation_level == "high"
        assert config.allow_cross_team is True
        assert config.max_rounds == 5

    def test_collaborative_preset(self) -> None:
        config = ForumEngineConfig.collaborative()
        assert config.confrontation_level == "low"
        assert config.team_integration is True
        assert config.max_rounds == 3

    def test_competitive_preset(self) -> None:
        config = ForumEngineConfig.competitive()
        assert config.confrontation_level == "medium"
        assert config.max_rounds == 5
        assert config.speech_trigger == 3

    def test_default_config(self) -> None:
        config = ForumEngineConfig()
        assert config.max_rounds == 5
        assert config.speech_trigger == 5
        assert config.convergence_threshold == 0.85
        assert config.topic == ""
