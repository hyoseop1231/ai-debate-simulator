# 🚀 AI 토론 시뮬레이터 - 빠른 시작 가이드

> **3분만에 AI 토론을 시작하세요!**

## ⚡ 초고속 시작 (3단계)

### 1️⃣ 의존성 설치
```bash
pip install -r requirements.txt
```

### 2️⃣ Ollama 서버 실행
```bash
# 터미널 1: Ollama 서버 시작
ollama serve

# 터미널 2: 모델 다운로드 (처음 한 번만)
ollama pull qwen3:30b-a3b  # 추천 모델 (고성능)
ollama pull llama3.2:3b    # 백업 모델 (빠름)
```

### 3️⃣ 웹 서버 실행
```bash
# 서버 시작
python start_server_simple.py

# 또는 직접 실행
python final_web_app.py
```

## 🌐 브라우저 접속
```
http://localhost:8003
```

## 🎯 기본 사용법

### 토론 시작하기
1. **브라우저 접속** → http://localhost:8003
2. **토론 주제 입력** → "AI가 일자리를 대체하는 것이 바람직한가?"
3. **토론 형식 선택** → 대립형 토론 (추천)
4. **모델 선택** → qwen3:30b-a3b (자동 선택됨)
5. **토론 시작** 버튼 클릭 ✨

### 토론 형식별 특징
- **🔥 대립형**: 천사 vs 악마 - 극명한 대립
- **🤝 협력형**: 연구팀 간 협력적 경쟁  
- **⚡ 경쟁형**: 블루팀 vs 레드팀 경쟁
- **🎨 커스텀**: 자유로운 설정

## 🧪 테스트 도구

### 연결 확인
```bash
# Ollama 연결 테스트
python test_ollama.py

# 토론 시스템 테스트
python test_debate.py
```

### 상태 확인
- **Ollama API**: http://localhost:11434
- **서버 상태**: http://localhost:8003/api/status
- **API 문서**: http://localhost:8003/docs

## 🆘 문제 해결

### 🔴 "Ollama 서버에 연결할 수 없습니다"
```bash
# 1. Ollama 실행 상태 확인
curl http://localhost:11434/api/tags

# 2. Ollama 재시작
ollama serve

# 3. 모델 설치 확인
ollama list
```

### 🔴 "포트 8003이 이미 사용 중입니다"
```bash
# 사용 중인 프로세스 확인
lsof -i :8003

# 프로세스 종료
kill -9 <PID>
```

### 🔴 "모델을 찾을 수 없습니다"
```bash
# 추천 모델 다운로드
ollama pull qwen3:30b-a3b

# 빠른 백업 모델
ollama pull llama3.2:3b

# 설치된 모델 확인
ollama list
```

### 🔴 브라우저에서 페이지가 로드되지 않음
1. **하드 리프레시**: `Ctrl+F5` (Windows) / `Cmd+Shift+R` (Mac)
2. **개발자 도구**: `F12`로 콘솔 에러 확인
3. **포트 확인**: http://localhost:8003 정확한지 확인

## 💡 최신 기능 (2024년 업데이트)

### ✨ 새로운 경험
- **깜빡거림 완전 제거**: 부드러운 스트리밍
- **자연스러운 AI 대화**: 친구와 대화하듯 자연스러운 톤
- **사고 과정 시각화**: AI의 thinking 프로세스 실시간 확인
- **글자 단위 타이핑**: 마치 사람이 타이핑하는 것처럼

### 🎪 토론 보는 재미
- AI들이 **"아! 이것 봐요"**, **"잠깐, 그건 좀 이상한데요?"** 같은 자연스러운 표현 사용
- 각 AI마다 고유한 성격과 말투
- 실시간으로 펼쳐지는 사고 과정

## 🎯 권장 설정

### 💻 시스템 요구사항
- **Python**: 3.8+ 
- **RAM**: 8GB+ (qwen3:30b-a3b 사용시)
- **저장공간**: 20GB+ (모델 다운로드용)

### 🚀 최적 성능을 위한 팁
1. **qwen3:30b-a3b 모델 사용** (가장 자연스러운 대화)
2. **유선 인터넷 연결** (모델 다운로드시)
3. **브라우저 최신 버전** 사용
4. **다른 무거운 프로그램 종료**

## 📚 더 알아보기

- **전체 문서**: [README.md](README.md)
- **개선사항**: [improvements_summary.md](improvements_summary.md)  
- **API 문서**: http://localhost:8003/docs
- **GitHub**: 이슈 및 기여는 GitHub에서

## 🎉 성공적인 첫 토론을 위한 추천 주제

### 🔥 인기 주제
- "AI가 일자리를 대체하는 것이 바람직한가?"
- "기본소득제 도입이 필요한가?"
- "원격근무가 오프라인 근무보다 효율적인가?"
- "소셜미디어가 사회에 미치는 영향은 긍정적인가?"

### 🎭 재미있는 주제  
- "파인애플 피자는 정당한가?"
- "고양이 vs 강아지, 더 나은 반려동물은?"
- "아침형 인간 vs 올빼미형 인간, 누가 더 우수한가?"

---

**🎪 준비 완료! 이제 AI들의 흥미진진한 토론을 즐겨보세요!**

> *문제가 생기면 F12 개발자 도구를 열어 콘솔 메시지를 확인해보세요.*