# ARCHITECTURE.md — AI Debate Simulator v2

> 4-Way Integration: AI Debate Simulator + BettaFish ForumEngine + MiroFish OASIS + OpenClaw
> 원칙: 고칠 건 고치고, 살릴 건 살린다.

---

## 전체 시스템 다이어그램

```
                        ┌──────────────────────────┐
                        │     OpenClaw Platform     │
                        │  Telegram│Discord│Slack   │
                        │  CLI: openclaw debate     │
                        └───────────┬──────────────┘
                                    │ REST / WebSocket
┌───────────────────────────────────▼────────────────────────────────┐
│                        API GATEWAY (FastAPI)                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ ┌───────────┐ │
│  │routes/   │ │routes/   │ │routes/   │ │routes/ │ │routes/    │ │
│  │debate.py │ │forum.py  │ │models.py │ │health  │ │openclaw.py│ │
│  │(legacy)  │ │(new)     │ │          │ │        │ │           │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘ └───────────┘ │
│       WebSocket Manager: 토큰 인증 + 연결당 rate limiting          │
└────────────────────────────┬───────────────────────────────────────┘
                             │
    ┌────────────────────────▼──────────────────────────────────┐
    │                    L0: DATA COLLECTOR                      │
    │  clustering/data_collector.py                              │
    │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
    │  │ arXiv API│  │ 뉴스 RSS │  │GitHub API│  │ 사용자   │ │
    │  │          │  │(feedpars)│  │          │  │ 시드텍스트│ │
    │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘ │
    │       └──────────────┴─────────────┴─────────────┘       │
    │                     ↓ Document[]                          │
    └─────────────────────┬────────────────────────────────────┘
                          │
    ┌─────────────────────▼────────────────────────────────────┐
    │              L1: OPINION CLUSTERING ENGINE                 │
    │  clustering/engine.py  (LLM 호출 없음)                    │
    │                                                           │
    │  Document[] → SentenceTransformer 임베딩                  │
    │            → HDBSCAN 클러스터링 (자동 클러스터 수)         │
    │            → TF-IDF 핵심 논점 추출                        │
    │                                                           │
    │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐      │
    │  │ Cluster A    │ │ Cluster B    │ │ Cluster C    │ ...  │
    │  │ "낙관론" 30% │ │ "회의론" 45% │ │ "현실주의"25%│      │
    │  │ 핵심논점 추출│ │ 핵심논점 추출│ │ 핵심논점 추출│      │
    │  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘      │
    │         └────────────────┴────────────────┘              │
    │                     ↓ ClusterProfile[]                    │
    └─────────────────────┬────────────────────────────────────┘
                          │
    ┌─────────────────────▼────────────────────────────────────┐
    │           L2: REPRESENTATIVE AGENT FACTORY                │
    │  agents/factory.py                                        │
    │                                                           │
    │  ClusterProfile → PersonaFactory (1 LLM 호출/클러스터)   │
    │                 → MiroFish AgentActivityConfig 적용       │
    │                                                           │
    │  ┌────────────┐  ┌────────────┐  ┌────────────┐         │
    │  │ Agent-A    │  │ Agent-B    │  │ Agent-C    │         │
    │  │ stance:낙관│  │ stance:회의│  │ stance:현실│         │
    │  │ weight:0.30│  │ weight:0.45│  │ weight:0.25│         │
    │  │ activity   │  │ activity   │  │ activity   │         │
    │  │ :0.7       │  │ :0.8       │  │ :0.5       │         │
    │  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘         │
    │        └───────────────┴───────────────┘                 │
    │                     ↓ ForumAgent[]                        │
    └─────────────────────┬────────────────────────────────────┘
                          │
    ┌─────────────────────▼────────────────────────────────────┐
    │                 L3: FORUM ENGINE                           │
    │  forum/engine.py  (BettaFish pub/sub 패턴)               │
    │                                                           │
    │  ┌─────────────────────────────────────────────┐         │
    │  │           Forum Log (pub/sub bus)            │         │
    │  │  agent-a.log ← Agent-A 발언                 │         │
    │  │  agent-b.log ← Agent-B 발언                 │         │
    │  │  agent-c.log ← Agent-C 발언                 │         │
    │  │  forum.log   ← 통합 + [HOST] 태그           │         │
    │  └───────────────────┬─────────────────────────┘         │
    │                      │ LogMonitor (1초 폴링)             │
    │                      │ 발언 N개 누적 시                  │
    │                      ↓                                    │
    │  ┌─────────────────────────────────────────────┐         │
    │  │           MODERATOR (ForumHost)              │         │
    │  │  - 에이전트와 다른 모델 (anti-homogenization)│         │
    │  │  - 이벤트 타임라인 정리                      │         │
    │  │  - 오류/모순 지적                            │         │
    │  │  - 합의/교착 판단                            │         │
    │  │  - ForumReader: [HOST] → 에이전트 프롬프트   │         │
    │  └─────────────────────────────────────────────┘         │
    │                                                           │
    │  OASIS 패턴 자체 구현 (MiroFish env.step 영감):            │
    │  - oasis_sim/engine.py (~200줄, 의존성 제로)             │
    │  - agent graph + async step loop + SQLite trace          │
    │  - active_hours 기반 에이전트 필터링                      │
    │  - activity_level 가중 선택                               │
    │  - influence_weight 반영                                  │
    │  - RuleAgent 수백개 (LLM 없음) + LLM 대표 에이전트       │
    │                                                           │
    │  종료 조건:                                               │
    │  - 최대 라운드 도달                                       │
    │  - 사회자 합의/교착 판정                                  │
    │  - 임베딩 유사도 기반 반복 감지                           │
    │                     ↓ DebateTranscript                    │
    └─────────────────────┬────────────────────────────────────┘
                          │
    ┌─────────────────────▼────────────────────────────────────┐
    │            L4: EVALUATION & PREDICTION                    │
    │  evaluation/evaluator.py  (기존 M-MAD 보존)              │
    │  evaluation/embeddings.py (임베딩 기반 보강)             │
    │  evaluation/predictor.py  (클러스터 가중 예측)           │
    │                                                           │
    │  M-MAD 8차원 평가:                                       │
    │  ┌────────────────────────────────────────────┐          │
    │  │ logical_coherence (1.5) │ relevance (1.4)  │          │
    │  │ evidence_quality  (1.3) │ factual_acc(1.3) │          │
    │  │ persuasiveness    (1.2) │ clarity   (1.1)  │          │
    │  │ originality       (1.0) │ emot_appeal(0.8) │          │
    │  └────────────────────────────────────────────┘          │
    │                                                           │
    │  + 임베딩 보강:                                          │
    │    - relevance: topic 임베딩 cosine similarity            │
    │    - originality: 이전 발언 대비 cosine distance          │
    │    - similarity: Jaccard → 임베딩 cosine (Jaccard fallb) │
    │                                                           │
    │  + 클러스터 가중 예측:                                   │
    │    weighted_score = debate_score × cluster_weight         │
    │    × (1 + stance_shift)                                   │
    │    dominant_opinion = argmax(weighted_scores)              │
    │    confidence = max / sum                                  │
    └─────────────────────┬────────────────────────────────────┘
                          │
    ┌─────────────────────▼────────────────────────────────────┐
    │               L5: REPORT GENERATOR                        │
    │  report/generator.py                                      │
    │                                                           │
    │  ReACT 패턴 (MiroFish):                                 │
    │  Planning (temp 0.3)                                      │
    │    → Multi-tool retrieval (min 3 tool calls/section)     │
    │    → Reflection loop                                      │
    │                                                           │
    │  출력:                                                    │
    │  1. 요약 — 1문단 결론                                    │
    │  2. 여론 분포 — 클러스터별 비중 + 가중 점수              │
    │  3. 핵심 쟁점 — 토론 최다 논점 Top 5                     │
    │  4. 토론 하이라이트 — 핵심 교환 3~5개                    │
    │  5. 예측 근거 — 살아남은 논점 + 출처                     │
    │  6. 반론 요약 — 소수 의견 핵심 반론                      │
    │                                                           │
    │  형식: Markdown (기본) │ JSON │ HTML                      │
    │  채널: OpenClaw → Telegram/Discord/Slack 포맷팅          │
    └──────────────────────────────────────────────────────────┘
```

---

## Retain / Refactor / Remove 판정표

### debate_agent.py (923줄)

| 대상 | 판정 | 근거 |
|------|------|------|
| `_call_llm()` async, 3-retry, exponential backoff | **RETAIN** | 프로덕션급 LLM 통신 코드 |
| `_handle_streaming_response()` SSE 파싱 | **RETAIN** | WebSocket 중계에 적합 |
| `_extract_relevant_context()` 7-category, max 8 | **RETAIN** | 우선순위 기반 컨텍스트 추출 |
| `_analyze_response_quality()` | **RETAIN** | 품질 분석 파이프라인 |
| `_extract_response_from_thinking()` o1-like 분리 | **RETAIN** | o1/o3 모델 대응 필수 |
| `AgentRole` enum 7개 고정 역할 | **REMOVE** | 클러스터 기반 동적 생성으로 대체 |
| `_get_default_persona()` 하드코딩 Korean emoji | **REMOVE** | PersonaFactory로 대체 |
| `_generate_intelligent_fallback()` 템플릿 응답 | **REFACTOR** | 클러스터 key_arguments 기반 폴백으로 교체 |
| `MultiAgentDebater` 클래스 | **REMOVE** | 사용되지 않는 죽은 코드. 64줄 즉시 삭제 |
| `OPENROUTER_MODELS` 하드코딩 dict | **REFACTOR** | `config/models.yaml`로 외부화 |
| `Argument` dataclass | **REFACTOR** | Pydantic + `cluster_id`, `influence_weight` 추가 |
| temperature 고정 0.7 | **REFACTOR** | 클러스터 profile에서 자동 결정 |
| `print(f"API Key 확인: {key[:20]}...")` | **REMOVE** | 보안 위험. 즉시 삭제 |

### debate_controller.py (552줄)

| 대상 | 판정 | 근거 |
|------|------|------|
| `_cross_evaluate_arguments()` 다차원 상호평가 | **RETAIN** | 자기평가(self_evaluation)만 제거 후 ForumEngine에 통합 |
| Round management (current_round, history) | **RETAIN** | ForumEngine 내부로 이동하되 로직 유지 |
| `_generate_initial_briefing()` | **RETAIN** | 클러스터 정보 포함하도록 확장 |
| `export_debate_transcript()` | **RETAIN** | OpenClaw 채널 포맷으로 확장 |
| `_conduct_adversarial_round()` | **REMOVE** | ForumEngine 설정 파라미터로 대체 |
| `_conduct_collaborative_round()` | **REMOVE** | ForumEngine 설정 파라미터로 대체 |
| `_conduct_competitive_round()` | **REMOVE** | ForumEngine 설정 파라미터로 대체 |
| `_conduct_standard_round()` | **REMOVE** | ForumEngine 대체 |
| `DebateFormat.OXFORD` | **REMOVE** | 핸들러 없는 죽은 코드 |
| `DebateFormat.ROUNDTABLE` | **REMOVE** | 핸들러 없는 죽은 코드 |
| `time_limit_per_round` | **REMOVE** | 설정만 있고 체크 로직 없음 |
| `enable_fact_checking` | **REMOVE** | 사용처 없음 |

### debate_evaluator.py (723줄)

| 대상 | 판정 | 근거 |
|------|------|------|
| M-MAD 8차원 프레임워크 전체 | **RETAIN** | 프로젝트 핵심 가치. 가중치 시스템 포함 |
| `DimensionScore` with rationale | **RETAIN** | 평가 투명성 핵심 |
| `CompetitiveDebateJudge` | **RETAIN** | 클러스터 가중치 로직 추가만 필요 |
| Logical fallacy detection 5패턴 | **REFACTOR** | 15패턴으로 확장 |
| `_calculate_similarity()` Jaccard | **REFACTOR** | 임베딩 cosine + Jaccard fallback |
| `_evaluate_relevance()` 키워드 매칭 | **REFACTOR** | 임베딩 유사도 보강 |
| `_evaluate_originality()` Jaccard | **REFACTOR** | 임베딩 cosine distance |
| `_evaluate_factual_accuracy()` conf=0.4 | **REFACTOR** | LLM 보강 옵션 추가 또는 가중치 하향 |

### final_web_app.py (1704줄)

| 대상 | 판정 | 근거 |
|------|------|------|
| FastAPI + WebSocket 패턴 | **RETAIN** | 아키텍처 패턴 유지, 파일만 분리 |
| Security headers middleware | **RETAIN** | CSP `unsafe-inline` → nonce 전환 |
| Session management | **REFACTOR** | 인메모리 → SQLite(dev)/Redis(prod) |
| `CORS allow_origins=["*"]` | **REFACTOR** | Settings 기반 제한 |
| 1704줄 단일 파일 | **REFACTOR** | 6개 라우터 파일로 분리 |
| `SimpleMetrics` 중복 클래스 | **REMOVE** | utils/monitoring.py와 통합 |

### utils/ (cache.py, security.py, monitoring.py)

| 대상 | 판정 | 근거 |
|------|------|------|
| LRU+TTL cache, Rate limiter, Metrics | **RETAIN** | 견고한 구현 |

---

## 새 디렉토리 구조

```
ai-debate-simulator/
├── api/                          # Web layer (final_web_app.py 분리)
│   ├── __init__.py
│   ├── app.py                    # FastAPI app 조립
│   ├── middleware.py             # Security headers, CSP nonce
│   ├── ws.py                    # WebSocket + 토큰 인증
│   └── routes/
│       ├── debate.py            # Legacy 엔드포인트 (전환기)
│       ├── forum.py             # ForumEngine 파이프라인
│       ├── models.py            # 모델 목록
│       ├── health.py            # 헬스체크 + 메트릭
│       └── openclaw.py          # OpenClaw 브릿지
│
├── agents/                       # Agent 시스템 (debate_agent.py 리팩토링)
│   ├── __init__.py
│   ├── base.py                  # BaseLLMAgent (_call_llm, streaming, thinking)
│   ├── forum_agent.py           # ForumAgent (클러스터 기반 동적 페르소나)
│   ├── factory.py               # PersonaFactory + AgentActivityConfig
│   └── moderator.py             # ForumHost (별도 모델, anti-homogenization)
│
├── clustering/                   # 여론 클러스터링 (NEW)
│   ├── __init__.py
│   ├── engine.py                # SentenceTransformer + HDBSCAN
│   └── data_collector.py        # arXiv, RSS, GitHub, 사용자 텍스트
│
├── evaluation/                   # 평가 시스템 (debate_evaluator.py 리팩토링)
│   ├── __init__.py
│   ├── evaluator.py             # M-MAD 8차원 (RETAINED)
│   ├── embeddings.py            # 임베딩 기반 similarity (NEW)
│   └── predictor.py             # 클러스터 가중 예측 (NEW)
│
├── forum/                        # Forum Engine (NEW, debate_controller.py 대체)
│   ├── __init__.py
│   ├── engine.py                # BettaFish pub/sub + OASIS env.step
│   ├── config.py                # ForumConfig + 형식 프리셋
│   └── transcript.py            # 다채널 포맷 변환
│
├── oasis_sim/                    # OASIS 패턴 자체 구현 (NEW)
│   ├── __init__.py
│   ├── engine.py                # async step loop (~200줄)
│   ├── rule_agent.py            # RuleAgent (LLM 없음, 규칙 기반)
│   ├── agent_graph.py           # 에이전트 관계 그래프
│   └── trace.py                 # SQLite 행동 추적
│
├── bridge/                       # 외부 연동 (NEW)
│   ├── __init__.py
│   └── openclaw.py              # OpenClaw extension 브릿지
│
├── report/                       # 리포트 생성 (NEW)
│   ├── __init__.py
│   └── generator.py             # ReACT 리포트 + 시각화
│
├── models/                       # 데이터 모델 (NEW)
│   ├── __init__.py
│   └── schemas.py               # 전 레이어 Pydantic 모델
│
├── config/                       # 설정 (기존 확장)
│   ├── __init__.py
│   ├── settings.py              # Pydantic Settings (확장)
│   └── models.yaml              # 모델 레지스트리 (하드코딩 대체)
│
├── utils/                        # 유틸리티 (기존 RETAIN)
│   ├── __init__.py
│   ├── cache.py
│   ├── security.py
│   └── monitoring.py
│
├── templates/                    # 프론트엔드 (분리)
│   ├── index.html               # Base template (슬림화)
│   └── static/
│       ├── js/app.js
│       └── css/style.css
│
├── tests/
│   ├── test_agents/
│   ├── test_clustering/
│   ├── test_evaluation/
│   ├── test_forum/
│   └── test_api/
│
├── # Legacy 호환 래퍼 (전환기)
├── debate_agent.py              # → from agents import *
├── debate_controller.py         # → from forum import *
├── debate_evaluator.py          # → from evaluation import *
├── main.py                      # 진입점 (final_web_app.py 대체)
│
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── ARCHITECTURE.md
└── README.md
```

---

## L0: 데이터 수집 (Data Collector)

시드 데이터를 수집하고 정규화한다. LLM 호출 없음.

### 입력 소스

| 소스 | 수집 방식 | 출력 |
|------|-----------|------|
| arXiv | `arxiv` 패키지, 키워드/카테고리 검색 | abstract + metadata |
| 뉴스 RSS | `feedparser`, 주요 기술 뉴스 피드 | title + summary |
| GitHub | GitHub Search API, 이슈/README | description + 주요 텍스트 |
| 사용자 시드 | 직접 입력 텍스트, URL | 추출된 본문 |

### 정규화 스키마

```python
class Document(BaseModel):
    id: str
    source: str           # "arxiv" | "github" | "news" | "user"
    title: str
    content: str          # 최대 2000자 truncate
    url: Optional[str]
    timestamp: datetime
    metadata: Dict
```

### 설계 원칙
- 각 소스 커넥터는 독립 모듈. 새 소스 추가 시 커넥터만 구현.
- rate limit 준수: arXiv 3초 간격, GitHub 토큰 기반 5000req/h.
- 수집 결과는 로컬 SQLite에 캐싱 (중복 수집 방지).

---

## L1: 여론 클러스터링 엔진 (Opinion Clustering Engine)

수집된 문서를 임베딩 → 클러스터링하여 여론 분포를 추출한다. **LLM 호출 없음.**

### 파이프라인

```
Document[]
  → SentenceTransformer 임베딩 (all-MiniLM-L6-v2 또는 multilingual)
  → UMAP 차원 축소 (선택, 문서 100개 이상 시)
  → HDBSCAN 클러스터링 (자동 클러스터 수)
     또는 K-Means (사용자가 클러스터 수 지정 시)
  → 클러스터별 핵심 논점 추출 (TF-IDF 기반, LLM 없음)
  → ClusterProfile[] 출력
```

### ClusterProfile 스키마

```python
class ClusterProfile(BaseModel):
    cluster_id: int
    label: str                    # TF-IDF 상위 키워드 조합
    weight: float                 # 전체 문서 중 비율 (0.0~1.0)
    document_count: int
    key_arguments: List[str]      # 핵심 논점 문장 (3~5개)
    keywords: List[str]           # 상위 키워드
    sentiment: float              # -1.0 (반대) ~ 1.0 (찬성)
    centroid: List[float]         # 클러스터 중심 벡터
```

### 설계 결정
- **HDBSCAN 기본**: 클러스터 수 미리 정하지 않아도 됨. 노이즈 포인트 자동 처리.
- **K-Means 폴백**: 사용자가 수를 지정하면 사용.
- **임베딩 모델**: `all-MiniLM-L6-v2` (22MB, 빠름) 또는 `paraphrase-multilingual-MiniLM-L12-v2` (한국어).
- **임베딩 재사용**: L4 평가 모듈에서 similarity/originality/relevance 계산에 동일 모델 사용.

---

## L2: 대표 에이전트 팩토리 (Representative Agent Factory)

각 클러스터를 하나의 토론 에이전트로 변환한다. **클러스터당 1회 LLM 호출.**

### PersonaFactory

```python
class PersonaFactory:
    def create_from_cluster(self, profile: ClusterProfile) -> ForumAgent
    def _build_persona_prompt(self, profile: ClusterProfile) -> str
    def _determine_stance(self, profile: ClusterProfile) -> str
```

### ForumAgent 스키마

```python
class ForumAgent(BaseModel):
    agent_id: str
    cluster_id: int
    label: str                # "낙관론", "회의론" 등
    weight: float             # 클러스터 비중
    persona_prompt: str       # LLM 생성 또는 규칙 기반 페르소나
    key_arguments: List[str]  # 폴백용 논점
    model: str                # 할당된 LLM 모델
    temperature: float        # 감성에 따른 온도 조절
    # MiroFish AgentActivityConfig
    activity_level: float     # 0.0~1.0
    active_hours: List[int]   # 활동 시간대
    influence_weight: float   # 영향력 가중치
```

### 모델 할당 전략

| 역할 | 모델 | 비고 |
|------|------|------|
| Moderator | 에이전트와 **다른 계열** (예: glm-4.7-flash) | Anti-homogenization 필수 |
| Agent (토론자) | gpt-oss:120b 또는 qwen2.5-coder:32b | 주력 모델 |
| Agent Factory | 아무 모델 | 1회 호출이므로 무관 |

### Anti-Homogenization 원칙 (BettaFish 핵심)

1. 모더레이터 = 에이전트와 **다른 모델 계열** 사용 (같은 모델이면 의견 수렴)
2. 모더레이터는 **팩트 오류/논리 모순 지적** (적대적 역할)
3. **발언 N개마다 1회** 개입 (과도한 개입 방지, BettaFish 기본값: 5)
4. 런타임 검증: `ForumHost.validate_model_separation()` 호출

---

## L3: ForumEngine (토론 엔진)

BettaFish ForumEngine의 pub/sub 패턴을 적용한 비동기 토론 시스템.
기존 DebateController를 대체한다.

### 핵심 구조: 로그 기반 pub/sub

에이전트들은 서로 직접 통신하지 않는다. 각자 로그 파일에 발언을 기록하고,
모더레이터가 로그를 읽어 중재한다.

```
forum/{session_id}/
├── logs/
│   ├── agent-{cluster_a_label}.jsonl
│   ├── agent-{cluster_b_label}.jsonl
│   ├── agent-{cluster_c_label}.jsonl
│   └── moderator.jsonl
├── forum.log                    # 통합 로그 ([SOURCE]/[HOST] 태그)
└── state.json                   # 토론 상태
```

### LogMonitor (BettaFish 패턴 그대로)

```
1. 1초 간격으로 에이전트 로그 파일 폴링
2. SummaryNode 출력만 필터링
3. forum.log에 [SOURCE:agent_name] 태그로 기록
4. agent_speeches_buffer에 누적
5. N개(기본 5) 누적 시 → ForumHost 트리거
```

### ForumReader (에이전트 → 모더레이터 요약 수신)

```
1. forum.log에서 최신 [HOST] 엔트리 역방향 스캔
2. 에이전트 LLM 프롬프트에 주입:
   "### Forum Host Latest Summary\n{host_speech}"
3. 캐싱: 동일 엔트리 반복 주입 방지
```

### ForumPost 스키마

```python
class ForumPost(BaseModel):
    post_id: str
    agent_id: str
    round: int
    timestamp: datetime
    content: str
    reply_to: Optional[str]      # 응답 대상 post_id
    evidence_refs: List[str]     # 인용한 근거 문서 ID
    stance_shift: float          # 입장 변화량 (-1.0 ~ 1.0)
    cluster_id: int
    influence_weight: float
```

### OASIS 패턴 자체 구현 (oasis_sim/)

camel-oasis 패키지는 소셜미디어(Twitter/Reddit)에 하드코딩되어 커스텀 환경 생성이 불가.
MiroFish OASIS의 핵심 패턴만 추출하여 ~200줄로 자체 구현한다. **외부 의존성 제로.**

#### 왜 자체 구현인가

| 항목 | camel-oasis 직접 사용 | 자체 구현 |
|------|----------------------|-----------|
| 환경 | TwitterEnv/RedditEnv만 | DebateEnv 자유롭게 정의 |
| ActionType | 35개 소셜미디어 행동 | 토론 행동 (발언/반박/동의/기권) |
| 의존성 | camel-ai + PyTorch + neo4j = 2~4GB | **0KB** (stdlib + numpy만) |
| Python | 3.10~3.11만 | 제약 없음 |
| ARM 호환 | cairocffi C 의존성 이슈 | 문제 없음 |

#### 핵심 구조

```python
# oasis_sim/engine.py (~200줄)
class DebateSimulation:
    """OASIS env.step() 패턴의 토론 최적화 자체 구현"""

    def __init__(self, agent_graph: AgentGraph, db_path: str):
        self.agent_graph = agent_graph
        self.trace = SQLiteTrace(db_path)  # 행동 추적
        self.current_step = 0

    async def step(self, active_agents: List[str]) -> StepResult:
        """한 타임스텝 실행 — LLM 대표 에이전트 + 규칙 에이전트"""
        tasks = []
        for agent_id in active_agents:
            agent = self.agent_graph.get(agent_id)
            if agent.is_llm_agent:
                tasks.append(agent.act_llm(self.context))
            else:
                tasks.append(agent.act_rule(self.context))
        results = await asyncio.gather(*tasks)
        self.trace.log(self.current_step, results)
        self.current_step += 1
        return StepResult(actions=results)

    def get_prediction(self) -> PredictionResult:
        """시뮬레이션 결과에서 여론 분포 추출"""
```

```python
# oasis_sim/rule_agent.py
class RuleAgent:
    """LLM 호출 없는 규칙 기반 에이전트 (MiroFish 핵심 트릭)"""

    agent_id: str
    entity_type: str          # University, Student, Expert, Media 등
    activity_level: float     # 0.0~1.0
    active_hours: List[int]   # 활동 시간대
    sentiment_bias: float     # -1.0 (반대) ~ 1.0 (찬성)
    influence_weight: float   # 영향력 가중치
    stance: str               # 초기 입장 (클러스터 라벨)

    def act_rule(self, context: Dict) -> Action:
        """규칙 기반 의사결정 — 확률적 투표"""
        # sentiment_bias + influence_weight + 주변 에이전트 영향
        # → 찬성/반대/중립/기권 중 하나 선택
```

```python
# oasis_sim/agent_graph.py
class AgentGraph:
    """에이전트 관계 그래프 (igraph 없이 dict 기반)"""

    def create_from_clusters(self, clusters: List[ClusterProfile],
                              scale: int = 100) -> None:
        """클러스터별 비례 에이전트 생성
        예: Cluster A(35%) → 35 RuleAgent + 1 LLM Agent
            Cluster B(45%) → 45 RuleAgent + 1 LLM Agent
            Cluster C(20%) → 20 RuleAgent + 1 LLM Agent
        """

    def get_neighbors(self, agent_id: str) -> List[str]:
        """이웃 에이전트 (영향 전파용)"""
```

#### 엔티티 타입별 기본 프로필 (MiroFish 패턴)

| 엔티티 타입 | activity_level | influence_weight | active_hours | 역할 |
|-------------|---------------|-----------------|--------------|------|
| Expert | 0.3 | 3.0 | 9~17 | 전문가 의견, 높은 영향력 |
| Media | 0.5 | 2.5 | 7~23 | 미디어, 넓은 확산 |
| Student | 0.8 | 0.8 | 8~13, 18~23 | 활발하지만 영향력 낮음 |
| General | 0.7 | 1.0 | 9~13, 18~23 | 일반 대중 |
| Institution | 0.2 | 3.0 | 9~17 | 기관, 드물지만 영향력 큼 |

#### 시뮬레이션 흐름

```
토론 결과 (ForumEngine L3)
    ↓
1. 클러스터별 비례 에이전트 생성 (기본 100개, 설정 가능)
   Cluster A(30%) → 30 RuleAgent + 1 LLM 대표
   Cluster B(45%) → 45 RuleAgent + 1 LLM 대표
   Cluster C(25%) → 25 RuleAgent + 1 LLM 대표
    ↓
2. env.step() 루프 (20~50 스텝)
   매 스텝:
     a. 현재 시뮬레이션 시각 계산
     b. active_hours에 해당하는 에이전트만 필터
     c. activity_level 가중치로 발언 에이전트 선택
     d. RuleAgent: 확률 기반 투표 (sentiment + 이웃 영향)
     e. LLM Agent: 토론 맥락 기반 발언 (ForumEngine 재활용)
     f. SQLite에 행동 기록
    ↓
3. 결과 집계
   - 스텝별 여론 분포 변화 추적
   - 최종 여론: 가중 투표 집계 (influence_weight 반영)
   - 토론 결과와 시뮬레이션 결과 일치도 검증
    ↓
4. 불일치 시 → 추가 토론 라운드 권장 (feedback loop)
```

#### 리소스

| 항목 | 사양 |
|------|------|
| 규칙 에이전트 100~500개 | ~100MB RAM |
| env.step() 50회 | CPU only, ~5초 |
| LLM 대표 에이전트 3~7개 | 기존 ForumEngine 공유 |
| SQLite trace | ~10MB per simulation |

**OASIS 시뮬레이션은 선택적(optional)이다.** ForumEngine 토론 결과만으로도 L4 평가 + L5 리포트 생성이 가능하다. OASIS는 대규모 여론 검증이 필요할 때 추가 레이어로 사용한다.

### ForumEngine에서의 에이전트 선택 (OASIS 패턴 적용)

토론 매 라운드에서도 OASIS 패턴을 적용하여 에이전트 선택:

```
매 라운드:
  1. 현재 시뮬레이션 시각 계산
  2. active_hours에 해당하는 에이전트만 필터
  3. activity_level 가중치로 발언 순서 결정
  4. influence_weight가 높은 에이전트 발언에 더 많은 응답 유도
```

### 토론 형식 프리셋 (기존 DebateFormat 대체)

기존 5개 형식을 ForumEngine 파라미터로 흡수:

| 기존 Format | ForumConfig 프리셋 |
|-------------|-------------------|
| ADVERSARIAL | `confrontation=high, agents=2, cross_team=true` |
| COLLABORATIVE | `confrontation=low, team_integration=true` |
| COMPETITIVE | `confrontation=medium, specialized_pipeline=true` |
| (OXFORD 미구현) | 제거 |
| (ROUNDTABLE 미구현) | 제거 |

### 종료 조건

| 조건 | 판정 주체 | 방식 |
|------|-----------|------|
| 최대 라운드 도달 | 시스템 | `max_rounds` 설정값 |
| 합의 도달 | 모더레이터 LLM | "양측이 수렴" 판정 |
| 교착 상태 | 모더레이터 LLM | "새로운 논점 없음" 판정 |
| 반복 감지 | 시스템 | 직전 2라운드 **임베딩 유사도** > 임계값 |

---

## L4: 평가 + 예측 (Evaluation & Prediction)

기존 M-MAD 8차원 평가를 **100% 보존**하면서, 임베딩 보강과 클러스터 가중 예측을 추가한다.

### M-MAD 평가 (RETAINED)

| 차원 | 가중치 | 보강 |
|------|--------|------|
| logical_coherence | 1.5 | 논리적 오류 패턴 5 → 15로 확장 |
| evidence_quality | 1.3 | 유지 |
| persuasiveness | 1.2 | 유지 |
| relevance | 1.4 | **임베딩 cosine similarity 보강** |
| originality | 1.0 | **임베딩 cosine distance 보강** |
| clarity | 1.1 | 유지 |
| factual_accuracy | 1.3 | LLM 보강 옵션 추가 |
| emotional_appeal | 0.8 | 유지 |

### 임베딩 기반 보강 (NEW)

```python
class EmbeddingSimilarity:
    """sentence-transformers 재사용 (L1 클러스터링과 동일 모델)"""
    def cosine_similarity(a, b) -> float
    def evaluate_relevance(argument, topic) -> float      # 키워드 → 임베딩
    def evaluate_originality(argument, history) -> float   # Jaccard → 임베딩
    def detect_repetition(round_n, round_n_minus_1) -> bool
```

Jaccard는 임베딩 미사용 시(GPU 없음 등) fallback으로 보존.

### 클러스터 가중 예측 (NEW)

```python
class PredictionResult(BaseModel):
    topic: str
    cluster_predictions: List[ClusterPrediction]
    dominant_opinion: str
    confidence: float
    consensus_level: float

class ClusterPrediction(BaseModel):
    cluster_label: str
    weight: float                  # 원래 클러스터 비중
    debate_score: float            # M-MAD 토론 평가 점수
    weighted_score: float          # weight × debate_score × (1 + stance_shift)
    key_arguments_survived: List[str]
```

### 제거된 Anti-pattern

- **자기평가(self_evaluation) 제거**: 에이전트가 자신을 평가 → 점수 부풀리기. 상대방 평가만 유지.
- **하드코딩 점수 스텁 제거**: `_evaluate_logic() → return 0.7` 같은 미구현 스텁 삭제.

---

## L5: 리포트 생성 + OpenClaw 전달

### ReACT 리포트 (MiroFish 패턴)

```
Phase 1 — Planning (temperature 0.3)
  → 구조화된 리포트 개요 생성

Phase 2 — Generation (temperature 0.5)
  → 섹션별 ReACT 루프 (최대 5회 반복):
     Thought → Action (도구 호출) → Observation
  → 섹션당 최소 3회 도구 호출

Phase 3 — Reflection
  → 완성도/정확성 검증
```

### 리포트 구성

1. **요약** — 1문단 결론
2. **여론 분포** — 클러스터별 비중 + 가중 점수 (plotly 차트)
3. **핵심 쟁점** — 토론 최다 논점 Top 5
4. **토론 하이라이트** — 모더레이터 선정 핵심 교환 3~5개
5. **예측 근거** — 지배적 여론의 살아남은 논점 + 출처
6. **반론 요약** — 소수 의견 핵심 반론 (편향 방지)

### OpenClaw 채널 전달

| 채널 | 포맷 |
|------|------|
| Telegram | Markdown, 긴 결과 분할 전송 |
| Discord | Embed, 색상 코드 (찬성=초록/반대=빨강) |
| Slack | Block Kit |
| Web | HTML rich format |

### OpenClaw Extension 구조

```
extensions/ai-debate/
  package.json            # openclaw.plugin.json 호환
  src/
    index.ts              # Extension entry point
    commands.ts           # /debate start, /debate status, /debate results
    bridge.ts             # HTTP client → /api/v2/* 호출
    formatter.ts          # 채널별 포맷팅
```

### OpenClaw Workspace 연동

```
~/.openclaw/workspace/memory/debates/{pipeline_id}/
  context.json            # 토론 주제, 설정, 참여 에이전트
  clusters.json           # 의견 클러스터 정보
  transcript.jsonl        # 토론 기록
  evaluation.json         # 평가 결과
  report.md               # 최종 리포트
```

---

## 기존 코드 재활용 전략

### 리팩토링 순서 (매 단계 서버 실행 가능 유지)

**Step 1: Extract-without-breaking**
1. `agents/base.py` 생성 — `_call_llm()` 등 핵심 LLM 통신 추출
2. `debate_agent.py`에서 `BaseLLMAgent` 상속으로 전환
3. `MultiAgentDebater` 삭제 (즉시, 사용처 없음)
4. API 키 print 출력 삭제 (즉시, 보안)

**Step 2: API layer split**
1. `api/` 디렉토리 생성, 라우터 파일 생성
2. `final_web_app.py` 엔드포인트를 하나씩 라우터로 이동
3. `main.py`가 `final_web_app.py` 대체

**Step 3: Evaluation upgrade**
1. `evaluation/` 디렉토리, 기존 evaluator 이동
2. `evaluation/embeddings.py` 추가 (임베딩 있으면 사용, 없으면 Jaccard fallback)
3. `debate_evaluator.py` → redirect wrapper

**Step 4: New modules**
1. `clustering/` 추가 — 독립 모듈
2. `agents/factory.py`, `agents/moderator.py` 추가
3. `forum/engine.py` 추가 — 새 엔드포인트 노출
4. 기존 `/api/debate/` 유지 (호환)

**Step 5: Integration & switchover**
1. ForumEngine이 DebateController 완전 대체 확인
2. `debate_controller.py` → deprecated wrapper
3. OpenClaw bridge 연결

---

## Phase별 구현 로드맵

### Phase 1: Foundation Extraction (1~2주)

죽은 코드 제거, 구조 분리, 테스트 인프라.

| 태스크 | 산출물 |
|--------|--------|
| Dead code 제거 | MultiAgentDebater, OXFORD/ROUNDTABLE, 죽은 설정, API 키 print |
| `agents/base.py` 추출 | BaseLLMAgent (_call_llm, streaming, thinking) |
| `api/` 분리 | final_web_app.py → 6개 라우터 |
| `evaluation/` 이동 | debate_evaluator.py → evaluation/ + redirect |
| `models/schemas.py` | 전 레이어 Pydantic 모델 정의 |
| CORS/CSP 수정 | `["*"]` → Settings 기반, nonce CSP |
| 테스트 프레임워크 | pytest 설정, characterization tests |

**완료 기준**: `python main.py`로 기존 기능 100% 동작. 죽은 코드 0줄.

### Phase 2: New Core (2~3주)

Clustering + ForumEngine + Agent Factory.

| 태스크 | 산출물 |
|--------|--------|
| `clustering/engine.py` | SentenceTransformer + HDBSCAN → ClusterProfile[] |
| `clustering/data_collector.py` | arXiv, RSS, 사용자 텍스트 수집기 |
| `agents/factory.py` | PersonaFactory: ClusterProfile → ForumAgent |
| `agents/moderator.py` | ForumHost: 별도 모델, N개 발언마다 개입 |
| `forum/engine.py` | 로그 기반 pub/sub, LogMonitor, ForumReader |
| `forum/config.py` | ForumConfig + 형식 프리셋 |
| `api/routes/forum.py` | 새 파이프라인 엔드포인트 |

**완료 기준**: 주제 입력 → 클러스터 3~7개 → 대표 에이전트 → ForumEngine 3라운드 토론.

### Phase 3: OASIS 시뮬레이션 + 평가 강화 (1~2주)

OASIS 패턴 자체 구현, 평가 강화, 예측.

| 태스크 | 산출물 |
|--------|--------|
| `oasis_sim/engine.py` | async step loop (~200줄, 의존성 제로) |
| `oasis_sim/rule_agent.py` | RuleAgent (LLM 없음, 규칙 기반 투표) |
| `oasis_sim/agent_graph.py` | 클러스터→에이전트 그래프 (비례 생성) |
| `oasis_sim/trace.py` | SQLite 행동 추적 + 여론 분포 집계 |
| `evaluation/embeddings.py` | 임베딩 similarity/relevance/originality |
| `evaluation/predictor.py` | 클러스터 가중 예측 + OASIS 결과 통합 |

**완료 기준**: 100개 규칙 에이전트 시뮬레이션 < 10초. 토론 결과 vs 시뮬레이션 결과 비교 리포트 출력.

### Phase 4: OpenClaw 연동 + Polish (1~2주)

OpenClaw 통합, 리포트, 배포.

| 태스크 | 산출물 |
|--------|--------|
| `bridge/openclaw.py` | OpenClaw extension bridge |
| `report/generator.py` | ReACT 리포트 + plotly 시각화 |
| `config/models.yaml` | OPENROUTER_MODELS 외부화 |
| WebSocket 인증 | 토큰 + rate limiting |
| Docker compose 업데이트 | 새 구조 반영 |
| 프론트엔드 분리 | 3027줄 HTML → template + JS + CSS |

**완료 기준**: OpenClaw에서 `/debate start` 실행 → 전체 파이프라인 E2E 동작 → 채널 전달.

---

## 기술 스택

### 기존 유지

| 라이브러리 | 용도 |
|-----------|------|
| fastapi, uvicorn | Web framework |
| httpx | Async HTTP (LLM 호출) |
| pydantic, pydantic-settings | 데이터 검증 |
| numpy | 수치 연산 |
| websockets | 실시간 스트리밍 |
| psutil | 시스템 모니터링 |

### 신규 추가

| 라이브러리 | 용도 | 선택 근거 |
|-----------|------|-----------|
| sentence-transformers | 텍스트 임베딩 | L1 클러스터링 + L4 평가 공유. 로컬 GPU 가속 |
| hdbscan | 밀도 기반 클러스터링 | 자동 클러스터 수, 노이즈 처리 |
| scikit-learn | K-Means fallback, TF-IDF | HDBSCAN 보완 |
| aiosqlite | 비동기 SQLite | 세션 스토어 (dev) |
| plotly | 인터랙티브 차트 | 리포트 시각화 |
| feedparser | RSS 파싱 | L0 뉴스 수집 |
| arxiv | arXiv API | L0 학술 수집 |

### 의도적으로 제외

| 기술 | 제외 이유 |
|------|-----------|
| LangChain/LlamaIndex | 오버엔지니어링. httpx 직접 호출로 충분 |
| ChromaDB/Vector DB | 문서 100~1000개에 numpy 유사도 계산으로 충분 |
| Redis/Kafka | 에이전트 3~7개에 과잉. JSONL 파일로 충분 |
| Zep Cloud | 단기 세션이므로 장기 기억 불필요 |
| GraphRAG | 구현 복잡도 대비 이점 불명확. Phase 4 이후 재검토 |

---

## 하드웨어 리소스 할당

```
GB10 Node 1 (120GB):
  ├─ Ollama: 토론 에이전트 모델 (~80GB)
  ├─ sentence-transformers (~2GB)
  └─ 시스템 + 앱 (~38GB)

GB10 Node 2 (120GB):
  ├─ Ollama: ForumHost 모더레이터 (다른 계열 모델)
  ├─ OASIS 시뮬레이션 (~100MB, CPU only, LLM 불필요)
  └─ 시스템 + 앱

동시 LLM 에이전트: 최대 20~30
OASIS 규칙 에이전트: 100~500 (LLM 제로, CPU only)
```

---

## 부록: BettaFish/MiroFish 흡수 요약

| 레퍼런스 | 흡수한 것 | 흡수하지 않은 것 |
|----------|-----------|------------------|
| BettaFish ForumEngine | 로그 기반 pub/sub, 별도 모델 모더레이터, 발언 N개 누적 후 개입, ForumReader 프롬프트 주입 | 웨이보/샤오홍슈 크롤러 (중국 소셜미디어 특화), BERT/GPT-2 파인튜닝 감성분석 |
| MiroFish OASIS | 듀얼 티어 에이전트 (규칙+LLM), activity_level/active_hours/influence_weight, env.step() 패턴 **자체 구현** (~200줄, oasis_sim/), 에이전트 그래프, SQLite trace, ReACT 리포트 생성 | camel-oasis 패키지 직접 사용 (소셜미디어 하드코딩, 2~4GB 의존성), Zep Cloud 장기 기억, GraphRAG 풀 구현, TwitterEnv/RedditEnv |
| OpenClaw | Extension 브릿지, 멀티채널 전달, 워크스페이스 메모리 연동 | ACP 멀티에이전트 라우팅 (향후 확장), Canvas UI |
