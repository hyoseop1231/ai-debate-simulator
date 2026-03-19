"""OpenClaw platform bridge for multi-channel debate result delivery."""

# @MX:ANCHOR: [AUTO] External system integration -- OpenClaw platform bridge
# @MX:REASON: Connects AI Debate Simulator to OpenClaw for Telegram/Discord/Slack/Web delivery

import html as html_module
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from models.schemas import ClusterPrediction, ClusterProfile, PipelineResult, PredictionResult

logger = logging.getLogger(__name__)


class OpenClawBridge:
    """Bridge between AI Debate Simulator and OpenClaw platform.

    Handles:
    - Receiving debate requests from OpenClaw
    - Formatting results for multi-channel delivery
    - Saving debate context to OpenClaw workspace memory
    """

    def __init__(self, workspace_dir: Optional[str] = None) -> None:
        self.workspace_dir = workspace_dir

    def format_for_channel(
        self, result: PipelineResult, channel: str = "telegram"
    ) -> List[str]:
        """Format pipeline result for a specific channel.

        Args:
            result: Complete pipeline result.
            channel: One of "telegram", "discord", "slack", "web".

        Returns:
            List of formatted message strings (may be split for length limits).
        """
        formatter = self._get_formatter(channel)
        return formatter.format(result)

    def _get_formatter(self, channel: str) -> "BaseFormatter":
        formatters: Dict[str, "BaseFormatter"] = {
            "telegram": TelegramFormatter(),
            "discord": DiscordFormatter(),
            "slack": SlackFormatter(),
            "web": WebFormatter(),
        }
        return formatters.get(channel, TelegramFormatter())

    def save_to_workspace(
        self, pipeline_id: str, result: PipelineResult
    ) -> Optional[str]:
        """Save debate context to OpenClaw workspace memory.

        Saves to: {workspace_dir}/{pipeline_id}/
          - context.json
          - clusters.json
          - transcript.jsonl
          - evaluation.json
          - report.md

        Returns:
            Path to the created directory, or None if workspace_dir is not set.
        """
        if not self.workspace_dir:
            logger.warning("workspace_dir not configured; skipping save")
            return None

        base = Path(self.workspace_dir) / pipeline_id
        base.mkdir(parents=True, exist_ok=True)

        # context.json
        context: Dict[str, Any] = {
            "pipeline_id": result.pipeline_id,
            "status": result.status,
            "topic": result.prediction.topic if result.prediction else "",
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        (base / "context.json").write_text(
            json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # clusters.json
        clusters_data = [c.model_dump() for c in result.clusters] if result.clusters else []
        (base / "clusters.json").write_text(
            json.dumps(clusters_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # transcript.jsonl
        transcript_lines: List[str] = []
        if result.debate_result and isinstance(result.debate_result, dict):
            posts = result.debate_result.get("posts", [])
            for post in posts:
                if isinstance(post, dict):
                    transcript_lines.append(json.dumps(post, ensure_ascii=False))
        (base / "transcript.jsonl").write_text(
            "\n".join(transcript_lines), encoding="utf-8"
        )

        # evaluation.json
        evaluation: Dict[str, Any] = {}
        if result.prediction:
            evaluation = result.prediction.model_dump()
        (base / "evaluation.json").write_text(
            json.dumps(evaluation, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # report.md
        report_content = result.report or ""
        (base / "report.md").write_text(report_content, encoding="utf-8")

        logger.info("Saved debate workspace to %s", base)
        return str(base)

    def build_openclaw_response(
        self, result: PipelineResult, channel: str = "telegram"
    ) -> Dict[str, Any]:
        """Build complete OpenClaw response payload."""
        return {
            "pipeline_id": result.pipeline_id,
            "status": result.status,
            "messages": self.format_for_channel(result, channel),
            "metadata": {
                "topic": result.prediction.topic if result.prediction else "",
                "clusters": len(result.clusters) if result.clusters else 0,
                "dominant_opinion": (
                    result.prediction.dominant_opinion if result.prediction else ""
                ),
                "confidence": (
                    result.prediction.confidence if result.prediction else 0.0
                ),
            },
        }


class BaseFormatter:
    """Base class for channel-specific formatters."""

    MAX_MESSAGE_LENGTH: int = 4096

    def format(self, result: PipelineResult) -> List[str]:
        """Format a pipeline result into a list of message strings."""
        raise NotImplementedError

    def _split_message(self, text: str) -> List[str]:
        """Split long text into chunks respecting MAX_MESSAGE_LENGTH.

        Splits at paragraph (blank-line) boundaries when possible,
        falling back to line boundaries.
        """
        if len(text) <= self.MAX_MESSAGE_LENGTH:
            return [text]

        chunks: List[str] = []
        current = ""
        for line in text.split("\n"):
            candidate = current + line + "\n"
            if len(candidate) > self.MAX_MESSAGE_LENGTH:
                if current.strip():
                    chunks.append(current.strip())
                current = line + "\n"
            else:
                current = candidate
        if current.strip():
            chunks.append(current.strip())
        return chunks

    # -- shared helpers --------------------------------------------------

    @staticmethod
    def _safe_topic(result: PipelineResult) -> str:
        if result.prediction:
            return result.prediction.topic
        return "N/A"

    @staticmethod
    def _safe_dominant(result: PipelineResult) -> str:
        if result.prediction:
            return result.prediction.dominant_opinion
        return "N/A"

    @staticmethod
    def _safe_confidence(result: PipelineResult) -> float:
        if result.prediction:
            return result.prediction.confidence
        return 0.0

    @staticmethod
    def _safe_cluster_predictions(
        result: PipelineResult,
    ) -> List[ClusterPrediction]:
        if result.prediction:
            return result.prediction.cluster_predictions
        return []

    @staticmethod
    def _safe_consensus(result: PipelineResult) -> float:
        if result.prediction:
            return result.prediction.consensus_level
        return 0.0

    @staticmethod
    def _key_issues(result: PipelineResult, limit: int = 5) -> List[str]:
        """Extract up to *limit* key arguments across clusters."""
        issues: List[str] = []
        if result.prediction:
            for cp in result.prediction.cluster_predictions:
                for arg in cp.key_arguments_survived:
                    if arg not in issues:
                        issues.append(arg)
                    if len(issues) >= limit:
                        return issues
        return issues


class TelegramFormatter(BaseFormatter):
    """Telegram MarkdownV2-compatible format.

    - Max message: 4096 chars
    - Supports: *bold*, _italic_, `code`, [link](url)
    - Split long results into multiple messages
    """

    MAX_MESSAGE_LENGTH: int = 4096

    def format(self, result: PipelineResult) -> List[str]:
        topic = self._safe_topic(result)
        dominant = self._safe_dominant(result)
        confidence = self._safe_confidence(result)
        cluster_preds = self._safe_cluster_predictions(result)
        consensus = self._safe_consensus(result)
        issues = self._key_issues(result)

        lines: List[str] = []

        lines.append(f"*토론 결과: {topic}*")
        lines.append("")
        lines.append(f"*우세 의견:* {dominant} ({confidence:.0%})")
        lines.append(f"*합의 수준:* {consensus:.0%}")
        lines.append("")

        if cluster_preds:
            lines.append("*여론 분포:*")
            for cp in cluster_preds:
                shift_indicator = ""
                if cp.stance_shift > 0:
                    shift_indicator = " ↑"
                elif cp.stance_shift < 0:
                    shift_indicator = " ↓"
                lines.append(
                    f"  - {cp.cluster_label}: {cp.weight:.0%} "
                    f"(점수: {cp.weighted_score:.2f}){shift_indicator}"
                )
            lines.append("")

        if issues:
            lines.append("*핵심 쟁점:*")
            for idx, issue in enumerate(issues, 1):
                lines.append(f"  {idx}. {issue}")
            lines.append("")

        if result.report:
            summary = result.report[:500]
            if len(result.report) > 500:
                summary += "..."
            lines.append(f"*결론:* {summary}")

        text = "\n".join(lines)
        return self._split_message(text)


class DiscordFormatter(BaseFormatter):
    """Discord Embed JSON format.

    - Max embed description: 4096 chars
    - Color coding: green=support, red=oppose, gray=neutral
    - Returns JSON strings of embed payloads
    """

    MAX_MESSAGE_LENGTH: int = 4096

    _COLOR_MAP: Dict[str, int] = {
        "support": 0x2ECC71,
        "oppose": 0xE74C3C,
        "neutral": 0x95A5A6,
    }

    def format(self, result: PipelineResult) -> List[str]:
        topic = self._safe_topic(result)
        dominant = self._safe_dominant(result)
        confidence = self._safe_confidence(result)
        cluster_preds = self._safe_cluster_predictions(result)
        consensus = self._safe_consensus(result)
        issues = self._key_issues(result)

        color = self._pick_color(dominant)

        fields: List[Dict[str, Any]] = [
            {"name": "우세 의견", "value": dominant, "inline": True},
            {"name": "신뢰도", "value": f"{confidence:.0%}", "inline": True},
            {"name": "합의 수준", "value": f"{consensus:.0%}", "inline": True},
        ]

        if cluster_preds:
            distribution_lines: List[str] = []
            for cp in cluster_preds:
                distribution_lines.append(
                    f"**{cp.cluster_label}**: {cp.weight:.0%} "
                    f"(점수: {cp.weighted_score:.2f})"
                )
            fields.append(
                {
                    "name": "여론 분포",
                    "value": "\n".join(distribution_lines),
                    "inline": False,
                }
            )

        if issues:
            issues_text = "\n".join(f"{i}. {iss}" for i, iss in enumerate(issues, 1))
            fields.append(
                {"name": "핵심 쟁점", "value": issues_text, "inline": False}
            )

        description = ""
        if result.report:
            description = result.report[:2048]
            if len(result.report) > 2048:
                description += "..."

        embed: Dict[str, Any] = {
            "title": f"토론 결과: {topic}",
            "color": color,
            "fields": fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if description:
            embed["description"] = description

        payload: Dict[str, Any] = {"embeds": [embed]}
        return [json.dumps(payload, ensure_ascii=False, indent=2)]

    def _pick_color(self, dominant_opinion: str) -> int:
        lower = dominant_opinion.lower()
        for keyword, color in self._COLOR_MAP.items():
            if keyword in lower:
                return color
        return self._COLOR_MAP["neutral"]


class SlackFormatter(BaseFormatter):
    """Slack Block Kit JSON format.

    - Max section text: 3000 chars
    - Returns JSON strings of Block Kit payloads
    """

    MAX_MESSAGE_LENGTH: int = 3000

    def format(self, result: PipelineResult) -> List[str]:
        topic = self._safe_topic(result)
        dominant = self._safe_dominant(result)
        confidence = self._safe_confidence(result)
        cluster_preds = self._safe_cluster_predictions(result)
        consensus = self._safe_consensus(result)
        issues = self._key_issues(result)

        blocks: List[Dict[str, Any]] = []

        # header
        blocks.append(
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"토론 결과: {topic}", "emoji": True},
            }
        )

        # summary section
        summary_text = (
            f"*우세 의견:* {dominant}\n"
            f"*신뢰도:* {confidence:.0%}\n"
            f"*합의 수준:* {consensus:.0%}"
        )
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": summary_text},
            }
        )

        blocks.append({"type": "divider"})

        # cluster distribution
        if cluster_preds:
            dist_lines: List[str] = []
            for cp in cluster_preds:
                dist_lines.append(
                    f"• *{cp.cluster_label}*: {cp.weight:.0%} "
                    f"(점수: {cp.weighted_score:.2f})"
                )
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "\n".join(dist_lines)},
                }
            )

        # key issues
        if issues:
            issues_lines = [f"{i}. {iss}" for i, iss in enumerate(issues, 1)]
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*핵심 쟁점:*\n" + "\n".join(issues_lines),
                    },
                }
            )

        # report excerpt
        if result.report:
            excerpt = result.report[:2000]
            if len(result.report) > 2000:
                excerpt += "..."
            blocks.append({"type": "divider"})
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*결론:*\n{excerpt}"},
                }
            )

        # context footer
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"Pipeline: `{result.pipeline_id}` | "
                            f"Status: `{result.status}`"
                        ),
                    }
                ],
            }
        )

        payload: Dict[str, Any] = {"blocks": blocks}
        return [json.dumps(payload, ensure_ascii=False, indent=2)]


class WebFormatter(BaseFormatter):
    """Web/HTML format for browser display."""

    MAX_MESSAGE_LENGTH: int = 50000

    def format(self, result: PipelineResult) -> List[str]:
        topic = self._safe_topic(result)
        dominant = self._safe_dominant(result)
        confidence = self._safe_confidence(result)
        cluster_preds = self._safe_cluster_predictions(result)
        consensus = self._safe_consensus(result)
        issues = self._key_issues(result)

        parts: List[str] = []

        parts.append(
            '<div class="debate-result" '
            'style="font-family:sans-serif;max-width:800px;margin:auto;padding:20px;">'
        )

        # title
        parts.append(f'  <h2 style="border-bottom:2px solid #333;padding-bottom:8px;">'
                      f'토론 결과: {html_module.escape(topic)}</h2>')

        # summary cards
        parts.append('  <div style="display:flex;gap:16px;margin-bottom:20px;">')
        parts.append(self._card("우세 의견", html_module.escape(dominant)))
        parts.append(self._card("신뢰도", f"{confidence:.0%}"))
        parts.append(self._card("합의 수준", f"{consensus:.0%}"))
        parts.append("  </div>")

        # cluster distribution
        if cluster_preds:
            parts.append('  <h3>여론 분포</h3>')
            parts.append('  <table style="width:100%;border-collapse:collapse;">')
            parts.append(
                "    <tr>"
                '<th style="text-align:left;padding:6px;border-bottom:1px solid #ccc;">클러스터</th>'
                '<th style="text-align:right;padding:6px;border-bottom:1px solid #ccc;">비중</th>'
                '<th style="text-align:right;padding:6px;border-bottom:1px solid #ccc;">점수</th>'
                '<th style="text-align:right;padding:6px;border-bottom:1px solid #ccc;">변화</th>'
                "</tr>"
            )
            for cp in cluster_preds:
                shift_str = f"{cp.stance_shift:+.2f}" if cp.stance_shift != 0 else "-"
                bar_width = int(cp.weight * 100)
                parts.append(
                    f"    <tr>"
                    f'<td style="padding:6px;">{html_module.escape(cp.cluster_label)}'
                    f'<div style="background:#e0e0e0;height:6px;border-radius:3px;">'
                    f'<div style="background:#4a90d9;width:{bar_width}%;height:6px;border-radius:3px;"></div>'
                    f"</div></td>"
                    f'<td style="text-align:right;padding:6px;">{cp.weight:.0%}</td>'
                    f'<td style="text-align:right;padding:6px;">{cp.weighted_score:.2f}</td>'
                    f'<td style="text-align:right;padding:6px;">{shift_str}</td>'
                    f"</tr>"
                )
            parts.append("  </table>")

        # key issues
        if issues:
            parts.append('  <h3>핵심 쟁점</h3>')
            parts.append("  <ol>")
            for issue in issues:
                parts.append(f"    <li>{html_module.escape(issue)}</li>")
            parts.append("  </ol>")

        # report
        if result.report:
            parts.append('  <h3>결론</h3>')
            parts.append(
                f'  <div style="background:#f9f9f9;padding:16px;border-radius:8px;'
                f'white-space:pre-wrap;">{html_module.escape(result.report)}</div>'
            )

        # footer
        parts.append(
            f'  <p style="color:#888;font-size:0.85em;margin-top:20px;">'
            f"Pipeline: {html_module.escape(result.pipeline_id)} | Status: {html_module.escape(result.status)}"
            f"</p>"
        )
        parts.append("</div>")

        html = "\n".join(parts)
        return self._split_message(html)

    @staticmethod
    def _card(label: str, value: str) -> str:
        return (
            f'    <div style="flex:1;background:#f5f5f5;padding:12px 16px;'
            f'border-radius:8px;text-align:center;">'
            f'<div style="font-size:0.85em;color:#666;">{label}</div>'
            f'<div style="font-size:1.3em;font-weight:bold;margin-top:4px;">{value}</div>'
            f"</div>"
        )


