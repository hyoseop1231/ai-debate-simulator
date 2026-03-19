"""ReACT-pattern report generator for L5.

Produces structured debate reports from pipeline output.
Supports Markdown (default), JSON, and HTML output formats.

Report structure (from ARCHITECTURE.md):
1. Summary -- 1-paragraph conclusion
2. Opinion Distribution -- cluster weights + weighted scores (chart)
3. Key Issues -- Top 5 most-discussed points
4. Debate Highlights -- 3-5 key exchanges selected by moderator
5. Prediction Basis -- surviving arguments + sources
6. Counter-arguments -- minority opinion key rebuttals
"""

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from html import escape as html_escape
from typing import Dict, List, Optional

from models.schemas import (
    ClusterPrediction,
    ClusterProfile,
    ForumPost,
    PredictionResult,
)

logger = logging.getLogger(__name__)


# @MX:ANCHOR: [AUTO] Report generator -- public API consumed by pipeline orchestrator and API layer
# @MX:REASON: fan_in >= 3 (pipeline, API, CLI)
class ReportGenerator:
    """ReACT-pattern report generator for debate results.

    Generates structured reports from debate pipeline output.
    Supports Markdown, JSON, and HTML formats.
    """

    def generate(
        self,
        topic: str,
        clusters: List[ClusterProfile],
        posts: List[ForumPost],
        prediction: PredictionResult,
        moderator_summaries: Optional[List[str]] = None,
        format: str = "markdown",
    ) -> str:
        """Generate a complete debate report.

        Args:
            topic: Debate topic.
            clusters: Opinion clusters from L1.
            posts: All ForumPosts from L3.
            prediction: Prediction result from L4.
            moderator_summaries: Host interventions from L3.
            format: ``"markdown"``, ``"json"``, or ``"html"``.

        Returns:
            Formatted report string.
        """
        logger.info("Generating %s report for topic: %s", format, topic)

        sections = self._build_sections(
            topic, clusters, posts, prediction, moderator_summaries
        )

        if format == "json":
            return self._render_json(sections)
        elif format == "html":
            return self._render_html(sections, topic)
        else:
            return self._render_markdown(sections, topic)

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_sections(
        self,
        topic: str,
        clusters: List[ClusterProfile],
        posts: List[ForumPost],
        prediction: PredictionResult,
        moderator_summaries: Optional[List[str]],
    ) -> Dict:
        """Build all report sections."""
        return {
            "summary": self._build_summary(topic, prediction),
            "opinion_distribution": self._build_distribution(clusters, prediction),
            "key_issues": self._build_key_issues(posts, clusters),
            "highlights": self._build_highlights(posts, moderator_summaries),
            "prediction_basis": self._build_prediction_basis(prediction),
            "counter_arguments": self._build_counter_arguments(prediction),
            "metadata": self._build_metadata(topic, clusters, posts),
        }

    def _build_summary(self, topic: str, prediction: PredictionResult) -> str:
        """Build a 1-paragraph conclusion from prediction results."""
        if not prediction.cluster_predictions:
            return f"No sufficient data to generate a conclusion for the topic: {topic}."

        dominant = prediction.cluster_predictions[0]
        dominant_pct = f"{dominant.weighted_score * 100:.1f}%"
        confidence_label = self._confidence_label(prediction.confidence)
        consensus_label = self._consensus_label(prediction.consensus_level)

        surviving_summary = ""
        if dominant.key_arguments_survived:
            top_args = dominant.key_arguments_survived[:3]
            surviving_summary = (
                " Key supporting arguments include: "
                + "; ".join(f'"{a[:80]}"' for a in top_args)
                + "."
            )

        minority_note = ""
        if len(prediction.cluster_predictions) > 1:
            second = prediction.cluster_predictions[1]
            minority_note = (
                f" However, the minority view \"{second.cluster_label}\" "
                f"({second.weighted_score * 100:.1f}%) presented notable counter-arguments."
            )

        return (
            f'On the topic of "{topic}", the dominant opinion is '
            f'"{dominant.cluster_label}" with a weighted score of {dominant_pct} '
            f"({confidence_label} confidence, {consensus_label} consensus)."
            f"{surviving_summary}{minority_note}"
        )

    def _build_distribution(
        self, clusters: List[ClusterProfile], prediction: PredictionResult
    ) -> Dict:
        """Build opinion distribution with weights and scores."""
        pred_map: Dict[str, ClusterPrediction] = {
            cp.cluster_label: cp for cp in prediction.cluster_predictions
        }

        rows = []
        for cluster in clusters:
            cp = pred_map.get(cluster.label)
            rows.append(
                {
                    "cluster_label": cluster.label,
                    "cluster_id": cluster.cluster_id,
                    "weight": cluster.weight,
                    "debate_score": cp.debate_score if cp else 0.0,
                    "weighted_score": cp.weighted_score if cp else 0.0,
                    "stance_shift": cp.stance_shift if cp else 0.0,
                    "document_count": cluster.document_count,
                }
            )

        # Sort by weighted score descending
        rows.sort(key=lambda r: r["weighted_score"], reverse=True)

        return {
            "rows": rows,
            "chart_data": {
                "pie": ChartGenerator.opinion_pie_chart(clusters),
                "bar": ChartGenerator.weighted_score_bar_chart(
                    prediction.cluster_predictions
                ),
            },
        }

    def _build_key_issues(
        self, posts: List[ForumPost], clusters: List[ClusterProfile]
    ) -> List[Dict]:
        """Extract top 5 most-discussed points across all posts."""
        cluster_label_map: Dict[int, str] = {
            c.cluster_id: c.label for c in clusters
        }

        # Collect all keywords from clusters
        all_keywords: List[str] = []
        for cluster in clusters:
            all_keywords.extend(cluster.keywords)

        # Count keyword occurrences in post content (case-insensitive)
        keyword_counts: Counter = Counter()
        keyword_sources: Dict[str, set] = defaultdict(set)
        keyword_posts: Dict[str, int] = Counter()

        for kw in set(all_keywords):
            kw_lower = kw.lower()
            for post in posts:
                if kw_lower in post.content.lower():
                    keyword_counts[kw] += 1
                    keyword_posts[kw] += 1
                    if post.cluster_id is not None:
                        label = cluster_label_map.get(post.cluster_id, f"Cluster {post.cluster_id}")
                        keyword_sources[kw].add(label)

        # If no keywords found, extract from post content directly
        if not keyword_counts and posts:
            # Fallback: use first sentence fragments as issue proxies
            for post in posts:
                first_sentence = post.content.split(".")[0].strip()
                if len(first_sentence) > 10:
                    short = first_sentence[:80]
                    keyword_counts[short] += 1
                    if post.cluster_id is not None:
                        label = cluster_label_map.get(post.cluster_id, f"Cluster {post.cluster_id}")
                        keyword_sources[short].add(label)

        top_issues = keyword_counts.most_common(5)
        result = []
        for keyword, count in top_issues:
            result.append(
                {
                    "issue": keyword,
                    "mention_count": count,
                    "source_clusters": sorted(keyword_sources.get(keyword, set())),
                }
            )
        return result

    def _build_highlights(
        self,
        posts: List[ForumPost],
        moderator_summaries: Optional[List[str]],
    ) -> List[Dict]:
        """Select 3-5 key debate exchanges."""
        # Build reply chains: find posts that have the most replies
        reply_counts: Counter = Counter()
        reply_map: Dict[str, List[ForumPost]] = defaultdict(list)
        post_map: Dict[str, ForumPost] = {p.post_id: p for p in posts}

        for post in posts:
            if post.reply_to and post.reply_to in post_map:
                reply_counts[post.reply_to] += 1
                reply_map[post.reply_to].append(post)

        highlights: List[Dict] = []

        # Top exchanges by reply count
        for parent_id, count in reply_counts.most_common(5):
            parent = post_map.get(parent_id)
            if parent is None:
                continue

            replies = sorted(reply_map[parent_id], key=lambda p: p.timestamp)
            best_reply = replies[0] if replies else None

            highlight = {
                "original_post": {
                    "post_id": parent.post_id,
                    "agent_id": parent.agent_id,
                    "cluster_id": parent.cluster_id,
                    "round": parent.round,
                    "content": parent.content,
                },
                "reply_count": count,
                "key_reply": None,
            }

            if best_reply:
                highlight["key_reply"] = {
                    "post_id": best_reply.post_id,
                    "agent_id": best_reply.agent_id,
                    "cluster_id": best_reply.cluster_id,
                    "round": best_reply.round,
                    "content": best_reply.content,
                }

            highlights.append(highlight)

            if len(highlights) >= 5:
                break

        # If we have fewer than 3 highlights and moderator summaries exist,
        # use those as supplementary highlights
        if moderator_summaries and len(highlights) < 3:
            for summary in moderator_summaries[: 3 - len(highlights)]:
                highlights.append(
                    {
                        "original_post": None,
                        "reply_count": 0,
                        "key_reply": None,
                        "moderator_summary": summary,
                    }
                )

        # Ensure at least 3 if we have enough posts
        if len(highlights) < 3 and posts:
            # Fill with high influence-weight posts
            sorted_posts = sorted(posts, key=lambda p: p.influence_weight, reverse=True)
            for post in sorted_posts:
                if post.post_id not in {
                    h.get("original_post", {}).get("post_id")
                    for h in highlights
                    if h.get("original_post")
                }:
                    highlights.append(
                        {
                            "original_post": {
                                "post_id": post.post_id,
                                "agent_id": post.agent_id,
                                "cluster_id": post.cluster_id,
                                "round": post.round,
                                "content": post.content,
                            },
                            "reply_count": 0,
                            "key_reply": None,
                        }
                    )
                    if len(highlights) >= 3:
                        break

        return highlights[:5]

    def _build_prediction_basis(self, prediction: PredictionResult) -> Dict:
        """Build surviving arguments from the dominant opinion."""
        if not prediction.cluster_predictions:
            return {"cluster_label": "", "arguments": [], "confidence": 0.0}

        dominant = prediction.cluster_predictions[0]
        return {
            "cluster_label": dominant.cluster_label,
            "arguments": dominant.key_arguments_survived,
            "confidence": prediction.confidence,
            "weighted_score": dominant.weighted_score,
            "stance_shift": dominant.stance_shift,
        }

    def _build_counter_arguments(self, prediction: PredictionResult) -> List[Dict]:
        """Build minority opinion key rebuttals for bias prevention."""
        if len(prediction.cluster_predictions) <= 1:
            return []

        counters = []
        for cp in prediction.cluster_predictions[1:]:
            if cp.key_arguments_survived:
                counters.append(
                    {
                        "cluster_label": cp.cluster_label,
                        "weight": cp.weight,
                        "weighted_score": cp.weighted_score,
                        "key_rebuttals": cp.key_arguments_survived,
                    }
                )
        return counters

    def _build_metadata(
        self,
        topic: str,
        clusters: List[ClusterProfile],
        posts: List[ForumPost],
    ) -> Dict:
        """Build report metadata."""
        max_round = max((p.round for p in posts), default=0)
        return {
            "generated_at": datetime.utcnow().isoformat(),
            "topic": topic,
            "cluster_count": len(clusters),
            "post_count": len(posts),
            "total_rounds": max_round + 1 if posts else 0,
            "unique_agents": len({p.agent_id for p in posts}),
        }

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _confidence_label(confidence: float) -> str:
        """Map confidence score to human-readable label."""
        if confidence >= 0.8:
            return "high"
        elif confidence >= 0.5:
            return "moderate"
        elif confidence >= 0.3:
            return "low"
        return "very low"

    @staticmethod
    def _consensus_label(consensus: float) -> str:
        """Map consensus level to human-readable label."""
        if consensus >= 0.8:
            return "strong"
        elif consensus >= 0.5:
            return "moderate"
        elif consensus >= 0.3:
            return "weak"
        return "very weak"

    # ------------------------------------------------------------------
    # Renderers
    # ------------------------------------------------------------------

    def _render_markdown(self, sections: Dict, topic: str) -> str:
        """Render report as Markdown."""
        lines: List[str] = []
        meta = sections["metadata"]

        # Title
        lines.append(f"# AI Debate Report: {topic}")
        lines.append("")
        lines.append(
            f"*Generated: {meta['generated_at']} | "
            f"Clusters: {meta['cluster_count']} | "
            f"Posts: {meta['post_count']} | "
            f"Rounds: {meta['total_rounds']} | "
            f"Agents: {meta['unique_agents']}*"
        )
        lines.append("")

        # 1. Summary
        lines.append("## 1. Summary")
        lines.append("")
        lines.append(sections["summary"])
        lines.append("")

        # 2. Opinion Distribution
        lines.append("## 2. Opinion Distribution")
        lines.append("")
        dist = sections["opinion_distribution"]
        lines.append(
            "| Cluster | Weight | Debate Score | Weighted Score | Stance Shift |"
        )
        lines.append(
            "|---------|--------|-------------|----------------|-------------|"
        )
        for row in dist["rows"]:
            lines.append(
                f"| {row['cluster_label']} "
                f"| {row['weight']:.2%} "
                f"| {row['debate_score']:.3f} "
                f"| {row['weighted_score']:.3f} "
                f"| {row['stance_shift']:+.3f} |"
            )
        lines.append("")

        # 3. Key Issues
        lines.append("## 3. Key Issues (Top 5)")
        lines.append("")
        issues = sections["key_issues"]
        if issues:
            for i, issue in enumerate(issues, 1):
                sources = ", ".join(issue["source_clusters"]) if issue["source_clusters"] else "N/A"
                lines.append(
                    f"{i}. **{issue['issue']}** -- "
                    f"Mentioned {issue['mention_count']} times "
                    f"(Sources: {sources})"
                )
        else:
            lines.append("*No key issues identified.*")
        lines.append("")

        # 4. Debate Highlights
        lines.append("## 4. Debate Highlights")
        lines.append("")
        highlights = sections["highlights"]
        if highlights:
            for i, hl in enumerate(highlights, 1):
                lines.append(f"### Exchange {i}")
                if hl.get("moderator_summary"):
                    lines.append(f"**Moderator Summary:** {hl['moderator_summary']}")
                elif hl.get("original_post"):
                    op = hl["original_post"]
                    lines.append(
                        f"**[{op['agent_id']}] (Round {op['round']}):** "
                        f"{op['content']}"
                    )
                    if hl.get("key_reply"):
                        rp = hl["key_reply"]
                        lines.append("")
                        lines.append(
                            f"> **[{rp['agent_id']}] (Round {rp['round']}):** "
                            f"{rp['content']}"
                        )
                    if hl["reply_count"] > 1:
                        lines.append(
                            f"\n*...and {hl['reply_count'] - 1} more replies*"
                        )
                lines.append("")
        else:
            lines.append("*No notable exchanges identified.*")
            lines.append("")

        # 5. Prediction Basis
        lines.append("## 5. Prediction Basis")
        lines.append("")
        basis = sections["prediction_basis"]
        if basis["arguments"]:
            lines.append(
                f"**Dominant opinion:** {basis['cluster_label']} "
                f"(confidence: {basis['confidence']:.2%}, "
                f"weighted score: {basis['weighted_score']:.3f})"
            )
            lines.append("")
            lines.append("**Surviving arguments:**")
            lines.append("")
            for arg in basis["arguments"]:
                lines.append(f"- {arg}")
        else:
            lines.append("*No surviving arguments recorded.*")
        lines.append("")

        # 6. Counter-arguments
        lines.append("## 6. Counter-arguments (Minority Opinions)")
        lines.append("")
        counters = sections["counter_arguments"]
        if counters:
            for ca in counters:
                lines.append(
                    f"### {ca['cluster_label']} "
                    f"(weight: {ca['weight']:.2%}, "
                    f"score: {ca['weighted_score']:.3f})"
                )
                lines.append("")
                for rebuttal in ca["key_rebuttals"]:
                    lines.append(f"- {rebuttal}")
                lines.append("")
        else:
            lines.append("*No counter-arguments recorded.*")
            lines.append("")

        lines.append("---")
        lines.append("*Report generated by AI Debate Simulator v2*")
        return "\n".join(lines)

    def _render_json(self, sections: Dict) -> str:
        """Render report as JSON."""
        return json.dumps(sections, ensure_ascii=False, indent=2, default=str)

    def _render_html(self, sections: Dict, topic: str) -> str:
        """Render report as HTML with embedded plotly charts."""
        meta = sections["metadata"]
        dist = sections["opinion_distribution"]
        pie_data = dist["chart_data"]["pie"]
        bar_data = dist["chart_data"]["bar"]

        # Build HTML sections
        summary_html = f"<p>{html_escape(sections['summary'])}</p>"

        # Distribution table
        dist_rows = ""
        for row in dist["rows"]:
            dist_rows += (
                f"<tr>"
                f"<td>{html_escape(row['cluster_label'])}</td>"
                f"<td>{row['weight']:.2%}</td>"
                f"<td>{row['debate_score']:.3f}</td>"
                f"<td>{row['weighted_score']:.3f}</td>"
                f"<td>{row['stance_shift']:+.3f}</td>"
                f"</tr>\n"
            )

        # Key issues list
        issues_html = ""
        for i, issue in enumerate(sections["key_issues"], 1):
            sources = ", ".join(issue["source_clusters"]) if issue["source_clusters"] else "N/A"
            issues_html += (
                f"<li><strong>{html_escape(issue['issue'])}</strong> -- "
                f"Mentioned {issue['mention_count']} times "
                f"(Sources: {html_escape(sources)})</li>\n"
            )
        if not issues_html:
            issues_html = "<li><em>No key issues identified.</em></li>"

        # Highlights
        highlights_html = ""
        for i, hl in enumerate(sections["highlights"], 1):
            highlights_html += f'<div class="highlight">\n<h4>Exchange {i}</h4>\n'
            if hl.get("moderator_summary"):
                highlights_html += (
                    f"<p><strong>Moderator Summary:</strong> "
                    f"{html_escape(hl['moderator_summary'])}</p>\n"
                )
            elif hl.get("original_post"):
                op = hl["original_post"]
                highlights_html += (
                    f"<p><strong>[{html_escape(op['agent_id'])}] "
                    f"(Round {op['round']}):</strong> "
                    f"{html_escape(op['content'])}</p>\n"
                )
                if hl.get("key_reply"):
                    rp = hl["key_reply"]
                    highlights_html += (
                        f'<blockquote><strong>[{html_escape(rp["agent_id"])}] '
                        f"(Round {rp['round']}):</strong> "
                        f"{html_escape(rp['content'])}</blockquote>\n"
                    )
                if hl["reply_count"] > 1:
                    highlights_html += (
                        f"<p><em>...and {hl['reply_count'] - 1} more replies</em></p>\n"
                    )
            highlights_html += "</div>\n"
        if not highlights_html:
            highlights_html = "<p><em>No notable exchanges identified.</em></p>"

        # Prediction basis
        basis = sections["prediction_basis"]
        basis_html = ""
        if basis["arguments"]:
            basis_html += (
                f"<p><strong>Dominant opinion:</strong> "
                f"{html_escape(basis['cluster_label'])} "
                f"(confidence: {basis['confidence']:.2%}, "
                f"weighted score: {basis['weighted_score']:.3f})</p>\n"
                f"<p><strong>Surviving arguments:</strong></p>\n<ul>\n"
            )
            for arg in basis["arguments"]:
                basis_html += f"<li>{html_escape(arg)}</li>\n"
            basis_html += "</ul>\n"
        else:
            basis_html = "<p><em>No surviving arguments recorded.</em></p>"

        # Counter-arguments
        counters_html = ""
        for ca in sections["counter_arguments"]:
            counters_html += (
                f"<h4>{html_escape(ca['cluster_label'])} "
                f"(weight: {ca['weight']:.2%}, "
                f"score: {ca['weighted_score']:.3f})</h4>\n<ul>\n"
            )
            for rebuttal in ca["key_rebuttals"]:
                counters_html += f"<li>{html_escape(rebuttal)}</li>\n"
            counters_html += "</ul>\n"
        if not counters_html:
            counters_html = "<p><em>No counter-arguments recorded.</em></p>"

        # Plotly chart JSON
        pie_json = json.dumps(pie_data, ensure_ascii=False, default=str)
        bar_json = json.dumps(bar_data, ensure_ascii=False, default=str)

        return _HTML_TEMPLATE.format(
            title=html_escape(topic),
            meta_generated=html_escape(meta["generated_at"]),
            meta_clusters=meta["cluster_count"],
            meta_posts=meta["post_count"],
            meta_rounds=meta["total_rounds"],
            meta_agents=meta["unique_agents"],
            summary_html=summary_html,
            dist_rows=dist_rows,
            pie_json=pie_json,
            bar_json=bar_json,
            issues_html=issues_html,
            highlights_html=highlights_html,
            basis_html=basis_html,
            counters_html=counters_html,
        )


class ChartGenerator:
    """Generates plotly chart data for reports."""

    @staticmethod
    def opinion_pie_chart(clusters: List[ClusterProfile]) -> Dict:
        """Pie chart data for opinion distribution.

        Returns a plotly trace dict for a pie chart.
        """
        labels = [c.label for c in clusters]
        values = [c.weight for c in clusters]

        return {
            "data": [
                {
                    "type": "pie",
                    "labels": labels,
                    "values": values,
                    "hole": 0.3,
                    "textinfo": "label+percent",
                    "hovertemplate": "%{label}: %{value:.2%}<extra></extra>",
                    "marker": {
                        "colors": _generate_colors(len(clusters)),
                    },
                }
            ],
            "layout": {
                "title": {"text": "Opinion Distribution by Cluster Weight"},
                "showlegend": True,
                "height": 400,
            },
        }

    @staticmethod
    def weighted_score_bar_chart(predictions: List[ClusterPrediction]) -> Dict:
        """Bar chart data for weighted prediction scores.

        Returns a plotly trace dict for a bar chart.
        """
        labels = [p.cluster_label for p in predictions]
        weighted_scores = [p.weighted_score for p in predictions]
        debate_scores = [p.debate_score for p in predictions]
        colors = _generate_colors(len(predictions))

        return {
            "data": [
                {
                    "type": "bar",
                    "name": "Weighted Score",
                    "x": labels,
                    "y": weighted_scores,
                    "marker": {"color": colors},
                    "hovertemplate": "%{x}: %{y:.3f}<extra>Weighted</extra>",
                },
                {
                    "type": "bar",
                    "name": "Debate Score",
                    "x": labels,
                    "y": debate_scores,
                    "marker": {"color": colors, "opacity": 0.5},
                    "hovertemplate": "%{x}: %{y:.3f}<extra>Debate</extra>",
                },
            ],
            "layout": {
                "title": {"text": "Weighted vs Debate Scores by Cluster"},
                "barmode": "group",
                "xaxis": {"title": "Cluster"},
                "yaxis": {"title": "Score", "range": [0, 1]},
                "height": 400,
            },
        }

    @staticmethod
    def timeline_chart(posts: List[ForumPost]) -> Dict:
        """Timeline of debate activity per cluster.

        Returns a plotly trace dict with one line per cluster.
        """
        # Group posts by (cluster_id, round)
        cluster_round_counts: Dict[int, Counter] = defaultdict(Counter)
        all_rounds: set = set()

        for post in posts:
            cid = post.cluster_id if post.cluster_id is not None else -1
            cluster_round_counts[cid][post.round] += 1
            all_rounds.add(post.round)

        if not all_rounds:
            return {"data": [], "layout": {"title": {"text": "Debate Timeline"}}}

        sorted_rounds = sorted(all_rounds)
        cluster_ids = sorted(cluster_round_counts.keys())
        colors = _generate_colors(len(cluster_ids))

        traces = []
        for i, cid in enumerate(cluster_ids):
            counts = cluster_round_counts[cid]
            label = f"Cluster {cid}" if cid >= 0 else "Unassigned"
            traces.append(
                {
                    "type": "scatter",
                    "mode": "lines+markers",
                    "name": label,
                    "x": sorted_rounds,
                    "y": [counts.get(r, 0) for r in sorted_rounds],
                    "marker": {"color": colors[i % len(colors)]},
                }
            )

        return {
            "data": traces,
            "layout": {
                "title": {"text": "Debate Activity Timeline"},
                "xaxis": {"title": "Round", "dtick": 1},
                "yaxis": {"title": "Post Count"},
                "height": 400,
            },
        }


# ------------------------------------------------------------------
# Private module helpers
# ------------------------------------------------------------------

_PLOTLY_PALETTE = [
    "#636EFA",
    "#EF553B",
    "#00CC96",
    "#AB63FA",
    "#FFA15A",
    "#19D3F3",
    "#FF6692",
    "#B6E880",
    "#FF97FF",
    "#FECB52",
]


def _generate_colors(n: int) -> List[str]:
    """Generate *n* colors cycling through the plotly palette."""
    if n == 0:
        return []
    return [_PLOTLY_PALETTE[i % len(_PLOTLY_PALETTE)] for i in range(n)]


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Debate Report: {title}</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.6;
    color: #1a1a2e;
    background: #f5f5f5;
    padding: 2rem;
  }}
  .container {{ max-width: 960px; margin: 0 auto; background: #fff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); padding: 2.5rem; }}
  h1 {{ font-size: 1.8rem; margin-bottom: 0.5rem; color: #16213e; }}
  h2 {{ font-size: 1.4rem; margin-top: 2rem; margin-bottom: 0.75rem; color: #0f3460; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.25rem; }}
  h3 {{ font-size: 1.15rem; margin-top: 1.2rem; margin-bottom: 0.5rem; color: #1a1a2e; }}
  h4 {{ font-size: 1rem; margin-top: 1rem; color: #333; }}
  .meta {{ font-size: 0.85rem; color: #718096; margin-bottom: 1.5rem; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
  th, td {{ padding: 0.6rem 0.8rem; text-align: left; border-bottom: 1px solid #e2e8f0; }}
  th {{ background: #f7fafc; font-weight: 600; color: #4a5568; }}
  tr:hover {{ background: #f7fafc; }}
  ul {{ margin: 0.5rem 0 0.5rem 1.5rem; }}
  li {{ margin: 0.25rem 0; }}
  blockquote {{ border-left: 3px solid #636EFA; padding: 0.5rem 1rem; margin: 0.75rem 0; background: #f0f4ff; border-radius: 4px; }}
  .chart {{ margin: 1.5rem 0; }}
  .highlight {{ background: #fafbfc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 1rem; margin: 0.75rem 0; }}
  .footer {{ margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #e2e8f0; font-size: 0.8rem; color: #a0aec0; }}
</style>
</head>
<body>
<div class="container">

<h1>AI Debate Report: {title}</h1>
<p class="meta">Generated: {meta_generated} | Clusters: {meta_clusters} | Posts: {meta_posts} | Rounds: {meta_rounds} | Agents: {meta_agents}</p>

<h2>1. Summary</h2>
{summary_html}

<h2>2. Opinion Distribution</h2>
<table>
  <thead><tr><th>Cluster</th><th>Weight</th><th>Debate Score</th><th>Weighted Score</th><th>Stance Shift</th></tr></thead>
  <tbody>
{dist_rows}
  </tbody>
</table>

<div class="chart" id="pie-chart"></div>
<div class="chart" id="bar-chart"></div>

<h2>3. Key Issues (Top 5)</h2>
<ol>
{issues_html}
</ol>

<h2>4. Debate Highlights</h2>
{highlights_html}

<h2>5. Prediction Basis</h2>
{basis_html}

<h2>6. Counter-arguments (Minority Opinions)</h2>
{counters_html}

<div class="footer">Report generated by AI Debate Simulator v2</div>

</div>

<script>
(function() {{
  var pieSpec = {pie_json};
  var barSpec = {bar_json};
  Plotly.newPlot('pie-chart', pieSpec.data, pieSpec.layout, {{responsive: true}});
  Plotly.newPlot('bar-chart', barSpec.data, barSpec.layout, {{responsive: true}});
}})();
</script>

</body>
</html>
"""
