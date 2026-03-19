"""Multi-node Ollama endpoint registry for distributed debate agents."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Minimum model tier: gpt-oss:20b equivalent (~13GB+)
MIN_MODEL_TIER = "gpt-oss:20b"


@dataclass
class OllamaNode:
    """Single Ollama node definition."""

    name: str
    api_url: str  # e.g. "http://100.115.195.128:11434/v1"
    api_key: str = "ollama"
    models: List[str] = field(default_factory=list)
    priority: int = 0  # lower = higher priority
    healthy: bool = True
    last_check: float = 0.0


class NodeRegistry:
    """Manages multiple Ollama nodes with health checking and routing."""

    HEALTH_TTL = 30.0  # seconds

    def __init__(self, nodes: Optional[List[OllamaNode]] = None) -> None:
        self.nodes: Dict[str, OllamaNode] = {}
        if nodes:
            for node in nodes:
                self.nodes[node.name] = node

    @classmethod
    def from_config(cls, config: List[Dict]) -> NodeRegistry:
        """Create registry from config dicts.

        config format:
        [
            {"name": "bigboy1", "api_url": "http://...", "models": ["gpt-oss:120b"]},
            ...
        ]
        """
        nodes = [
            OllamaNode(
                name=c.get("name", f"node-{i}"),
                api_url=c["api_url"] if "api_url" in c else c.get("url", ""),
                api_key=c.get("api_key", "ollama"),
                models=c.get("models", []),
                priority=c.get("priority", i),
            )
            for i, c in enumerate(config)
        ]
        return cls(nodes)

    @classmethod
    def from_env(cls) -> NodeRegistry:
        """Create registry from OLLAMA_NODES env var.

        Format: name1=url1,name2=url2,...
        """
        nodes_str = os.getenv("OLLAMA_NODES", "")
        if not nodes_str:
            api_url = os.getenv("OPENROUTER_API_URL", "http://localhost:11434/v1")
            api_key = os.getenv("OPENROUTER_API_KEY", "ollama")
            return cls([OllamaNode(name="default", api_url=api_url, api_key=api_key)])

        nodes = []
        for i, pair in enumerate(nodes_str.split(",")):
            pair = pair.strip()
            if "=" in pair:
                name, url = pair.split("=", 1)
                nodes.append(
                    OllamaNode(name=name.strip(), api_url=url.strip(), priority=i)
                )
            else:
                nodes.append(
                    OllamaNode(name=f"node-{i}", api_url=pair.strip(), priority=i)
                )
        return cls(nodes)

    def get_node(self, name: str) -> Optional[OllamaNode]:
        """Get node by name."""
        return self.nodes.get(name)

    def get_healthy_nodes(self) -> List[OllamaNode]:
        """Return healthy nodes sorted by priority."""
        return sorted(
            [n for n in self.nodes.values() if n.healthy],
            key=lambda n: n.priority,
        )

    def assign_round_robin(self, count: int) -> List[OllamaNode]:
        """Assign nodes round-robin for `count` agents."""
        healthy = self.get_healthy_nodes()
        if not healthy:
            raise RuntimeError("No healthy Ollama nodes available")
        return [healthy[i % len(healthy)] for i in range(count)]

    def assign_by_mapping(self, mapping: Dict[int, str]) -> Dict[int, OllamaNode]:
        """Assign nodes by explicit cluster_id -> node_name mapping."""
        result = {}
        for cluster_id, node_name in mapping.items():
            node = self.get_node(node_name)
            if node and node.healthy:
                result[cluster_id] = node
            else:
                healthy = self.get_healthy_nodes()
                if healthy:
                    result[cluster_id] = healthy[0]
                    logger.warning(
                        "Node '%s' unavailable for cluster %d, falling back to '%s'",
                        node_name,
                        cluster_id,
                        healthy[0].name,
                    )
                else:
                    raise RuntimeError(f"No healthy node for cluster {cluster_id}")
        return result

    async def health_check_all(self) -> Dict[str, bool]:
        """Check health of all nodes concurrently."""
        results: Dict[str, bool] = {}

        async def _check(node: OllamaNode) -> None:
            now = time.time()
            if now - node.last_check < self.HEALTH_TTL:
                results[node.name] = node.healthy
                return
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{node.api_url}/models",
                        headers={"Authorization": f"Bearer {node.api_key}"},
                    )
                    node.healthy = resp.status_code == 200
                    if node.healthy and not node.models:
                        data = resp.json()
                        if "data" in data:
                            node.models = [m["id"] for m in data["data"]]
            except Exception as e:
                logger.warning("Health check failed for %s: %s", node.name, e)
                node.healthy = False
            node.last_check = now
            results[node.name] = node.healthy

        await asyncio.gather(*[_check(n) for n in self.nodes.values()])
        return results

    def summary(self) -> List[Dict]:
        """Return node status summary."""
        return [
            {
                "name": n.name,
                "api_url": n.api_url,
                "models": n.models,
                "healthy": n.healthy,
                "priority": n.priority,
            }
            for n in sorted(self.nodes.values(), key=lambda x: x.priority)
        ]
