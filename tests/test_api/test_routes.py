"""Tests for API routes -- health, models, forum start validation."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app."""
    # Set required env vars and yield inside the patch context so that
    # requests made during the test also see the patched environment.
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key-12345"}):
        from api.app import app

        yield TestClient(app)


@pytest.fixture
def client_no_key():
    """TestClient without API key set."""
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False):
        from api.app import app

        yield TestClient(app)


class TestHealthEndpoint:
    """test_health_endpoint: returns 200."""

    def test_health_returns_200_with_api_key(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "checks" in data
        assert "timestamp" in data

    def test_status_endpoint(self, client: TestClient) -> None:
        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "online"
        assert "version" in data

    def test_health_degraded_without_key(self, client_no_key: TestClient) -> None:
        response = client_no_key.get("/api/health")
        # Without API key, status should be degraded (503)
        data = response.json()
        assert data["checks"]["openrouter"] == "unhealthy"


class TestModelsEndpoint:
    """test_models_endpoint: returns model list."""

    def test_models_returns_list(self, client: TestClient) -> None:
        response = client.get("/api/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data
        assert data["success"] is True
        assert isinstance(data["models"], list)
        assert len(data["models"]) > 0

    def test_models_have_required_fields(self, client: TestClient) -> None:
        response = client.get("/api/models")
        data = response.json()
        for model in data["models"]:
            assert "name" in model
            assert "display_name" in model
            assert "provider" in model


class TestForumStartValidation:
    """test_forum_start_validation: rejects empty topic."""

    def test_rejects_empty_topic(self, client: TestClient) -> None:
        response = client.post(
            "/api/forum/start",
            json={"topic": ""},
        )
        assert response.status_code == 422  # Validation error

    def test_rejects_whitespace_only_topic(self, client: TestClient) -> None:
        response = client.post(
            "/api/forum/start",
            json={"topic": "   "},
        )
        # After sanitization, topic becomes empty -> validation error
        assert response.status_code == 422

    def test_sanitizes_xss_in_topic(self, client: TestClient) -> None:
        """Topic with HTML tags should be sanitized."""
        response = client.post(
            "/api/forum/start",
            json={
                "topic": '<script>alert("xss")</script>AI Safety',
                "max_rounds": 1,
            },
        )
        # Should not contain script tags if the request proceeds
        if response.status_code == 200:
            data = response.json()
            assert "<script>" not in data.get("topic", "")

    def test_forum_status_not_found(self, client: TestClient) -> None:
        response = client.get("/api/forum/nonexistent-session/status")
        assert response.status_code == 404

    def test_forum_result_not_found(self, client: TestClient) -> None:
        response = client.get("/api/forum/nonexistent-session/result")
        assert response.status_code == 404

    def test_forum_transcript_not_found(self, client: TestClient) -> None:
        response = client.get("/api/forum/nonexistent-session/transcript")
        assert response.status_code == 404
