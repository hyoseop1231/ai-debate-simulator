# AI Debate Simulator v2 — 멀티노드 분산 설계안

> 작성: 2026-03-19 | 목표: 토론 에이전트를 서로 다른 Ollama 노드에 분산 배정

---

## 1. 현재 구조 분석

```
PersonaFactory(api_url) ──→ ForumAgent(api_url, api_key)
                                 │
                                 └─→ BaseLLMAgent(api_url, api_key)
                                         │
                                         └─→ 단일 self.openrouter_api_url
```

**문제**: `PersonaFactory`가 하나의 `api_url`만 받아서 모든 에이전트가 같은 노드에 고정됨.

---

## 2. 사용 가능 노드

| 노드 | Tailscale URL | 주요 모델 |
|------|--------------|---------|
| bigboy1 | `http://100.115.195.128:11434/v1` | gpt-oss:120b, qwen2.5:7b, qwen2.5-coder:32b |
| bigboy2 | `http://100.77.225.102:11434/v1` | 분석용 |
| thor | `http://100.68.192.59:11434/v1` | gpt-oss:20b |

---

## 3. 아키텍처 변경 포인트

### 3.1 새 파일: `config/nodes.py` — 노드 레지스트리

```python
"""Multi-node Ollama endpoint registry."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class OllamaNode:
    """Single Ollama node definition."""
    name: str
    api_url: str  # e.g. "http://100.115.195.128:11434/v1"
    api_key: str = "ollama"
    models: List[str] = field(default_factory=list)  # available models
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
    def from_config(cls, config: List[Dict]) -> "NodeRegistry":
        """Create registry from config dicts.

        config format:
        [
            {"name": "bigboy1", "api_url": "http://...", "models": ["gpt-oss:120b"], "priority": 0},
            ...
        ]
        """
        nodes = [
            OllamaNode(
                name=c["name"],
                api_url=c["api_url"],
                api_key=c.get("api_key", "ollama"),
                models=c.get("models", []),
                priority=c.get("priority", 0),
            )
            for c in config
        ]
        return cls(nodes)

    @classmethod
    def from_env(cls) -> "NodeRegistry":
        """Create registry from OLLAMA_NODES env var.

        Format: name1=url1,name2=url2,...
        Example: OLLAMA_NODES=bigboy1=http://100.115.195.128:11434/v1,thor=http://100.68.192.59:11434/v1
        """
        import os
        nodes_str = os.getenv("OLLAMA_NODES", "")
        if not nodes_str:
            # Fallback to single-node legacy
            api_url = os.getenv("OPENROUTER_API_URL", "http://localhost:11434/v1")
            api_key = os.getenv("OPENROUTER_API_KEY", "ollama")
            return cls([OllamaNode(name="default", api_url=api_url, api_key=api_key)])

        nodes = []
        for i, pair in enumerate(nodes_str.split(",")):
            pair = pair.strip()
            if "=" in pair:
                name, url = pair.split("=", 1)
                nodes.append(OllamaNode(name=name.strip(), api_url=url.strip(), priority=i))
            else:
                nodes.append(OllamaNode(name=f"node-{i}", api_url=pair.strip(), priority=i))

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
        """Assign nodes by explicit cluster_id -> node_name mapping.

        mapping: {0: "bigboy1", 1: "bigboy2", 2: "thor"}
        Returns: {0: OllamaNode(...), 1: OllamaNode(...), ...}
        """
        result = {}
        for cluster_id, node_name in mapping.items():
            node = self.get_node(node_name)
            if node and node.healthy:
                result[cluster_id] = node
            else:
                # Fallback to first healthy node
                healthy = self.get_healthy_nodes()
                if healthy:
                    result[cluster_id] = healthy[0]
                    logger.warning(
                        "Node '%s' unavailable for cluster %d, falling back to '%s'",
                        node_name, cluster_id, healthy[0].name,
                    )
                else:
                    raise RuntimeError(f"No healthy node for cluster {cluster_id}")
        return result

    async def health_check_all(self) -> Dict[str, bool]:
        """Check health of all nodes concurrently."""
        results = {}

        async def _check(node: OllamaNode) -> None:
            now = time.time()
            if now - node.last_check < self.HEALTH_TTL:
                results[node.name] = node.healthy
                return
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    # Ollama /v1/models endpoint
                    resp = await client.get(
                        f"{node.api_url}/models",
                        headers={"Authorization": f"Bearer {node.api_key}"},
                    )
                    node.healthy = resp.status_code == 200
                    if node.healthy and node.models == []:
                        # Auto-discover models
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
```

### 3.2 `agents/factory.py` — PersonaFactory 수정

**변경 방향**: `api_url` 단일 파라미터 → `NodeRegistry` 기반 멀티노드 지원. 하위 호환성 유지.

```python
# === 변경 전 ===
class PersonaFactory:
    def __init__(
        self,
        default_model: str = "qwen2.5-coder:32b",
        api_url: str = None,
        api_key: str = None,
    ) -> None:
        self.default_model = default_model
        self.api_url = api_url or os.getenv("OPENROUTER_API_URL", "http://localhost:11434/v1")
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "ollama")


# === 변경 후 ===
class PersonaFactory:
    def __init__(
        self,
        default_model: str = "qwen2.5-coder:32b",
        api_url: str = None,
        api_key: str = None,
        node_registry: "NodeRegistry | None" = None,
        node_mapping: "dict[int, str] | None" = None,
    ) -> None:
        import os
        from config.nodes import NodeRegistry

        self.default_model = default_model
        # Legacy single-node fallback
        self.api_url = api_url or os.getenv("OPENROUTER_API_URL", "http://localhost:11434/v1")
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "ollama")

        # Multi-node support
        self.node_registry = node_registry  # None = legacy single-node mode
        self.node_mapping = node_mapping    # {cluster_id: "node_name"} or None for round-robin
```

**`create_agents` 메서드 수정**:

```python
    async def create_agents(
        self,
        clusters: List[ClusterProfile],
        use_llm_persona: bool = True,
    ) -> List[ForumAgent]:
        """Create one ForumAgent per cluster, optionally distributed across nodes."""
        agents: list[ForumAgent] = []

        # Determine node assignments
        node_assignments = self._resolve_node_assignments(clusters)

        for cluster in clusters:
            if use_llm_persona:
                persona = await self._generate_persona_llm(cluster)
            else:
                persona = self._generate_persona_rule(cluster)

            temperature = max(0.0, min(2.0, 0.7 + (cluster.sentiment * 0.1)))

            # Get node-specific api_url/api_key for this cluster
            api_url, api_key, model = self._get_node_config(cluster.cluster_id, node_assignments)

            agent = ForumAgent(
                config=ForumAgentConfig(
                    agent_id=self._safe_agent_id(cluster),
                    cluster_id=cluster.cluster_id,
                    label=cluster.label,
                    weight=cluster.weight,
                    persona_prompt=persona,
                    key_arguments=cluster.key_arguments,
                    model=model,
                    temperature=temperature,
                    activity_level=self._determine_activity(cluster),
                    active_hours=list(range(9, 22)),
                    influence_weight=cluster.weight * 2,
                ),
                api_url=api_url,
                api_key=api_key,
            )
            agents.append(agent)
            logger.info(
                "Created agent: %s → node=%s model=%s",
                agent.config.agent_id,
                api_url,
                model,
            )

        return agents

    def _resolve_node_assignments(
        self, clusters: List[ClusterProfile]
    ) -> "dict[int, OllamaNode] | None":
        """Resolve which node each cluster's agent should use.

        Returns None if single-node mode (legacy).
        """
        if self.node_registry is None:
            return None  # Legacy single-node

        if self.node_mapping:
            # Explicit mapping: {cluster_id: "node_name"}
            return self.node_registry.assign_by_mapping(self.node_mapping)
        else:
            # Round-robin
            nodes = self.node_registry.assign_round_robin(len(clusters))
            return {c.cluster_id: nodes[i] for i, c in enumerate(clusters)}

    def _get_node_config(
        self,
        cluster_id: int,
        assignments: "dict[int, OllamaNode] | None",
    ) -> tuple[str, str, str]:
        """Return (api_url, api_key, model) for a given cluster.

        Falls back to legacy single-node if assignments is None.
        """
        if assignments is None or cluster_id not in assignments:
            return self.api_url, self.api_key, self.default_model

        node = assignments[cluster_id]
        # Use node's first model if available, else default_model
        model = node.models[0] if node.models else self.default_model
        return node.api_url, node.api_key, model
```

### 3.3 `agents/factory.py` — ForumAgent 변경

**ForumAgent 자체는 변경 불필요.** 이미 `api_url`과 `api_key`를 개별적으로 받고 있으므로, 팩토리에서 노드별 URL을 넘겨주면 됨.

```python
# ForumAgent.__init__ — 변경 없음
class ForumAgent(BaseLLMAgent):
    def __init__(self, config, api_url, api_key):
        super().__init__(model=config.model, temperature=config.temperature,
                         api_url=api_url, api_key=api_key)
        self.config = config
```

### 3.4 `api/routes/forum.py` — API 엔드포인트 변경

**ForumStartRequest에 노드 설정 추가**:

```python
# === 변경 전 ===
class ForumStartRequest(BaseModel):
    topic: str = ...
    agent_model: Optional[str] = Field("qwen2.5-coder:32b", ...)
    # ...


# === 변경 후 ===
class NodeAssignment(BaseModel):
    """Per-agent node assignment."""
    node_name: str = Field(..., description="Node name (e.g. 'bigboy1')")
    model: Optional[str] = Field(None, description="Model override for this node")


class ForumStartRequest(BaseModel):
    topic: str = ...
    agent_model: Optional[str] = Field("qwen2.5-coder:32b", ...)

    # --- 멀티노드 확장 ---
    nodes: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Ollama node list. Format: [{name, api_url, models?, priority?}]"
    )
    node_mapping: Optional[Dict[str, str]] = Field(
        None,
        description="Agent-to-node mapping. Format: {'0': 'bigboy1', '1': 'thor'}"
    )
    # ...
```

**`_create_agents` 헬퍼 변경**:

```python
async def _create_agents(
    topic: str,
    seed_texts: Optional[List[str]],
    model: str,
    nodes: Optional[List[Dict]] = None,           # NEW
    node_mapping: Optional[Dict[str, str]] = None, # NEW
) -> list:
    """Create debate agents, optionally distributed across nodes."""
    from models.schemas import ClusterProfile
    from agents.factory import PersonaFactory

    if seed_texts and len(seed_texts) >= 2:
        clusters = _clusters_from_seeds(seed_texts)
    else:
        clusters = _default_clusters(topic, seed_texts)

    # Build NodeRegistry if multi-node config provided
    node_registry = None
    int_mapping = None

    if nodes:
        from config.nodes import NodeRegistry
        node_registry = NodeRegistry.from_config(nodes)
        # Run health check before creating agents
        await node_registry.health_check_all()

        if node_mapping:
            # Convert string keys to int: {"0": "bigboy1"} → {0: "bigboy1"}
            int_mapping = {int(k): v for k, v in node_mapping.items()}

    factory = PersonaFactory(
        default_model=model,
        node_registry=node_registry,
        node_mapping=int_mapping,
    )
    agents = await factory.create_agents(clusters, use_llm_persona=False)

    return agents
```

**`start_forum` 핸들러 변경** — `_create_agents` 호출부만 수정:

```python
@router.post("/start", ...)
async def start_forum(request: ForumStartRequest) -> ForumStartResponse:
    # ... (기존 코드 동일)

    try:
        agents = await _create_agents(
            topic=request.topic,
            seed_texts=request.seed_texts,
            model=request.agent_model or "qwen2.5-coder:32b",
            nodes=request.nodes,               # NEW
            node_mapping=request.node_mapping,  # NEW
        )
    except Exception as e:
        logger.error("Failed to create agents: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="내부 오류가 발생했습니다.")

    # ... (이하 동일)
```

---

## 4. 노드 라우팅 전략

### 4.1 라우팅 모드 3가지

| 모드 | 조건 | 동작 |
|------|------|------|
| **Legacy** | `nodes=null` | 기존 단일 `OPENROUTER_API_URL` 사용 |
| **Round-robin** | `nodes=[...]`, `node_mapping=null` | 클러스터를 건강한 노드에 순서대로 배정 |
| **Explicit** | `nodes=[...]`, `node_mapping={...}` | 클러스터별 지정 노드 사용 |

### 4.2 헬스체크 로직

```
POST /api/forum/start
  ↓
  nodes 파라미터 있음?
  ├─ No → Legacy 모드 (기존 동작)
  └─ Yes → NodeRegistry 생성
           ↓
           health_check_all() (병렬, 5초 타임아웃)
           ↓
           각 노드 GET /v1/models → 200이면 healthy
           ↓
           unhealthy 노드는 round-robin에서 제외
           ↓
           모든 노드 unhealthy → 500 에러
```

### 4.3 모델 자동 탐지

헬스체크 시 `/v1/models` 응답에서 사용 가능한 모델 목록을 자동으로 채움. `node_mapping`에서 모델을 지정하지 않으면 노드의 첫 번째 모델 사용.

---

## 5. 설정 구조

### 5.1 `.env.development` 확장

```bash
# === 기존 (변경 없음, 하위 호환) ===
OPENROUTER_API_KEY=ollama
OPENROUTER_API_URL=http://100.115.195.128:11434/v1
DEFAULT_MODEL=qwen2.5-coder:32b

# === 멀티노드 추가 (선택) ===
OLLAMA_NODES=bigboy1=http://100.115.195.128:11434/v1,bigboy2=http://100.77.225.102:11434/v1,thor=http://100.68.192.59:11434/v1
```

### 5.2 `config/models.yaml` 확장

```yaml
# 기존 models/defaults 섹션은 유지

# === 신규: 노드 정의 ===
nodes:
  - name: bigboy1
    api_url: "http://100.115.195.128:11434/v1"
    api_key: "ollama"
    models: ["gpt-oss:120b", "qwen2.5:7b", "qwen2.5-coder:32b"]
    priority: 0

  - name: bigboy2
    api_url: "http://100.77.225.102:11434/v1"
    api_key: "ollama"
    models: ["qwen2.5:7b"]
    priority: 1

  - name: thor
    api_url: "http://100.68.192.59:11434/v1"
    api_key: "ollama"
    models: ["gpt-oss:20b"]
    priority: 2

# === 프리셋 노드 매핑 ===
node_presets:
  distributed_3way:
    "0": bigboy1   # cluster 0 → bigboy1
    "1": bigboy2   # cluster 1 → bigboy2
    "2": thor      # cluster 2 → thor

  bigboy_only:
    "0": bigboy1
    "1": bigboy1
    "2": bigboy1
```

---

## 6. API 인터페이스

### 6.1 기존 요청 (변경 없음, 하위 호환)

```bash
curl -X POST http://localhost:8003/api/forum/start \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "AI 규제 필요성",
    "seed_texts": ["AI 규제가 필요하다", "AI 자율성이 중요하다", "균형 잡힌 접근이 필요"],
    "max_rounds": 5,
    "agent_model": "qwen2.5-coder:32b"
  }'
```

### 6.2 멀티노드: Round-robin

```bash
curl -X POST http://localhost:8003/api/forum/start \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "AI 규제 필요성",
    "seed_texts": ["AI 규제가 필요하다", "AI 자율성이 중요하다", "균형 잡힌 접근이 필요"],
    "max_rounds": 5,
    "nodes": [
      {"name": "bigboy1", "api_url": "http://100.115.195.128:11434/v1", "models": ["gpt-oss:120b"]},
      {"name": "bigboy2", "api_url": "http://100.77.225.102:11434/v1", "models": ["qwen2.5:7b"]},
      {"name": "thor", "api_url": "http://100.68.192.59:11434/v1", "models": ["gpt-oss:20b"]}
    ]
  }'
```

결과: agent-0 → bigboy1(gpt-oss:120b), agent-1 → bigboy2(qwen2.5:7b), agent-2 → thor(gpt-oss:20b)

### 6.3 멀티노드: Explicit mapping

```bash
curl -X POST http://localhost:8003/api/forum/start \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "AI 규제 필요성",
    "seed_texts": ["AI 규제가 필요하다", "AI 자율성이 중요하다", "균형 잡힌 접근이 필요"],
    "max_rounds": 5,
    "nodes": [
      {"name": "bigboy1", "api_url": "http://100.115.195.128:11434/v1", "models": ["gpt-oss:120b"]},
      {"name": "bigboy2", "api_url": "http://100.77.225.102:11434/v1", "models": ["qwen2.5:7b"]},
      {"name": "thor", "api_url": "http://100.68.192.59:11434/v1", "models": ["gpt-oss:20b"]}
    ],
    "node_mapping": {
      "0": "bigboy1",
      "1": "thor",
      "2": "bigboy2"
    }
  }'
```

### 6.4 노드 상태 확인 엔드포인트 (신규)

```bash
# GET /api/forum/nodes — 등록된 노드 상태 조회
curl http://localhost:8003/api/forum/nodes
```

응답:
```json
{
  "nodes": [
    {"name": "bigboy1", "api_url": "http://100.115.195.128:11434/v1", "models": ["gpt-oss:120b", "qwen2.5:7b"], "healthy": true},
    {"name": "bigboy2", "api_url": "http://100.77.225.102:11434/v1", "models": ["qwen2.5:7b"], "healthy": true},
    {"name": "thor", "api_url": "http://100.68.192.59:11434/v1", "models": ["gpt-oss:20b"], "healthy": false}
  ]
}
```

---

## 7. 코드 변경 최소화 — 변경 파일 목록

| 파일 | 변경 유형 | 영향 범위 |
|------|---------|---------|
| `config/nodes.py` | **신규** | 노드 레지스트리 클래스 |
| `agents/factory.py` | **수정** | `PersonaFactory.__init__` + `create_agents` + 2개 헬퍼 추가 |
| `api/routes/forum.py` | **수정** | `ForumStartRequest`에 2필드 추가 + `_create_agents` 파라미터 확장 |
| `config/models.yaml` | **수정** | `nodes` + `node_presets` 섹션 추가 |
| `.env.development` | **수정** (선택) | `OLLAMA_NODES` 환경변수 추가 |

### 변경하지 않는 파일

| 파일 | 이유 |
|------|------|
| `agents/base.py` (`BaseLLMAgent`) | 이미 인스턴스별 `api_url` 지원 |
| `ForumAgent` 클래스 | 이미 개별 `api_url` 수신 구조 |
| `forum/engine.py` | 에이전트 리스트만 받으므로 무관 |
| `agents/moderator.py` | 모더레이터는 단일 노드 유지 |
| `config/settings.py` | 레지스트리가 별도이므로 수정 불필요 |

---

## 8. 하위 호환성 보장

```
nodes=null, node_mapping=null
  → PersonaFactory(node_registry=None)
  → _get_node_config() returns (self.api_url, self.api_key, self.default_model)
  → 기존과 100% 동일 동작
```

- `nodes`와 `node_mapping`은 모두 `Optional`, 기본값 `None`
- `OLLAMA_NODES` 환경변수 미설정 시 `OPENROUTER_API_URL` 폴백
- 기존 테스트 (`tests/test_agents/test_factory.py`) 수정 불필요

---

## 9. 구현 순서 (권장)

```
Phase 1: config/nodes.py 생성 (NodeRegistry + OllamaNode)
Phase 2: agents/factory.py 수정 (PersonaFactory 멀티노드 지원)
Phase 3: api/routes/forum.py 수정 (ForumStartRequest 확장 + _create_agents 연동)
Phase 4: config/models.yaml 노드 설정 추가
Phase 5: 테스트 — 3노드 분산 토론 실행
```

### Phase 5 검증 시나리오

```bash
# 1. 헬스체크
curl http://localhost:8003/api/forum/nodes

# 2. 3노드 분산 토론 시작
curl -X POST http://localhost:8003/api/forum/start \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "원자력 발전 확대 찬반",
    "seed_texts": [
      "원자력은 탄소중립을 위한 필수 에너지원이다",
      "원자력의 안전성과 폐기물 문제는 해결 불가능하다",
      "재생에너지와 원자력의 혼합 포트폴리오가 현실적이다"
    ],
    "max_rounds": 3,
    "nodes": [
      {"name": "bigboy1", "api_url": "http://100.115.195.128:11434/v1", "models": ["gpt-oss:120b"]},
      {"name": "bigboy2", "api_url": "http://100.77.225.102:11434/v1", "models": ["qwen2.5:7b"]},
      {"name": "thor", "api_url": "http://100.68.192.59:11434/v1", "models": ["gpt-oss:20b"]}
    ]
  }'

# 3. 로그에서 노드 배정 확인
# 기대: "Created agent: agent-0-view-1 → node=http://100.115.195.128:11434/v1 model=gpt-oss:120b"

# 4. 기존 단일노드 요청도 여전히 동작하는지 확인
curl -X POST http://localhost:8003/api/forum/start \
  -H "Content-Type: application/json" \
  -d '{"topic": "테스트", "max_rounds": 1}'
```

---

## 10. 시퀀스 다이어그램

```
Client                API(/forum/start)        PersonaFactory         NodeRegistry        Ollama Nodes
  │                        │                       │                     │                    │
  │─── POST (nodes=[...]) ─→                       │                     │                    │
  │                        │── from_config(nodes) ──→                    │                    │
  │                        │                       │                     │                    │
  │                        │── health_check_all() ──────────────────────→│                    │
  │                        │                       │                     │── GET /v1/models ──→│
  │                        │                       │                     │←── 200 + models ───│
  │                        │                       │                     │                    │
  │                        │── PersonaFactory(registry, mapping) ───────→│                    │
  │                        │                       │                     │                    │
  │                        │── create_agents() ────→                     │                    │
  │                        │                       │── resolve_assignments()                  │
  │                        │                       │── ForumAgent(api_url=node1.url) ─────────│
  │                        │                       │── ForumAgent(api_url=node2.url) ─────────│
  │                        │                       │── ForumAgent(api_url=node3.url) ─────────│
  │                        │                       │                     │                    │
  │                        │── ForumEngine(agents) ─→                    │                    │
  │                        │                       │                     │                    │
  │←── {session_id, ...} ──│                       │                     │                    │
```
