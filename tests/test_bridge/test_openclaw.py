"""Tests for bridge.openclaw -- OpenClawBridge and formatters."""

from __future__ import annotations

import json
from typing import List

import pytest

from bridge.openclaw import (
    BaseFormatter,
    DiscordFormatter,
    OpenClawBridge,
    TelegramFormatter,
)
from models.schemas import PipelineResult, PredictionResult


class TestTelegramFormat:
    """test_telegram_format: proper markdown."""

    def test_telegram_format_contains_topic(
        self, sample_pipeline_result: PipelineResult
    ) -> None:
        formatter = TelegramFormatter()
        messages = formatter.format(sample_pipeline_result)

        assert len(messages) >= 1
        full_text = "\n".join(messages)
        assert "AI Safety" in full_text

    def test_telegram_format_contains_dominant_opinion(
        self, sample_pipeline_result: PipelineResult
    ) -> None:
        formatter = TelegramFormatter()
        messages = formatter.format(sample_pipeline_result)
        full_text = "\n".join(messages)
        assert "ai-safety-alignment" in full_text

    def test_telegram_format_uses_markdown_bold(
        self, sample_pipeline_result: PipelineResult
    ) -> None:
        formatter = TelegramFormatter()
        messages = formatter.format(sample_pipeline_result)
        full_text = "\n".join(messages)
        # Telegram uses * for bold
        assert "*" in full_text

    def test_telegram_format_contains_confidence(
        self, sample_pipeline_result: PipelineResult
    ) -> None:
        formatter = TelegramFormatter()
        messages = formatter.format(sample_pipeline_result)
        full_text = "\n".join(messages)
        assert "75%" in full_text

    def test_telegram_no_prediction(self) -> None:
        result = PipelineResult(
            pipeline_id="test",
            status="completed",
        )
        formatter = TelegramFormatter()
        messages = formatter.format(result)
        assert len(messages) >= 1


class TestDiscordFormat:
    """test_discord_format: valid embed JSON."""

    def test_discord_format_valid_json(
        self, sample_pipeline_result: PipelineResult
    ) -> None:
        formatter = DiscordFormatter()
        messages = formatter.format(sample_pipeline_result)

        assert len(messages) == 1
        data = json.loads(messages[0])
        assert "embeds" in data
        assert isinstance(data["embeds"], list)
        assert len(data["embeds"]) == 1

    def test_discord_embed_has_title(
        self, sample_pipeline_result: PipelineResult
    ) -> None:
        formatter = DiscordFormatter()
        messages = formatter.format(sample_pipeline_result)
        data = json.loads(messages[0])
        embed = data["embeds"][0]
        assert "title" in embed
        assert "color" in embed

    def test_discord_embed_has_fields(
        self, sample_pipeline_result: PipelineResult
    ) -> None:
        formatter = DiscordFormatter()
        messages = formatter.format(sample_pipeline_result)
        data = json.loads(messages[0])
        embed = data["embeds"][0]
        assert "fields" in embed
        field_names = {f["name"] for f in embed["fields"]}
        assert "우세 의견" in field_names
        assert "신뢰도" in field_names

    def test_discord_color_for_neutral(self) -> None:
        result = PipelineResult(
            pipeline_id="test",
            status="completed",
            prediction=PredictionResult(
                topic="Test",
                dominant_opinion="neutral-position",
                confidence=0.5,
                consensus_level=0.5,
            ),
        )
        formatter = DiscordFormatter()
        messages = formatter.format(result)
        data = json.loads(messages[0])
        embed = data["embeds"][0]
        assert embed["color"] == 0x95A5A6  # neutral gray


class TestMessageSplitting:
    """test_message_splitting: long messages split correctly."""

    def test_short_message_not_split(self) -> None:
        formatter = TelegramFormatter()
        short_text = "Short message"
        chunks = formatter._split_message(short_text)
        assert len(chunks) == 1
        assert chunks[0] == short_text

    def test_long_message_split(self) -> None:
        formatter = TelegramFormatter()
        # Create a message longer than 4096 chars
        long_text = "\n".join([f"Line {i}: " + "x" * 80 for i in range(100)])
        assert len(long_text) > 4096

        chunks = formatter._split_message(long_text)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= formatter.MAX_MESSAGE_LENGTH

    def test_split_preserves_all_content(self) -> None:
        formatter = TelegramFormatter()
        lines = [f"Line {i}" for i in range(200)]
        long_text = "\n".join(lines)

        chunks = formatter._split_message(long_text)
        reconstructed = "\n".join(chunks)
        # All original lines should appear in reconstructed text
        for line in lines:
            assert line in reconstructed

    def test_discord_max_length(self) -> None:
        formatter = DiscordFormatter()
        assert formatter.MAX_MESSAGE_LENGTH == 4096


class TestOpenClawBridge:
    """Test OpenClawBridge integration."""

    def test_format_for_telegram(
        self, sample_pipeline_result: PipelineResult
    ) -> None:
        bridge = OpenClawBridge()
        messages = bridge.format_for_channel(sample_pipeline_result, "telegram")
        assert len(messages) >= 1

    def test_format_for_discord(
        self, sample_pipeline_result: PipelineResult
    ) -> None:
        bridge = OpenClawBridge()
        messages = bridge.format_for_channel(sample_pipeline_result, "discord")
        assert len(messages) >= 1
        # Discord messages should be valid JSON
        data = json.loads(messages[0])
        assert "embeds" in data

    def test_format_for_unknown_channel_falls_back_to_telegram(
        self, sample_pipeline_result: PipelineResult
    ) -> None:
        bridge = OpenClawBridge()
        messages = bridge.format_for_channel(sample_pipeline_result, "unknown_channel")
        # Should fall back to telegram formatter
        assert len(messages) >= 1

    def test_build_openclaw_response(
        self, sample_pipeline_result: PipelineResult
    ) -> None:
        bridge = OpenClawBridge()
        response = bridge.build_openclaw_response(sample_pipeline_result)
        assert response["pipeline_id"] == "test-pipeline-001"
        assert response["status"] == "completed"
        assert "messages" in response
        assert "metadata" in response
        assert response["metadata"]["topic"] == "AI Safety and Governance"

    def test_save_to_workspace_without_dir(
        self, sample_pipeline_result: PipelineResult
    ) -> None:
        bridge = OpenClawBridge(workspace_dir=None)
        result = bridge.save_to_workspace("test-id", sample_pipeline_result)
        assert result is None

    def test_save_to_workspace(
        self, tmp_path, sample_pipeline_result: PipelineResult
    ) -> None:
        bridge = OpenClawBridge(workspace_dir=str(tmp_path))
        path = bridge.save_to_workspace("test-pipeline", sample_pipeline_result)

        assert path is not None
        saved_dir = tmp_path / "test-pipeline"
        assert saved_dir.exists()
        assert (saved_dir / "context.json").exists()
        assert (saved_dir / "clusters.json").exists()
        assert (saved_dir / "evaluation.json").exists()
        assert (saved_dir / "report.md").exists()
