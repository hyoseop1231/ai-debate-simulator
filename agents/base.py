"""Base LLM agent with shared HTTP/streaming logic extracted from debate_agent.py."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Callable, Optional

import httpx


logger = logging.getLogger(__name__)


class BaseLLMAgent:
    """Shared LLM calling infrastructure for all agent types.

    Provides retry logic, SSE streaming, API health checks,
    thinking-content extraction, and response quality analysis.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        api_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.openrouter_api_url: str = api_url or os.getenv(
            "OPENROUTER_API_URL", "https://openrouter.ai/api/v1"
        )
        self.openrouter_api_key: str = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.model: str = model or os.getenv("DEFAULT_MODEL", "qwen2.5-coder:32b")
        self.temperature: float = temperature
        self._logger: logging.Logger = logging.getLogger(
            f"{self.__class__.__name__}"
        )

    # ------------------------------------------------------------------
    # API health check
    # ------------------------------------------------------------------

    async def _check_api_health(self) -> bool:
        """Verify that the OpenRouter (or compatible) API is reachable."""
        if not self.openrouter_api_key:
            self._logger.warning("OPENROUTER_API_KEY not set")
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.openrouter_api_url}/models",
                    headers={"Authorization": f"Bearer {self.openrouter_api_key}"},
                )
                return response.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Core LLM call with 3-retry + exponential backoff
    # ------------------------------------------------------------------

    async def _call_llm(
        self,
        prompt: str,
        stream_callback: Optional[Callable[..., Any]] = None,
        *,
        system_prompt: str = "",
        max_tokens: int = 800,
    ) -> dict[str, Any]:
        """Call the LLM API with retry and optional streaming.

        Returns a dict with keys: content, evidence, confidence, quality_score.
        On total failure, returns a fallback dict.
        """
        self._logger.debug(
            "API Key check: %s",
            f"{self.openrouter_api_key[:20]}..." if self.openrouter_api_key else "missing",
        )

        if not await self._check_api_health():
            self._logger.warning("OpenRouter API connection failed")
            return self._default_fallback()

        api_url = f"{self.openrouter_api_url}/chat/completions"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://ai-debate-simulator.local",
            "X-Title": "AI Debate Simulator",
        }

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": bool(stream_callback),
            "temperature": self.temperature,
            "top_p": 0.95,
            "max_tokens": max_tokens,
        }

        max_retries = 3
        retry_delay = 1

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(60.0, connect=15.0),
                    limits=httpx.Limits(
                        max_keepalive_connections=5, max_connections=10
                    ),
                    follow_redirects=True,
                ) as client:
                    if stream_callback:
                        actual_content = await self._handle_streaming_response(
                            client, api_url, headers, payload, stream_callback
                        )

                        analysis_result = self._analyze_response_quality(
                            actual_content
                        )

                        return {
                            "content": analysis_result["cleaned_content"],
                            "evidence": analysis_result["evidence"],
                            "confidence": analysis_result["confidence"],
                            "quality_score": analysis_result["quality_score"],
                        }
                    else:
                        response = await client.post(
                            api_url, headers=headers, json=payload
                        )
                        response.raise_for_status()

                        data = response.json()
                        content = (
                            data.get("choices", [{}])[0]
                            .get("message", {})
                            .get("content", "")
                            .strip()
                        )

                        if not content:
                            raise ValueError("Empty response received")

                        analysis_result = self._analyze_response_quality(content)

                        return {
                            "content": analysis_result["cleaned_content"],
                            "evidence": analysis_result["evidence"],
                            "confidence": analysis_result["confidence"],
                            "quality_score": analysis_result["quality_score"],
                        }

            except Exception as e:
                self._logger.warning("LLM call attempt %d failed: %s", attempt + 1, e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    self._logger.error("LLM call failed after all retries: %s", e)

        return self._default_fallback()

    # ------------------------------------------------------------------
    # SSE streaming handler
    # ------------------------------------------------------------------

    async def _handle_streaming_response(
        self,
        client: httpx.AsyncClient,
        api_url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        stream_callback: Callable[..., Any],
    ) -> str:
        """Parse an SSE stream from the LLM API and relay chunks via callback."""
        actual_content = ""
        self._logger.info("Streaming started")

        async with client.stream(
            "POST", api_url, headers=headers, json=payload
        ) as response:
            response.raise_for_status()
            self._logger.debug(
                "Streaming response status=%d", response.status_code
            )

            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                if not line.startswith("data: "):
                    continue

                data_str = line[6:]
                if data_str == "[DONE]":
                    self._logger.debug("Streaming DONE signal received")
                    break

                try:
                    chunk_data = json.loads(data_str)
                    choices = chunk_data.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    chunk = delta.get("content", "")

                    if chunk:
                        actual_content += chunk
                        self._logger.debug("Chunk received: %d chars", len(chunk))
                        await stream_callback("content_chunk", chunk)
                        await asyncio.sleep(0.03)
                except json.JSONDecodeError:
                    continue

        if not actual_content.strip():
            default_msg = "[Error occurred during response generation]"
            await stream_callback("content_chunk", default_msg)
            actual_content = default_msg

        self._logger.info("Streaming complete - %d chars", len(actual_content))
        return actual_content

    # ------------------------------------------------------------------
    # Thinking content extraction
    # ------------------------------------------------------------------

    def _extract_response_from_thinking(self, thinking_content: str) -> str:
        """Extract an actual response from thinking/reasoning content.

        Some models place conversational content inside thinking tags.
        This method detects such cases and returns usable text.
        """
        if not thinking_content:
            return ""

        # Conversational indicators (Korean)
        conversational_indicators = [
            "그런데", "하지만", "사실", "정말", "진짜", "아니", "맞아",
            "그래", "네", "예", "생각해보면", "그렇지만", "그러나",
            "따라서", "그래서", "그러므로", "어요", "습니다", "죠",
            "거야", "거죠", "잖아", "거든", "해요",
        ]

        # Question/rebuttal indicators
        question_indicators = ["?", "까요", "인가요", "일까요", "가요", "죠?"]

        # Opinion indicators
        opinion_indicators = ["생각", "의견", "관점", "입장", "견해", "판단"]

        is_conversational = any(
            indicator in thinking_content for indicator in conversational_indicators
        )
        is_question = any(
            indicator in thinking_content for indicator in question_indicators
        )
        is_opinion = any(
            indicator in thinking_content for indicator in opinion_indicators
        )

        if is_conversational or is_question or is_opinion:
            response = thinking_content.strip()

            # Truncate if too long
            if len(response) > 300:
                sentences = response.split(".")
                response = ". ".join(sentences[:3]) + "."

            # Remove meta-references to thinking process
            meta_phrases = [
                "생각해보니", "생각해보면", "생각을 해보면",
                "고민해보니", "고민해보면",
                "분석해보니", "분석해보면",
                "판단해보니", "판단해보면",
            ]

            for phrase in meta_phrases:
                if response.startswith(phrase):
                    response = response[len(phrase):].strip()
                    if response.startswith(","):
                        response = response[1:].strip()
                    break

            return response

        # If thinking content is too meta, build a generic response from keywords
        if len(thinking_content) > 50:
            keywords: list[str] = []
            important_words = thinking_content.split()

            for word in important_words[:20]:
                if len(word) > 2 and word not in [
                    "그런데", "하지만", "생각", "아니", "진짜",
                ]:
                    keywords.append(word)
                    if len(keywords) >= 3:
                        break

            if keywords:
                return (
                    f"흥미로운 점이 있네요. {' '.join(keywords[:2])}에 대해 "
                    "생각해보면 복잡한 문제인 것 같습니다. "
                    "좀 더 자세히 살펴볼 필요가 있을 것 같아요."
                )

        return ""

    # ------------------------------------------------------------------
    # Response quality analysis
    # ------------------------------------------------------------------

    def _analyze_response_quality(self, content: str) -> dict[str, Any]:
        """Analyze and score a response for evidence, logic, and quality."""
        cleaned_content = content.strip()

        # Evidence extraction (enhanced patterns)
        evidence: list[str] = []
        evidence_patterns = [
            "연구에 따르면", "데이터에 의하면", "통계적으로", "전문가들은",
            "보고서에서", "조사 결과", "실험을 통해", "분석에 따르면",
            "예를 들어", "실제로", "구체적으로", "사실",
        ]

        sentences = cleaned_content.replace("!", ".").replace("?", ".").split(".")
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and any(
                pattern in sentence for pattern in evidence_patterns
            ):
                evidence.append(sentence)
                if len(evidence) >= 3:
                    break

        # Quality score (KITECH-style criteria)
        quality_score = 0.5

        # Length appropriateness (50-300 chars optimal)
        if 50 <= len(cleaned_content) <= 300:
            quality_score += 0.1

        # Logical structure (connectors)
        logical_connectors = [
            "따라서", "그러므로", "왜냐하면", "또한",
            "하지만", "그러나", "반면에",
        ]
        if any(conn in cleaned_content for conn in logical_connectors):
            quality_score += 0.1

        # Specificity (numbers, proper nouns)
        if re.search(r"\d+", cleaned_content) or any(
            char.isupper() for char in cleaned_content
        ):
            quality_score += 0.1

        # Emotional tone appropriateness
        emotional_words = ["놀랍게도", "확실히", "분명히", "당연히", "절대적으로"]
        if any(word in cleaned_content for word in emotional_words):
            quality_score += 0.05

        # Confidence calculation
        confidence = quality_score
        if evidence:
            confidence += 0.15
        if len(cleaned_content) > 100:
            confidence += 0.05

        return {
            "cleaned_content": cleaned_content,
            "evidence": evidence[:3],
            "confidence": min(confidence, 0.95),
            "quality_score": min(quality_score, 1.0),
        }

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _default_fallback(self) -> dict[str, Any]:
        """Return a minimal fallback response when LLM calls fail."""
        return {
            "content": "[Response generation failed. Please retry.]",
            "evidence": [],
            "confidence": 0.0,
            "quality_score": 0.0,
        }
