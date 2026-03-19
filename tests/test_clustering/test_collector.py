"""Tests for clustering.data_collector -- UserTextIngester and DataCollector."""

from __future__ import annotations

from typing import List

import pytest

from clustering.data_collector import MAX_CONTENT_LENGTH, DataCollector, UserTextIngester
from models.schemas import Document


class TestUserTextIngester:
    """test_user_text_ingester: basic ingest."""

    def test_basic_ingest(self) -> None:
        ingester = UserTextIngester()
        texts = [
            "AI safety is an important field of research.",
            "Climate change affects global food production.",
        ]
        docs = ingester.ingest(texts, topic="general")

        assert len(docs) == 2
        for doc in docs:
            assert doc.source == "user"
            assert doc.id  # non-empty
            assert doc.content
            assert doc.title

    def test_empty_texts_skipped(self) -> None:
        ingester = UserTextIngester()
        texts = ["valid text", "", "  ", "another valid text"]
        docs = ingester.ingest(texts)
        assert len(docs) == 2

    def test_topic_stored_in_metadata(self) -> None:
        ingester = UserTextIngester()
        docs = ingester.ingest(["some text"], topic="AI Ethics")
        assert docs[0].metadata.get("topic") == "AI Ethics"

    def test_no_topic_empty_metadata(self) -> None:
        ingester = UserTextIngester()
        docs = ingester.ingest(["some text"], topic="")
        assert "topic" not in docs[0].metadata


class TestIngesterTruncation:
    """test_ingester_truncation: content > 2000 chars truncated."""

    def test_content_truncated_at_max_length(self) -> None:
        ingester = UserTextIngester()
        long_text = "A" * 5000
        docs = ingester.ingest([long_text])

        assert len(docs) == 1
        assert len(docs[0].content) <= MAX_CONTENT_LENGTH

    def test_short_content_not_truncated(self) -> None:
        ingester = UserTextIngester()
        short_text = "Short content."
        docs = ingester.ingest([short_text])
        assert docs[0].content == short_text


class TestIngesterDedup:
    """test_ingester_dedup: duplicate texts handled by DataCollector._deduplicate."""

    def test_deduplicate_removes_exact_duplicates(self) -> None:
        docs = [
            Document(id="d1", source="test", title="T1", content="Same content here"),
            Document(id="d2", source="test", title="T2", content="Same content here"),
            Document(id="d3", source="test", title="T3", content="Different content"),
        ]
        deduped = DataCollector._deduplicate(docs)
        assert len(deduped) == 2

    def test_deduplicate_preserves_order(self) -> None:
        docs = [
            Document(id="d1", source="test", title="First", content="AAA"),
            Document(id="d2", source="test", title="Second", content="BBB"),
            Document(id="d3", source="test", title="Third", content="AAA"),
        ]
        deduped = DataCollector._deduplicate(docs)
        assert deduped[0].id == "d1"
        assert deduped[1].id == "d2"

    def test_deduplicate_empty_list(self) -> None:
        assert DataCollector._deduplicate([]) == []


class TestDataCollectorAsync:
    """Async tests for DataCollector.collect using user source only."""

    @pytest.mark.asyncio
    async def test_collect_user_texts(self) -> None:
        collector = DataCollector(sources=["user"])
        docs = await collector.collect(
            topic="test",
            max_docs=10,
            user_texts=["Text one", "Text two"],
        )
        assert len(docs) == 2

    @pytest.mark.asyncio
    async def test_collect_unknown_source_skipped(self) -> None:
        collector = DataCollector(sources=["nonexistent"])
        docs = await collector.collect(topic="test", max_docs=10)
        assert docs == []

    @pytest.mark.asyncio
    async def test_collect_max_docs_limit(self) -> None:
        collector = DataCollector(sources=["user"])
        many_texts = [f"Text {i}" for i in range(20)]
        docs = await collector.collect(topic="test", max_docs=5, user_texts=many_texts)
        assert len(docs) <= 5
