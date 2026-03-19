"""Tests for agents.moderator -- ForumHost."""

from __future__ import annotations

import logging
from typing import List

import pytest

from agents.moderator import ForumHost
from models.schemas import LogEntry


@pytest.fixture
def different_model_host() -> ForumHost:
    """ForumHost with different model from debate agents."""
    return ForumHost(
        model="moderator-model",
        debate_agent_model="agent-model",
        api_url="http://localhost:11434/v1",
        api_key="test",
        speech_trigger=3,
    )


@pytest.fixture
def same_model_host() -> ForumHost:
    """ForumHost with same model as debate agents (anti-pattern)."""
    return ForumHost(
        model="same-model",
        debate_agent_model="same-model",
        api_url="http://localhost:11434/v1",
        api_key="test",
        speech_trigger=5,
    )


class TestModelSeparationWarning:
    """test_model_separation_warning: same model logs warning."""

    def test_same_model_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            ForumHost(
                model="shared-model",
                debate_agent_model="shared-model",
                api_url="http://localhost:11434/v1",
                api_key="test",
            )
        assert any("same as agent model" in record.message for record in caplog.records)

    def test_different_model_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            ForumHost(
                model="moderator-model",
                debate_agent_model="agent-model",
                api_url="http://localhost:11434/v1",
                api_key="test",
            )
        homogenization_warnings = [
            r for r in caplog.records if "same as agent model" in r.message
        ]
        assert len(homogenization_warnings) == 0


class TestValidateModelSeparation:
    """test_validate_model_separation: returns True/False correctly."""

    def test_returns_true_for_different_models(
        self, different_model_host: ForumHost
    ) -> None:
        assert different_model_host.validate_model_separation() is True

    def test_returns_false_for_same_models(
        self, same_model_host: ForumHost
    ) -> None:
        assert same_model_host.validate_model_separation() is False


class TestShouldIntervene:
    """test_should_intervene: triggers at speech_trigger count."""

    def test_does_not_intervene_below_trigger(
        self, different_model_host: ForumHost
    ) -> None:
        # speech_trigger=3, record 2 speeches
        different_model_host.record_speech()
        different_model_host.record_speech()
        assert different_model_host.should_intervene() is False

    def test_intervenes_at_trigger(self, different_model_host: ForumHost) -> None:
        # speech_trigger=3, record 3 speeches
        for _ in range(3):
            different_model_host.record_speech()
        assert different_model_host.should_intervene() is True

    def test_intervenes_above_trigger(self, different_model_host: ForumHost) -> None:
        for _ in range(5):
            different_model_host.record_speech()
        assert different_model_host.should_intervene() is True


class TestRecordAndReset:
    """test_record_and_reset: speech counter resets after moderation."""

    @pytest.mark.asyncio
    async def test_counter_resets_after_moderation(
        self, different_model_host: ForumHost
    ) -> None:
        # Record enough speeches to trigger
        for _ in range(3):
            different_model_host.record_speech()
        assert different_model_host.should_intervene() is True

        # generate_moderation resets the counter
        entries = [
            LogEntry(
                source="agent-0",
                content="Test speech content",
                round_number=1,
            )
        ]
        # Mock the LLM call to avoid real API calls
        different_model_host._call_llm = lambda *a, **kw: _mock_llm_result()
        await different_model_host.generate_moderation(entries, "test topic")

        assert different_model_host.speeches_since_last == 0
        assert different_model_host.should_intervene() is False

    def test_record_increments_counter(self, different_model_host: ForumHost) -> None:
        assert different_model_host.speeches_since_last == 0
        different_model_host.record_speech()
        assert different_model_host.speeches_since_last == 1
        different_model_host.record_speech()
        assert different_model_host.speeches_since_last == 2


class TestFormatEntries:
    """Test _format_entries helper."""

    def test_format_entries_empty(self, different_model_host: ForumHost) -> None:
        result = different_model_host._format_entries([])
        assert "아직 발언이 없습니다" in result

    def test_format_entries_truncates_long_content(
        self, different_model_host: ForumHost
    ) -> None:
        entry = LogEntry(
            source="agent-0",
            content="X" * 500,
            round_number=1,
        )
        result = different_model_host._format_entries([entry])
        assert "..." in result
        assert len(result) < 500


async def _mock_llm_result():
    """Helper to return a mock LLM response."""
    return {"content": "Mock moderation summary.", "evidence": [], "confidence": 0.5, "quality_score": 0.5}
