"""Tests for report.generator -- ReportGenerator."""

from __future__ import annotations

import json
from typing import List

import pytest

from models.schemas import ClusterProfile, ForumPost, PredictionResult
from report.generator import ReportGenerator


@pytest.fixture
def generator() -> ReportGenerator:
    return ReportGenerator()


class TestMarkdownReport:
    """test_markdown_report: contains expected sections."""

    def test_markdown_contains_all_sections(
        self,
        generator: ReportGenerator,
        sample_clusters: List[ClusterProfile],
        sample_posts: List[ForumPost],
        sample_prediction: PredictionResult,
    ) -> None:
        report = generator.generate(
            topic="AI Safety and Governance",
            clusters=sample_clusters,
            posts=sample_posts,
            prediction=sample_prediction,
            format="markdown",
        )

        assert "# AI Debate Report:" in report
        assert "## 1. Summary" in report
        assert "## 2. Opinion Distribution" in report
        assert "## 3. Key Issues" in report
        assert "## 4. Debate Highlights" in report
        assert "## 5. Prediction Basis" in report
        assert "## 6. Counter-arguments" in report

    def test_markdown_contains_topic(
        self,
        generator: ReportGenerator,
        sample_clusters: List[ClusterProfile],
        sample_posts: List[ForumPost],
        sample_prediction: PredictionResult,
    ) -> None:
        report = generator.generate(
            topic="AI Safety and Governance",
            clusters=sample_clusters,
            posts=sample_posts,
            prediction=sample_prediction,
            format="markdown",
        )
        assert "AI Safety and Governance" in report

    def test_markdown_contains_cluster_labels(
        self,
        generator: ReportGenerator,
        sample_clusters: List[ClusterProfile],
        sample_posts: List[ForumPost],
        sample_prediction: PredictionResult,
    ) -> None:
        report = generator.generate(
            topic="Test",
            clusters=sample_clusters,
            posts=sample_posts,
            prediction=sample_prediction,
            format="markdown",
        )
        for cluster in sample_clusters:
            assert cluster.label in report

    def test_markdown_contains_dominant_opinion(
        self,
        generator: ReportGenerator,
        sample_clusters: List[ClusterProfile],
        sample_posts: List[ForumPost],
        sample_prediction: PredictionResult,
    ) -> None:
        report = generator.generate(
            topic="Test",
            clusters=sample_clusters,
            posts=sample_posts,
            prediction=sample_prediction,
            format="markdown",
        )
        assert sample_prediction.dominant_opinion in report


class TestJsonReport:
    """test_json_report: valid JSON."""

    def test_json_is_valid(
        self,
        generator: ReportGenerator,
        sample_clusters: List[ClusterProfile],
        sample_posts: List[ForumPost],
        sample_prediction: PredictionResult,
    ) -> None:
        report = generator.generate(
            topic="AI Safety",
            clusters=sample_clusters,
            posts=sample_posts,
            prediction=sample_prediction,
            format="json",
        )
        data = json.loads(report)
        assert isinstance(data, dict)

    def test_json_contains_sections(
        self,
        generator: ReportGenerator,
        sample_clusters: List[ClusterProfile],
        sample_posts: List[ForumPost],
        sample_prediction: PredictionResult,
    ) -> None:
        report = generator.generate(
            topic="AI Safety",
            clusters=sample_clusters,
            posts=sample_posts,
            prediction=sample_prediction,
            format="json",
        )
        data = json.loads(report)
        assert "summary" in data
        assert "opinion_distribution" in data
        assert "key_issues" in data
        assert "highlights" in data
        assert "prediction_basis" in data
        assert "counter_arguments" in data
        assert "metadata" in data

    def test_json_metadata_fields(
        self,
        generator: ReportGenerator,
        sample_clusters: List[ClusterProfile],
        sample_posts: List[ForumPost],
        sample_prediction: PredictionResult,
    ) -> None:
        report = generator.generate(
            topic="AI Safety",
            clusters=sample_clusters,
            posts=sample_posts,
            prediction=sample_prediction,
            format="json",
        )
        data = json.loads(report)
        meta = data["metadata"]
        assert meta["topic"] == "AI Safety"
        assert meta["cluster_count"] == 3
        assert meta["post_count"] == 4


class TestHtmlReport:
    """test_html_report: contains plotly script tag."""

    def test_html_contains_plotly(
        self,
        generator: ReportGenerator,
        sample_clusters: List[ClusterProfile],
        sample_posts: List[ForumPost],
        sample_prediction: PredictionResult,
    ) -> None:
        report = generator.generate(
            topic="AI Safety",
            clusters=sample_clusters,
            posts=sample_posts,
            prediction=sample_prediction,
            format="html",
        )
        assert "plotly" in report.lower()
        assert "<script" in report

    def test_html_is_valid_document(
        self,
        generator: ReportGenerator,
        sample_clusters: List[ClusterProfile],
        sample_posts: List[ForumPost],
        sample_prediction: PredictionResult,
    ) -> None:
        report = generator.generate(
            topic="AI Safety",
            clusters=sample_clusters,
            posts=sample_posts,
            prediction=sample_prediction,
            format="html",
        )
        assert "<!DOCTYPE html>" in report
        assert "</html>" in report
        assert "<body>" in report

    def test_html_escapes_topic(
        self,
        generator: ReportGenerator,
        sample_clusters: List[ClusterProfile],
        sample_posts: List[ForumPost],
        sample_prediction: PredictionResult,
    ) -> None:
        report = generator.generate(
            topic="AI <Safety> & Governance",
            clusters=sample_clusters,
            posts=sample_posts,
            prediction=sample_prediction,
            format="html",
        )
        # HTML should escape special characters
        assert "&lt;Safety&gt;" in report or "AI" in report

    def test_html_contains_chart_divs(
        self,
        generator: ReportGenerator,
        sample_clusters: List[ClusterProfile],
        sample_posts: List[ForumPost],
        sample_prediction: PredictionResult,
    ) -> None:
        report = generator.generate(
            topic="AI Safety",
            clusters=sample_clusters,
            posts=sample_posts,
            prediction=sample_prediction,
            format="html",
        )
        assert 'id="pie-chart"' in report
        assert 'id="bar-chart"' in report


class TestReportEdgeCases:
    """Test report generation edge cases."""

    def test_empty_predictions(self, generator: ReportGenerator) -> None:
        prediction = PredictionResult(
            topic="Empty",
            cluster_predictions=[],
            dominant_opinion="",
            confidence=0.0,
            consensus_level=0.0,
        )
        report = generator.generate(
            topic="Empty",
            clusters=[],
            posts=[],
            prediction=prediction,
            format="markdown",
        )
        assert "No sufficient data" in report

    def test_with_moderator_summaries(
        self,
        generator: ReportGenerator,
        sample_clusters: List[ClusterProfile],
        sample_posts: List[ForumPost],
        sample_prediction: PredictionResult,
    ) -> None:
        report = generator.generate(
            topic="Test",
            clusters=sample_clusters,
            posts=sample_posts,
            prediction=sample_prediction,
            moderator_summaries=["The debate shows strong polarization."],
            format="markdown",
        )
        assert isinstance(report, str)
        assert len(report) > 0
