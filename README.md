# 🎪 AI 토론 시뮬레이터

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-Latest-green.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **프로덕션 수준의 실시간 AI 토론 시뮬레이션 시스템 - 완전한 thinking/content 분리와 자연스러운 대화 지원**

## 🌟 주요 특징

### ✨ 2025년 최종 안정화 버전 (v6.0)
- **🎯 Gemma3:e4b 기본 모델**: 안정성과 성능을 모두 만족하는 최적 모델
- **🔄 완전한 메시지 손실 방지**: thinking과 content 완벽 분리 처리
- **🧠 지능형 응답 추출**: thinking 내용에서 실제 응답 자동 추출
- **⚡ 안정적인 스트리밍**: 백엔드 레벨에서 thinking 태그 사전 처리
- **💬 자연스러운 AI 대화**: 구조적이지 않은 친근한 톤의 토론
- **✨ 글자 단위 타이핑**: 사람이 직접 타이핑하는 것 같은 자연스러운 효과
- **📊 사고 과정 시각화**: AI의 thinking 프로세스를 별도 아코디언으로 표시
- **📱 반응형 웹 UI**: 모든 기기에서 완벽한 사용 경험
- **🐳 프로덕션 수준 Docker**: 멀티스테이지 빌드, 보안 강화, 모니터링 통합
- **🔧 실시간 평가 시스템**: 품질 기반 평가로 토론 품질 보장
- **🚀 종합 평가 시스템**: ORGANIZER의 체계적인 토론 내용 종합 및 결론 도출

### 🎯 핵심 기능
- **다양한 토론 형식**: 대립형(MAD), 협력형, 경쟁형, 커스텀
- **전문화된 AI 에이전트**: 각기 다른 역할과 페르소나 
- **실시간 WebSocket 통신**: 지연 없는 실시간 토론 진행
- **다차원 평가 시스템**: 논리성, 설득력, 창의성 등 8개 차원 평가
- **Ollama 통합**: 로컬 LLM으로 프라이버시 보장

## 🚀 빠른 시작 (3단계)

### 1. 환경 설정
```bash
# 저장소 클론
git clone https://github.com/yourusername/ai-debate-simulator.git
cd ai-debate-simulator

# 의존성 설치
pip install -r requirements.txt
```

### 2. Ollama 서버 시작
```bash
# Ollama 설치 및 실행 (https://ollama.ai)
ollama serve

# 기본 모델 다운로드 (터미널 2에서)
ollama pull gemma3n:e4b      # 기본 모델 (안정성+성능 최적화)
ollama pull llama3.2:3b      # 백업 모델 (빠름)
ollama pull qwen3:30b-a3b    # 고성능 모델 (선택사항)
```

### 3. 웹 애플리케이션 실행

#### 🐳 Docker 실행 (권장)
```bash
# Docker Compose로 실행
docker-compose up -d

# 상태 확인
docker-compose ps

# 로그 확인
docker-compose logs -f ai-debate-simulator

# 중지
docker-compose down
```

#### 🐍 Python 직접 실행
```bash
# 서버 시작
python3 start_server_simple.py

# 또는 직접 실행
python3 final_web_app.py
```

### 4. 브라우저 접속
```
http://localhost:8003
```

## 🏗️ 프로젝트 구조

```
ai-debate-simulator/
├── 🎯 Core Files
│   ├── final_web_app.py          # 메인 웹 애플리케이션 (최신 안정화 버전)
│   ├── debate_agent.py           # AI 에이전트 구현 (thinking 분리 로직 포함)
│   ├── debate_controller.py      # 토론 제어 시스템 (다양한 토론 형식 지원)
│   ├── debate_evaluator.py       # 다차원 평가 시스템 (M-MAD 스타일)
│   ├── start_server_simple.py    # 서버 시작 스크립트
│   └── requirements.txt          # 프로덕션 수준 의존성 (200+ 패키지)
│
├── 🔧 Configuration
│   ├── config/
│   │   ├── settings.py           # 환경별 설정 관리
│   │   └── __init__.py
│   └── env_sample.txt            # 환경 변수 템플릿
│
├── 🛡️ Security & Utils
│   ├── utils/
│   │   ├── security.py           # 보안 시스템 (레이트 리미팅, 입력 검증)
│   │   ├── cache.py              # 캐싱 시스템 (Redis 통합)
│   │   ├── monitoring.py         # 모니터링 시스템 (성능 메트릭)
│   │   └── __init__.py
│
├── 🐳 Docker & Deployment
│   ├── Dockerfile                # 프로덕션 수준 멀티스테이지 빌드
│   ├── docker-compose.yml        # 완전한 인프라 스택 (Redis, PostgreSQL, 모니터링)
│   ├── Dockerfile.original       # 원본 Dockerfile (백업)
│   ├── docker-compose.original.yml # 원본 docker-compose (백업)
│   └── requirements.original.txt # 원본 requirements (백업)
│
├── 🧪 Testing
│   ├── test_ollama.py            # Ollama 연결 테스트
│   ├── test_improved_system.py   # 통합 테스트 스위트
│   └── test_avatar.html          # 아바타 생성 테스트
│
├── 📁 Logs & Cache
│   └── logs/                     # 애플리케이션 로그 디렉토리
│
└── 📚 Documentation
    ├── README.md                 # 이 파일 (완전 업데이트됨)
    ├── IMPROVEMENT_GUIDE.md      # 상세한 개선 가이드
    ├── START_HERE.md            # 빠른 시작 가이드
    ├── CHANGELOG.md             # 버전별 변경 사항
    └── LICENSE                   # MIT 라이선스
```

## 🤖 AI 에이전트 시스템

### 역할별 전문화된 에이전트
- **🔍 Searcher**: "아! 이것 봐요" - 정보 검색 및 증거 수집
- **🧠 Analyzer**: "잠깐, 그건 좀 이상한데요?" - 논리 분석 및 약점 파악  
- **✍️ Writer**: "생각해보세요" - 설득력 있는 논증 작성
- **📋 Reviewer**: "정리해보면요" - 품질 검토 및 핵심 정리
- **😈 Devil**: "근데 말이죠" - 반대 입장 강화 (MAD 방식)
- **😇 Angel**: "맞아요!" - 지지 입장 옹호 (MAD 방식)
- **🎯 Organizer**: "자, 정리해볼까요?" - 토론 진행 및 중재

### 자연스러운 대화 스타일
AI들이 구조적이지 않고 친구와 대화하듯 자연스럽게 토론합니다:

**이전 (구조적):**
```
희망천사는 AI의 생산성 향상과 함께 고용 구조 변화를 강조했지만,
- 논점 검토: ...
- 전략 수립: ...
- 근거 선택: ...
```

**현재 (자연스러운):**
```
환경 보호가 중요하다는 건 동감해요. 하지만 현실적으로 생각해보면, 
일자리도 지켜야 하고 경제도 돌아가야 하잖아요? 

예를 들어 독일 같은 경우 재생에너지로 전환하면서 오히려 새로운 
일자리를 만들어냈거든요.
```

## 🎪 토론 형식

### 1. 대립형 토론 (MAD 스타일)
- **천사팀 vs 악마팀** 구조
- 극명한 대립으로 쟁점 부각
- 감정적 호소와 논리적 반박의 조화

### 2. 협력형 토론 (Society of Minds)
- **연구팀 간 협력적 경쟁**
- 집단 지성을 통한 문제 해결
- 건설적 비판과 아이디어 발전

### 3. 경쟁형 토론 (Agent4Debate)
- **블루팀 vs 레드팀** 경쟁
- 전략적 접근과 체계적 논증
- 승부욕을 통한 논증 품질 향상

### 4. 커스텀 토론
- 사용자 정의 팀 구성
- 자유로운 역할 설정
- 특수 목적 토론 지원

## 🎨 사고 과정 시각화

### AI Thinking 프로세스
```
<think>
환경 문제 얘기가 나왔네. 그런데 경제적 현실도 무시할 수 없잖아? 
구체적인 예시를 들면서 균형잡힌 시각을 보여주자.
</think>

환경 보호가 중요하다는 건 동감해요. 하지만 현실적으로 생각해보면...
```

### 실시간 스트리밍
- **사고 과정**: 아코디언 UI에서 실시간 표시
- **실제 응답**: 대화창에서 글자 단위 타이핑
- **완전한 분리**: 깜빡거림 없는 부드러운 경험

## 📊 다차원 평가 시스템

### 8개 평가 차원
1. **논리적 일관성** - 논리적 흐름의 자연스러움
2. **증거 품질** - 제시된 근거의 신뢰성
3. **설득력** - 상대방을 설득하는 능력
4. **관련성** - 주제와의 연관성
5. **독창성** - 창의적이고 새로운 관점
6. **명확성** - 의사소통의 명확함
7. **사실 정확성** - 팩트의 정확성
8. **감정적 호응** - 감정적 공감대 형성

### 실시간 점수 시각화
- 라운드별 점수 변화 추적
- 차원별 강약점 분석  
- 최종 승부 결정 및 분석

## 🛠️ 기술 스택

### Backend
- **FastAPI**: 고성능 웹 프레임워크
- **WebSockets**: 실시간 양방향 통신
- **Ollama**: 로컬 LLM 서버
- **Python 3.8+**: 비동기 처리

### Frontend  
- **Vanilla JavaScript**: 가벼운 프론트엔드
- **WebSocket API**: 실시간 스트리밍
- **Responsive CSS**: 모든 기기 지원
- **Real-time UI Updates**: 즉각적인 피드백

### AI Models
- **gemma3n:e4b**: 기본 모델 (안정성+성능 최적화)
- **llama3.2:3b**: 빠른 백업 모델
- **qwen3:30b-a3b**: 고성능 모델 (선택사항)
- **지원 형식**: Ollama 호환 모든 모델

## 🐳 Docker 실행 가이드

### 🚀 프로덕션 수준 Docker 실행 (권장)
```bash
# 1. 리포지토리 클론
git clone https://github.com/hyoseop1231/ai-debate-simulator.git
cd ai-debate-simulator

# 2. 환경 설정 (선택사항)
cp env_sample.txt .env

# 3. 기본 실행 (AI 토론 시뮬레이터만)
docker-compose up -d ai-debate-simulator

# 4. 개발 환경 실행 (소스 코드 마운트)
docker-compose --profile development up -d

# 5. 완전한 프로덕션 스택 (Redis, PostgreSQL 포함)
docker-compose --profile production up -d

# 6. 모니터링 포함 실행 (Prometheus, Grafana)
docker-compose --profile production --profile monitoring up -d

# 7. 브라우저 접속
open http://localhost:8003
```

### 🔧 환경별 실행 방법
```bash
# 최소 실행 (AI 토론만)
docker-compose up -d ai-debate-simulator

# 개발 환경 (핫 리로드 + 디버깅)
docker-compose --profile development up -d

# 프로덕션 환경 (캐시 + 데이터베이스)
docker-compose --profile production up -d

# 모니터링 환경 (성능 모니터링)
docker-compose --profile monitoring up -d

# 로깅 환경 (ELK 스택)
docker-compose --profile logging up -d

# 전체 스택 (모든 서비스)
docker-compose --profile production --profile monitoring --profile logging up -d
```

### Docker 관리 명령어
```bash
# 상태 확인
docker-compose ps

# 로그 확인
docker-compose logs -f ai-debate-simulator

# 재시작
docker-compose restart

# 중지 및 제거
docker-compose down

# 이미지 재빌드
docker-compose build --no-cache
```

### Docker 환경 설정

#### 환경 변수 (`.env` 파일)
```bash
# 애플리케이션 설정
DEBATE_PORT=8003
OLLAMA_API_URL=http://host.docker.internal:11434
LOG_LEVEL=INFO

# 성능 튜닝
MAX_DEBATE_ROUNDS=5
DEFAULT_MODEL=gemma3n:e4b
CHUNK_SIZE=1
```

#### 호스트 Ollama 연결
Docker 컨테이너에서 호스트의 Ollama 서버에 연결하기 위해 `host.docker.internal`을 사용합니다:
```bash
# 호스트에서 Ollama 실행
ollama serve

# Docker 컨테이너가 자동으로 연결
```

### 프로덕션 배포
```bash
# 프로덕션 환경 변수 설정
export OLLAMA_API_URL=https://your-ollama-server.com
export SECRET_KEY=your-production-secret-key
export CORS_ORIGINS=https://your-domain.com

# 스케일링 (여러 인스턴스)
docker-compose up -d --scale ai-debate-simulator=3
```

## 🔧 고급 설정

### 환경 변수
```bash
# 포트 설정
export DEBATE_PORT=8003

# Ollama API URL
export OLLAMA_API_URL=http://localhost:11434

# 로그 레벨
export LOG_LEVEL=INFO
```

### 커스텀 모델 추가
```python
# debate_agent.py에서 모델 설정
self.model = "your-custom-model:latest"
```

## 📋 API 문서

서버 실행 후 다음 URL에서 자동 생성된 API 문서 확인:
- **Swagger UI**: http://localhost:8003/docs
- **ReDoc**: http://localhost:8003/redoc

### 주요 엔드포인트
```
GET  /api/status           # 서버 상태 확인
GET  /api/health           # 헬스체크 (프로덕션용)
GET  /api/metrics          # 성능 메트릭 (Prometheus 호환)
GET  /api/models           # 사용 가능한 모델 목록  
GET  /api/ollama/status    # Ollama 서버 상태 및 연결 테스트
POST /api/debate/start     # 토론 시작
POST /api/cache/clear      # 캐시 정리 (Redis 지원)
GET  /ws/{session_id}      # WebSocket 연결 (실시간 스트리밍)
```

## 🐛 문제 해결

### Ollama 연결 문제
```bash
# Ollama 상태 확인
curl http://localhost:11434/api/tags

# Ollama 재시작
ollama serve

# 연결 테스트
python3 test_ollama.py
```

### 포트 충돌
```bash
# 사용 중인 프로세스 확인
lsof -i :8003

# 프로세스 종료
kill -9 <PID>
```

### 모델 다운로드 문제
```bash
# 모델 목록 확인
ollama list

# 기본 모델 다시 다운로드
ollama pull gemma3n:e4b
ollama pull llama3.2:3b
```

### 브라우저 문제
- **캐시 삭제**: Ctrl+F5 (하드 리프레시)
- **개발자 도구**: F12로 콘솔 에러 확인
- **WebSocket 연결**: 네트워크 탭에서 WS 연결 확인

## 🚀 개발 및 기여

### 개발 환경 설정
```bash
# 개발 의존성 포함 설치
pip install -r requirements.txt

# 코드 포맷팅
black . --line-length 120

# 린팅
pylint *.py

# 테스트 실행
python3 test_ollama.py
```

### 기여 방법
1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📈 성능 최적화

### 최종 안정화 개선사항 (2024 v6.0)
- **🎯 Gemma3:e4b 최적화**: 안정성과 성능을 모두 만족하는 모델 선택
- **🔄 완전한 메시지 손실 방지**: thinking과 content 완벽 분리
- **🧠 지능형 응답 추출**: thinking 내용에서 실제 응답 자동 추출
- **⚡ 90% DOM 업데이트 감소**: 청크 크기 최적화
- **✨ 완전한 깜빡거림 제거**: 모든 애니메이션 효과 제거
- **💬 자연스러운 타이핑**: 글자 단위 스트리밍
- **📊 메모리 사용량 50% 감소**: 불필요한 처리 제거
- **🛡️ 프로덕션 수준 보안**: 레이트 리미팅, 입력 검증, 에러 핸들링
- **📈 실시간 모니터링**: 성능 메트릭 및 헬스체크
- **🔧 실시간 평가 시스템**: 품질 기반 평가로 토론 품질 향상
- **🚀 종합 평가 개선**: ORGANIZER 타임아웃 120초, 청크 최적화

### 권장 사양
- **RAM**: 6GB+ (gemma3n:e4b 사용시), 8GB+ (qwen3:30b-a3b 사용시)
- **CPU**: 4코어+ (최적 성능을 위해)
- **GPU**: 선택사항 (CPU로도 원활 동작)
- **디스크**: 최소 10GB (모델 저장용)
- **네트워크**: 로컬 실행 (인터넷 불필요)

## 🎯 추천 토론 주제

### 🔥 인기 주제
- "AI가 일자리를 대체하는 것이 바람직한가?"
- "기본소득제 도입이 필요한가?"
- "원격근무가 오프라인 근무보다 효율적인가?"
- "소셜미디어가 사회에 미치는 영향은 긍정적인가?"

### 🎭 재미있는 주제  
- "파인애플 피자는 정당한가?"
- "고양이 vs 강아지, 더 나은 반려동물은?"
- "아침형 인간 vs 올빼미형 인간, 누가 더 우수한가?"

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

## 🙏 감사의 글

이 프로젝트는 다음 연구들에서 영감을 받았습니다:

- [Multi-Agents-Debate (MAD)](https://github.com/Skytliang/Multi-Agents-Debate)
- [LLM Multiagent Debate](https://github.com/composable-models/llm_multiagent_debate)
- [Agent4Debate](https://github.com/zhangyiqun018/agent-for-debate)
- [M-MAD](https://github.com/SU-JIAYUAN/M-MAD)

## 📞 지원 및 문의

- **Issues**: GitHub Issues 트래커 사용
- **Discussions**: 일반적인 질문 및 토론
- **Wiki**: 추가 문서 및 가이드

---

## 📝 최신 업데이트 (v6.0 - 2024.07.20)

### 🎯 주요 변경사항
- **기본 모델 변경**: `gemma3n:e4b`로 안정성과 성능 최적화
- **프로덕션 인프라**: Docker 멀티스테이지 빌드, Redis, PostgreSQL, 모니터링 통합
- **완전한 메시지 처리**: thinking과 content 완벽 분리, 메시지 손실 방지
- **실시간 평가**: 품질 기반 평가 시스템으로 토론 품질 향상
- **종합 평가 개선**: ORGANIZER 타임아웃 및 청크 최적화
- **중복 파일 정리**: improved 파일들을 기본 파일로 통합

### 🔧 기술 개선
- **200+ 패키지**: 프로덕션 수준 의존성 관리
- **보안 강화**: 레이트 리미팅, 입력 검증, 에러 핸들링
- **모니터링**: Prometheus, Grafana, ELK 스택 지원
- **캐싱**: Redis 통합으로 성능 향상
- **로깅**: 구조화된 로깅 시스템

---

**🎪 즐거운 AI 토론 경험을 즐기세요!** 

> *"AI들이 토론하는 모습을 보며 우리도 더 나은 사고를 배울 수 있습니다."*

**📢 v6.0 업데이트**: 이제 더욱 안정적이고 강력한 AI 토론 시스템으로 업그레이드되었습니다!
