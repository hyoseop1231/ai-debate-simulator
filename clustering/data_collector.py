"""L0 Data Collector -- collects seed data from multiple sources and normalizes to Document[]."""

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from models.schemas import Document

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 2000


class ArxivFetcher:
    """Fetches papers from arXiv API."""

    # @MX:NOTE: [AUTO] Rate limit enforced at 3s between requests per arXiv API policy
    RATE_LIMIT_SECONDS = 3.0

    async def fetch(self, query: str, max_results: int = 10) -> List[Document]:
        """Search arXiv for papers matching query. Return abstracts as Documents."""
        try:
            import arxiv
        except ImportError:
            logger.warning("arxiv package not installed, skipping arXiv fetch")
            return []

        documents: List[Document] = []
        try:
            client = arxiv.Client()
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance,
            )

            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None, lambda: list(client.results(search))
            )

            for result in results:
                content = f"{result.title}\n\n{result.summary}"
                doc = Document(
                    id=str(uuid.uuid4()),
                    source="arxiv",
                    title=result.title,
                    content=content[:MAX_CONTENT_LENGTH],
                    url=result.entry_id,
                    timestamp=result.published,
                    metadata={
                        "authors": [a.name for a in result.authors[:5]],
                        "categories": result.categories,
                    },
                )
                documents.append(doc)
                await asyncio.sleep(self.RATE_LIMIT_SECONDS)

        except Exception:
            logger.exception("Failed to fetch from arXiv for query: %s", query)

        logger.info("ArxivFetcher collected %d documents for query '%s'", len(documents), query)
        return documents


class RSSFetcher:
    """Fetches news articles from RSS feeds."""

    DEFAULT_FEEDS = [
        "https://news.ycombinator.com/rss",
        "https://rss.arxiv.org/rss/cs.AI",
    ]

    async def fetch(
        self,
        feeds: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
        max_results: int = 20,
    ) -> List[Document]:
        """Parse RSS feeds and filter by keywords."""
        try:
            import feedparser
        except ImportError:
            logger.warning("feedparser package not installed, skipping RSS fetch")
            return []

        feed_urls = feeds or self.DEFAULT_FEEDS
        documents: List[Document] = []

        for feed_url in feed_urls:
            try:
                loop = asyncio.get_event_loop()
                parsed = await loop.run_in_executor(
                    None, feedparser.parse, feed_url
                )

                for entry in parsed.entries:
                    if len(documents) >= max_results:
                        break

                    title = getattr(entry, "title", "")
                    summary = getattr(entry, "summary", "")
                    combined_text = f"{title} {summary}".lower()

                    if keywords and not any(kw.lower() in combined_text for kw in keywords):
                        continue

                    content = f"{title}\n\n{summary}" if summary else title
                    published = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        try:
                            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        except (TypeError, ValueError):
                            published = None

                    doc = Document(
                        id=str(uuid.uuid4()),
                        source="rss",
                        title=title,
                        content=content[:MAX_CONTENT_LENGTH],
                        url=getattr(entry, "link", None),
                        timestamp=published,
                        metadata={"feed": feed_url},
                    )
                    documents.append(doc)

                if len(documents) >= max_results:
                    break

            except Exception:
                logger.exception("Failed to parse RSS feed: %s", feed_url)

        logger.info("RSSFetcher collected %d documents", len(documents))
        return documents


class UserTextIngester:
    """Processes user-provided seed text."""

    def ingest(self, texts: List[str], topic: str = "") -> List[Document]:
        """Convert raw text inputs to Documents."""
        documents: List[Document] = []
        for text in texts:
            if not text or not text.strip():
                continue
            content = text.strip()[:MAX_CONTENT_LENGTH]
            title = content[:80].split("\n")[0]
            doc = Document(
                id=str(uuid.uuid4()),
                source="user",
                title=title,
                content=content,
                url=None,
                timestamp=datetime.now(tz=timezone.utc),
                metadata={"topic": topic} if topic else {},
            )
            documents.append(doc)

        logger.info("UserTextIngester ingested %d documents", len(documents))
        return documents


class DataCollector:
    """Unified data collector -- optional pre-step for the pipeline."""

    def __init__(self, sources: Optional[List[str]] = None) -> None:
        self.sources = sources or ["user"]
        self._arxiv_fetcher = ArxivFetcher()
        self._rss_fetcher = RSSFetcher()
        self._user_ingester = UserTextIngester()

    async def collect(
        self,
        topic: str,
        max_docs: int = 50,
        user_texts: Optional[List[str]] = None,
    ) -> List[Document]:
        """Collect documents from all configured sources."""
        tasks: List[asyncio.Task[List[Document]]] = []
        per_source_max = max(1, max_docs // max(len(self.sources), 1))

        for source in self.sources:
            if source == "arxiv":
                tasks.append(
                    asyncio.create_task(
                        self._arxiv_fetcher.fetch(topic, max_results=per_source_max)
                    )
                )
            elif source == "rss":
                tasks.append(
                    asyncio.create_task(
                        self._rss_fetcher.fetch(
                            keywords=[topic] if topic else None,
                            max_results=per_source_max,
                        )
                    )
                )
            elif source == "user":
                # Wrap sync call in a coroutine
                async def _ingest_user() -> List[Document]:
                    return self._user_ingester.ingest(user_texts or [], topic=topic)

                tasks.append(asyncio.create_task(_ingest_user()))
            else:
                logger.warning("Unknown source: %s, skipping", source)

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_docs: List[Document] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Source collection failed: %s", result)
                continue
            all_docs.extend(result)

        # Deduplicate by content hash
        deduped = self._deduplicate(all_docs)

        # Limit to max_docs
        deduped = deduped[:max_docs]

        logger.info(
            "DataCollector collected %d documents (%d before dedup) for topic '%s'",
            len(deduped),
            len(all_docs),
            topic,
        )
        return deduped

    @staticmethod
    def _deduplicate(documents: List[Document]) -> List[Document]:
        """Deduplicate documents by content hash."""
        seen_hashes: set[str] = set()
        unique: List[Document] = []
        for doc in documents:
            content_hash = hashlib.sha256(doc.content.encode("utf-8")).hexdigest()
            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                unique.append(doc)
        return unique
