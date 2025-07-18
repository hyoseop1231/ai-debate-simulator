"""
토론 에이전트 구현 - GitHub 저장소들의 베스트 프랙티스 통합
"""

from typing import List, Dict, Optional, Tuple
from enum import Enum
from dataclasses import dataclass
import json
import logging
import asyncio
import os

class AgentRole(Enum):
    """Agent4Debate의 역할 기반 접근법"""
    SEARCHER = "searcher"  # 정보 검색 담당
    ANALYZER = "analyzer"  # 논증 분석 담당
    WRITER = "writer"      # 논증 생성 담당
    REVIEWER = "reviewer"  # 품질 검토 담당
    DEVIL = "devil"        # MAD의 반대 입장
    ANGEL = "angel"        # MAD의 지지 입장
    ORGANIZER = "organizer"  # 토론 진행자 (새로 추가)

class DebateStance(Enum):
    """토론 입장"""
    SUPPORT = "support"
    OPPOSE = "oppose"
    NEUTRAL = "neutral"

@dataclass
class Argument:
    """논증 데이터 구조 (KITECH 방식 품질 점수 추가)"""
    content: str
    agent_name: str
    stance: DebateStance
    round_number: int
    evidence: List[str] = None
    confidence_score: float = 0.0
    quality_score: float = 0.7  # KITECH 방식 품질 점수
    
class DebateAgent:
    """통합 토론 에이전트 클래스"""
    
    def __init__(
        self,
        name: str,
        role: AgentRole,
        stance: DebateStance,
        model: str = "llama3.2:3b",
        persona_prompt: str = None,
        temperature: float = 0.7
    ):
        # 환경 변수에서 Ollama API URL 읽기
        self.ollama_api_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
        self.name = name
        self.role = role
        self.stance = stance
        self.model = model
        self.persona_prompt = persona_prompt or self._get_default_persona()
        self.temperature = temperature
        self.argument_history: List[Argument] = []
        self.logger = logging.getLogger(f"DebateAgent.{name}")
        
    def _get_default_persona(self) -> str:
        """역할별 기본 페르소나 프롬프트 (표현력 강화)"""
        personas = {
            AgentRole.SEARCHER: """🔍 당신은 정보 찾기를 좋아하는 사람입니다. 
            "아! 이것 봐요" "자료를 찾아보니까요" 같은 말을 자주 해요. 구체적인 사실이나 데이터로 이야기하세요.""",
            
            AgentRole.ANALYZER: """🧠 당신은 논리적으로 생각하는 걸 좋아해요. 
            "잠깐, 그건 좀 이상한데요?" "논리적으로 보면요" 같은 식으로 말하면서 상대방 주장의 문제점을 찾아주세요.""",
            
            AgentRole.WRITER: """✍️ 당신은 설득을 잘하는 사람이에요. 
            감정적으로 호소하면서도 "생각해보세요" "이게 바로 그 이유에요" 같은 말로 사람들을 설득하세요.""",
            
            AgentRole.REVIEWER: """📋 당신은 정리를 잘하는 사람이에요. 
            "정리해보면요" "핵심은 이거에요" 같은 말을 하면서 중요한 포인트들을 짚어주세요.""",
            
            AgentRole.DEVIL: """😈 당신은 반대 의견을 제시하는 걸 좋아해요. 
            "근데 말이죠" "정말 그럴까요?" 같은 말로 상대방 주장에 의문을 제기하고 반박하세요.""",
            
            AgentRole.ANGEL: """😇 당신은 긍정적이고 희망적인 사람이에요. 
            "맞아요!" "그 점이 정말 좋네요" 같은 말로 좋은 면을 부각시키고 지지해주세요.""",
            
            AgentRole.ORGANIZER: """🎯 당신은 토론을 진행하는 사람이에요. 
            "자, 정리해볼까요?" "양쪽 의견을 들어보니" 같은 말로 공정하게 진행하고 요약해주세요."""
        }
        
        base_instruction = """
        
친구와 대화하듯이 자연스럽게 말하세요. 3-4문장 정도로 간단히 하되 설득력 있게 해주세요.
        """
        
        return personas.get(self.role, "당신은 사려 깊은 토론 참가자입니다. 🤔") + base_instruction
    
    async def generate_argument(
        self,
        topic: str,
        context: List[Argument],
        round_number: int,
        focus_instruction: str = None,
        stream_callback=None
    ) -> Argument:
        """
        논증 생성 - Society of Minds의 컨텍스트 기반 접근법 적용
        스트리밍 지원 추가
        """
        # 컨텍스트에서 관련 정보 추출
        relevant_context = self._extract_relevant_context(context)
        
        # 역할별 특화된 프롬프트 생성
        prompt = self._build_argument_prompt(
            topic, relevant_context, round_number, focus_instruction
        )
        
        # Context7 연구 기반: 비동기 LLM 호출 (스트리밍 옵션)
        response = await self._call_llm(prompt, stream_callback)
        
        # 논증 생성 및 저장 (KITECH 방식 품질 점수 포함)
        argument = Argument(
            content=response['content'],
            agent_name=self.name,
            stance=self.stance,
            round_number=round_number,
            evidence=response.get('evidence', []),
            confidence_score=response.get('confidence', 0.7),
            quality_score=response.get('quality_score', 0.7)  # KITECH 품질 점수
        )
        
        # thinking 내용이 있으면 속성으로 추가
        if 'thinking_content' in response:
            argument.thinking_content = response['thinking_content']
        
        self.argument_history.append(argument)
        return argument
    
    def _extract_relevant_context(self, context: List[Argument]) -> List[Argument]:
        """관련 컨텍스트 추출 - 향상된 대화 맥락 이해"""
        if not context:
            return []
        
        # 1. 직전 발언자의 논증 (직접 응답을 위해)
        last_argument = context[-1] if context else None
        
        # 2. 현재 라운드의 모든 논증 (대화 흐름 이해)
        current_round = context[-1].round_number if context else 1
        current_round_args = [arg for arg in context if arg.round_number == current_round]
        
        # 3. 이전 라운드의 핵심 논증 (논의 연속성)
        previous_round_args = []
        if current_round > 1:
            previous_round_args = [arg for arg in context 
                                 if arg.round_number == current_round - 1][-3:]
        
        # 4. 반대 입장의 최근 논증 (반박 대상)
        opposing_args = [arg for arg in context 
                        if arg.stance != self.stance and arg.stance != DebateStance.NEUTRAL][-2:]
        
        # 5. 같은 팀의 최근 논증 (일관성 유지)
        team_args = [arg for arg in context 
                    if arg.stance == self.stance and arg.agent_name != self.name][-2:]
        
        # 6. 진행자의 최근 정리 (토론 방향 이해)
        organizer_args = [arg for arg in context 
                         if arg.stance == DebateStance.NEUTRAL][-1:]
        
        # 7. 높은 품질의 논증 (중요 포인트)
        high_quality_args = sorted([arg for arg in context 
                                  if hasattr(arg, 'quality_score') and arg.quality_score > 0.8],
                                 key=lambda x: x.quality_score, reverse=True)[:2]
        
        # 모든 관련 논증을 시간순으로 정렬 (중복 제거)
        all_relevant = []
        seen_contents = set()
        
        # 우선순위: 직전 발언 > 현재 라운드 > 반대 입장 > 같은 팀 > 진행자 > 이전 라운드 > 고품질
        for arg in ([last_argument] if last_argument else []) + current_round_args + \
                   opposing_args + team_args + organizer_args + previous_round_args + high_quality_args:
            if arg and arg.content not in seen_contents:
                all_relevant.append(arg)
                seen_contents.add(arg.content)
                if len(all_relevant) >= 8:  # 최대 8개까지만
                    break
        
        return all_relevant
    
    def _build_argument_prompt(
        self,
        topic: str,
        context: List[Argument],
        round_number: int,
        focus_instruction: str = None
    ) -> str:
        """역할별 특화된 프롬프트 생성 - 향상된 대화 맥락 이해"""
        # 직전 발언자 정보 추출
        last_speaker = None
        last_content = None
        if context:
            last_speaker = context[-1].agent_name
            last_content = context[-1].content[:200] + "..." if len(context[-1].content) > 200 else context[-1].content
        
        # 대화 맥락 요약
        context_summary = self._summarize_context(context)
        
        base_prompt = f"""
{self.persona_prompt}

🎯 **토론 정보**
- 주제: {topic}
- 당신의 입장: {self.stance.value}
- 현재 라운드: {round_number}

💬 **대화 맥락**
{context_summary}

📝 **이전 발언들**
{self._format_context(context)}

🎪 **응답 가이드라인**
1. 직전 발언자({last_speaker if last_speaker else '없음'})의 주장에 직접적으로 응답하세요.
2. 대화의 흐름을 자연스럽게 이어가면서 당신의 논점을 제시하세요.
3. 같은 팀원의 주장은 지지하고 보완하세요.
4. 반대 팀의 주장은 논리적으로 반박하세요.
5. 진행자의 정리나 지시사항이 있다면 반영하세요.

"""
        
        # 역할별 특화 지시사항 (한국어로 개선)
        role_instructions = {
            AgentRole.SEARCHER: "🔍 구체적인 증거와 사실을 찾아 제시하세요. '연구에 따르면', '데이터를 보면' 등의 표현을 사용하세요.",
            AgentRole.ANALYZER: "🧠 상대방 논증의 논리적 구조를 분석하고 약점을 찾아내세요. '하지만', '그러나' 등으로 전환하세요.",
            AgentRole.WRITER: "✍️ 설득력 있는 논증을 명확한 논리로 구성하세요. 감정과 이성의 균형을 맞추세요.",
            AgentRole.REVIEWER: "📋 전체 논의를 검토하고 핵심을 강화하세요. '정리하자면', '핵심은' 등을 활용하세요.",
            AgentRole.DEVIL: "😈 가정과 전제에 도전하고 강력한 반박을 제시하세요. '과연 그럴까요?', '다른 관점에서' 등을 사용하세요.",
            AgentRole.ANGEL: "😇 긍정적 측면을 지지하고 강화하세요. '더 나아가', '이것이 바로' 등의 표현을 활용하세요.",
            AgentRole.ORGANIZER: "🎯 양측의 논점을 공정하게 정리하고 토론의 방향을 제시하세요. '지금까지의 논의를 보면' 등을 사용하세요."
        }
        
        prompt = base_prompt + "\n🎭 **역할별 특별 지시**: " + role_instructions.get(self.role, "당신의 역할에 충실하게 응답하세요.")
        
        # 직전 발언에 대한 구체적 응답 지시
        if last_speaker and last_content:
            prompt += f"\n\n💡 **직전 발언 응답 포인트**:\n{last_speaker}의 주장: \"{last_content}\"\n→ 이 주장에 대해 구체적으로 언급하며 시작하세요."
        
        if focus_instruction:
            prompt += f"\n\n⚡ **특별 지시사항**: {focus_instruction}"
        
        prompt += "\n\n당신의 논증을 생성하세요:"
        
        return prompt
    
    def _summarize_context(self, context: List[Argument]) -> str:
        """대화 맥락 요약"""
        if not context:
            return "토론이 막 시작되었습니다."
        
        summary_parts = []
        
        # 현재 라운드 정보
        current_round = context[-1].round_number
        summary_parts.append(f"- 현재 {current_round}라운드 진행 중")
        
        # 각 팀의 최근 입장
        support_args = [arg for arg in context[-5:] if arg.stance == DebateStance.SUPPORT]
        oppose_args = [arg for arg in context[-5:] if arg.stance == DebateStance.OPPOSE]
        
        if support_args:
            summary_parts.append(f"- 지지 팀 최근 주장: {len(support_args)}개 논증 제시")
        if oppose_args:
            summary_parts.append(f"- 반대 팀 최근 주장: {len(oppose_args)}개 논증 제시")
        
        # 주요 쟁점 파악 (간단한 키워드 추출)
        all_content = " ".join([arg.content for arg in context[-5:]])
        if "하지만" in all_content or "그러나" in all_content:
            summary_parts.append("- 현재 의견 대립이 활발함")
        if "동의" in all_content or "맞습니다" in all_content:
            summary_parts.append("- 일부 합의점 발견")
        
        return "\n".join(summary_parts)
    
    def _format_context(self, context: List[Argument]) -> str:
        """컨텍스트 포맷팅 - 향상된 대화 흐름 표시"""
        if not context:
            return "아직 이전 발언이 없습니다."
        
        formatted = []
        current_round = -1
        
        for i, arg in enumerate(context):
            # 라운드 변경 시 구분선 추가
            if arg.round_number != current_round:
                current_round = arg.round_number
                formatted.append(f"\n--- 라운드 {current_round} ---")
            
            # 발언 순서 표시
            order_emoji = "💬" if i == len(context) - 1 else "💭"  # 마지막 발언 강조
            
            # 팀 표시
            team_indicator = ""
            if arg.stance == DebateStance.SUPPORT:
                team_indicator = "🟢"
            elif arg.stance == DebateStance.OPPOSE:
                team_indicator = "🔴"
            else:  # NEUTRAL (진행자)
                team_indicator = "🟡"
            
            # 발언 내용 (긴 내용은 요약)
            content = arg.content
            if len(content) > 300:
                content = content[:297] + "..."
            
            # 품질 점수가 있으면 표시
            quality_indicator = ""
            if hasattr(arg, 'quality_score'):
                if arg.quality_score >= 0.8:
                    quality_indicator = " ⭐"
                elif arg.quality_score >= 0.6:
                    quality_indicator = " ✓"
            
            formatted.append(
                f"{order_emoji} {team_indicator} [{arg.agent_name}]{quality_indicator}: {content}"
            )
        
        return "\n".join(formatted)
    
    async def _check_ollama_health(self) -> bool:
        """Ollama 서비스 상태 확인"""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.ollama_api_url}/api/tags")
                return response.status_code == 200
        except Exception:
            return False
    
    async def _call_llm(self, prompt: str, stream_callback=None) -> Dict:
        """LLM 호출 (Context7 연구 기반 비동기 최적화 + 스트리밍 지원)"""
        import httpx
        import json
        import asyncio
        
        # Ollama 상태 확인
        if not await self._check_ollama_health():
            self.logger.warning("Ollama 서비스가 응답하지 않습니다")
            return await self._generate_intelligent_fallback_async()
        
        # Ollama API 엔드포인트
        api_url = f"{self.ollama_api_url}/api/chat"
        
        # KITECH 방식: 구조화된 시스템 프롬프트 (thinking 태그 포함)
        enhanced_system_prompt = f"""
{self.persona_prompt}

🎯 **토론 응답 가이드라인:**
- 자연스럽고 대화하듯이 응답하세요
- 3-5문장 정도로 간결하되 설득력 있게
- 구체적인 예시나 경험을 들어주세요
- 상대방 말에 직접 반응하면서 시작
- 너무 격식적이지 말고 친근하게

🧠 **사고 과정과 실제 응답 분리:**
다음과 같은 형식으로 응답하세요:

<think>
여기에 간단한 사고 과정을 작성하세요:
- 뭔가 놓친 점이나 반박할 점은?
- 어떤 근거나 예시를 들면 좋을까?
- 상대방에게 어떻게 대답할까?

자연스럽고 간결하게 생각하는 과정을 적어주세요.
</think>

실제 토론 응답을 자연스럽고 대화체로 작성하세요.

**예시:**
<think>
환경 문제 얘기가 나왔네. 그런데 경제적 현실도 무시할 수 없잖아? 구체적인 예시를 들면서 균형잡힌 시각을 보여주자.
</think>

환경 보호가 중요하다는 건 동감해요. 하지만 현실적으로 생각해보면, 일자리도 지켜야 하고 경제도 돌아가야 하잖아요? 

예를 들어 독일 같은 경우 재생에너지로 전환하면서 오히려 새로운 일자리를 만들어냈거든요. 환경 vs 경제가 아니라 둘 다 잡는 방법을 찾는게 더 현실적인 것 같아요.

**중요:** 
1. <think> 태그로 시작하고 </think> 태그로 반드시 닫아주세요.
2. 사고 과정은 간결하고 자연스럽게 작성하세요.
3. 실제 응답은 대화하듯이 친근하게 작성하세요.
4. **비추론 모델의 경우** thinking 태그를 사용하지 않더라도 대체 방식으로 사고과정을 나타내주세요.
"""
        
        # 메시지 구성 (KITECH 패턴 적용)
        messages = [
            {"role": "system", "content": enhanced_system_prompt},
            {"role": "user", "content": f"토론 상황: {prompt}\n\n위 가이드라인에 따라 논리적이고 설득력 있는 응답을 생성해주세요."}
        ]
        
        # API 요청 페이로드 (스트리밍 활성화)
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": bool(stream_callback),  # 콜백이 있으면 스트리밍 모드
            "options": {
                "temperature": self.temperature,
                "top_p": 0.9,           # KITECH 방식: 응답 품질 향상
                "repeat_penalty": 1.1,  # 반복 방지
                "max_tokens": 1000      # 더 긴 응답을 위해 토큰 제한 증가
            }
        }
        
        # Context7 연구 기반: 비동기 재시도 로직
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                # 비동기 API 호출 (Context7 최적화) - 향상된 연결 설정
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(30.0, connect=10.0),
                    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                    follow_redirects=True
                ) as client:
                    if stream_callback:
                        # 스트리밍 모드
                        actual_content = await self._handle_streaming_response(
                            client, api_url, payload, stream_callback
                        )
                        
                        # 스트리밍 응답도 동일한 형식으로 반환
                        analysis_result = await self._analyze_response_quality_async(actual_content)
                        
                        return {
                            'content': analysis_result['cleaned_content'],
                            'evidence': analysis_result['evidence'], 
                            'confidence': analysis_result['confidence'],
                            'quality_score': analysis_result['quality_score']
                        }
                    else:
                        # 일반 모드
                        response = await client.post(api_url, json=payload)
                        response.raise_for_status()
                        
                        data = response.json()
                        content = data.get('message', {}).get('content', '').strip()
                        
                        if not content:
                            raise ValueError("빈 응답 수신")
                        
                        # Context7 방식: 강화된 응답 분석
                        analysis_result = await self._analyze_response_quality_async(content)
                        
                        return {
                            'content': analysis_result['cleaned_content'],
                            'evidence': analysis_result['evidence'],
                            'confidence': analysis_result['confidence'],
                            'quality_score': analysis_result['quality_score']
                        }
                    
            except Exception as e:
                self.logger.warning(f"LLM 호출 시도 {attempt + 1} 실패: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # 지수 백오프
                else:
                    self.logger.error(f"LLM 호출 최종 실패: {e}")
        
        # Context7 방식: 지능형 폴백 시스템
        return await self._generate_intelligent_fallback_async()
    
    async def _handle_streaming_response(self, client, api_url, payload, stream_callback):
        """실시간 스트리밍 thinking 태그 처리"""
        buffer = ""
        in_thinking = False
        thinking_content = ""
        actual_content = ""
        thinking_sent = False
        
        async with client.stream('POST', api_url, json=payload) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                if line.strip():
                    try:
                        chunk_data = json.loads(line)
                        if 'message' in chunk_data and 'content' in chunk_data['message']:
                            chunk = chunk_data['message']['content']
                            buffer += chunk
                            
                            # 버퍼에서 처리 가능한 부분 찾기
                            while True:
                                if not in_thinking:
                                    # thinking 태그 시작 찾기
                                    think_start = buffer.find('<think>')
                                    thinking_start = buffer.find('<thinking>')
                                    
                                    if think_start != -1 and (thinking_start == -1 or think_start < thinking_start):
                                        # <think> 태그 처리
                                        if think_start > 0:
                                            # 태그 이전 내용을 실제 컨텐츠로 (안전하게 처리)
                                            content = buffer[:think_start].strip()
                                            if content:  # 비어있지 않은 경우만 전송
                                                actual_content += content
                                                # 바로 전송 (청크 나누지 않음)
                                                await stream_callback('content_chunk', content)
                                                await asyncio.sleep(0.15)  # 적당한 딜레이
                                        
                                        buffer = buffer[think_start + 7:]  # '<think>' 제거
                                        in_thinking = True
                                        if not thinking_sent:
                                            await stream_callback('thinking_start', '')
                                            thinking_sent = True
                                        
                                    elif thinking_start != -1:
                                        # <thinking> 태그 처리
                                        if thinking_start > 0:
                                            content = buffer[:thinking_start].strip()
                                            if content:  # 비어있지 않은 경우만 전송
                                                actual_content += content
                                                # 바로 전송 (청크 나누지 않음)
                                                await stream_callback('content_chunk', content)
                                                await asyncio.sleep(0.15)  # 적당한 딜레이
                                        
                                        buffer = buffer[thinking_start + 10:]  # '<thinking>' 제거
                                        in_thinking = True
                                        if not thinking_sent:
                                            await stream_callback('thinking_start', '')
                                            thinking_sent = True
                                        
                                    else:
                                        # 태그가 없으면 안전한 부분만 전송 (큰 청크로)
                                        safe_end = buffer.rfind(' ') if ' ' in buffer else -1
                                        if safe_end > 0 and len(buffer) > 100:  # 큰 청크 크기
                                            content = buffer[:safe_end + 1]
                                            actual_content += content
                                            # 바로 전송 (청크 나누지 않음)
                                            await stream_callback('content_chunk', content)
                                            await asyncio.sleep(0.15)  # 적당한 딜레이
                                            buffer = buffer[safe_end + 1:]
                                        else:
                                            break
                                            
                                else:
                                    # thinking 태그 종료 찾기
                                    think_end = buffer.find('</think>')
                                    thinking_end = buffer.find('</thinking>')
                                    
                                    if think_end != -1 and (thinking_end == -1 or think_end < thinking_end):
                                        # </think> 태그 처리
                                        content = buffer[:think_end]
                                        if content.strip():  # 비어있지 않은 경우만 전송
                                            thinking_content += content
                                            # 바로 전송 (청크 나누지 않음)
                                            await stream_callback('thinking_chunk', content)
                                            await asyncio.sleep(0.1)  # 적당한 딜레이
                                        
                                        buffer = buffer[think_end + 8:]  # '</think>' 제거
                                        in_thinking = False
                                        await stream_callback('thinking_complete', thinking_content)
                                        
                                    elif thinking_end != -1:
                                        # </thinking> 태그 처리
                                        content = buffer[:thinking_end]
                                        if content.strip():  # 비어있지 않은 경우만 전송
                                            thinking_content += content
                                            # 바로 전송 (청크 나누지 않음)
                                            await stream_callback('thinking_chunk', content)
                                            await asyncio.sleep(0.1)  # 적당한 딜레이
                                        
                                        buffer = buffer[thinking_end + 11:]  # '</thinking>' 제거
                                        in_thinking = False
                                        await stream_callback('thinking_complete', thinking_content)
                                        
                                    else:
                                        # 태그 종료가 없으면 큰 청크로 전송 (깜빡거림 방지)
                                        if len(buffer) > 100:  # 큰 청크 크기로 업데이트 빈도 줄이기
                                            chunk_to_send = buffer[:100]
                                            thinking_content += chunk_to_send
                                            await stream_callback('thinking_chunk', chunk_to_send)
                                            await asyncio.sleep(0.2)  # 더 긴 딜레이로 깜빡거림 방지
                                            buffer = buffer[100:]
                                        else:
                                            break
                            
                        if chunk_data.get('done', False):
                            break
                            
                    except json.JSONDecodeError:
                        continue
        
        # 스트링 끝에서 남은 버퍼 처리
        if buffer.strip():  # 비어있지 않은 경우만 처리
            if in_thinking:
                # thinking 중에 끝났으면 남은 내용을 thinking으로
                thinking_content += buffer
                await stream_callback('thinking_chunk', buffer)
                await stream_callback('thinking_complete', thinking_content)
            else:
                # 일반 컨텐츠 - 바로 전송
                actual_content += buffer
                # 바로 전송 (청크 나누지 않음)
                await stream_callback('content_chunk', buffer)
                await asyncio.sleep(0.15)  # 적당한 딜레이
        
        # 비추론 모델 대응: thinking 태그가 없는 경우 전체 응답을 처리
        if not thinking_content and actual_content:
            # thinking 태그가 없는 모델의 경우 처음 부분을 가상의 thinking으로 처리
            sentences = actual_content.split('. ')
            if len(sentences) > 1:
                # 처음 1-2문장을 thinking으로 사용
                thinking_part = '. '.join(sentences[:2]) + '.'
                actual_part = '. '.join(sentences[2:]) if len(sentences) > 2 else sentences[-1]
                
                # 가상의 thinking 전송
                await stream_callback('thinking_start', '')
                await stream_callback('thinking_chunk', f"비추론 모델 대응: {thinking_part}")
                await stream_callback('thinking_complete', thinking_part)
                
                # 실제 내용 업데이트
                actual_content = actual_part
        
        # 기본 메시지 처리 - 실제 컨텐츠가 없을 경우만
        if not actual_content.strip():
            if thinking_content:  # thinking은 있지만 실제 컨텐츠가 없는 경우
                default_msg = "[사고 과정은 있지만 실제 응답이 생성되지 않았습니다]"
            else:
                default_msg = "[응답 생성 중 오류가 발생했습니다]"
            await stream_callback('content_chunk', default_msg)
            actual_content = default_msg
        
        self.logger.info(f"스트리밍 완료 - thinking: {len(thinking_content)}자, 실제: {len(actual_content)}자")
        
        # 디버깅: 실제 내용의 시작 부분 확인
        if actual_content:
            self.logger.debug(f"실제 응답 시작: {actual_content[:100]}...")
        
        # 응답 반환
        return actual_content
    
    async def _analyze_response_quality_async(self, content: str) -> Dict:
        """Context7 방식: 비동기 응답 품질 분석"""
        return self._analyze_response_quality(content)
    
    async def _generate_intelligent_fallback_async(self) -> Dict:
        """Context7 방식: 비동기 지능형 폴백"""
        return self._generate_intelligent_fallback()
    
    def _analyze_response_quality(self, content: str) -> Dict:
        """KITECH 방식: 응답 품질 분석 및 개선"""
        
        # 기본 정리
        cleaned_content = content.strip()
        
        # 증거 추출 (강화된 패턴)
        evidence = []
        evidence_patterns = [
            "연구에 따르면", "데이터에 의하면", "통계적으로", "전문가들은",
            "보고서에서", "조사 결과", "실험을 통해", "분석에 따르면",
            "예를 들어", "실제로", "구체적으로", "사실"
        ]
        
        sentences = cleaned_content.replace('!', '.').replace('?', '.').split('.')
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and any(pattern in sentence for pattern in evidence_patterns):
                evidence.append(sentence)
                if len(evidence) >= 3:
                    break
        
        # 품질 점수 계산 (KITECH 평가 기준)
        quality_score = 0.5
        
        # 길이 적절성 (50-300자 최적)
        if 50 <= len(cleaned_content) <= 300:
            quality_score += 0.1
        
        # 논리 구조 (접속사 사용)
        logical_connectors = ["따라서", "그러므로", "왜냐하면", "또한", "하지만", "그러나", "반면에"]
        if any(conn in cleaned_content for conn in logical_connectors):
            quality_score += 0.1
        
        # 구체성 (숫자, 고유명사 포함)
        import re
        if re.search(r'\d+', cleaned_content) or any(char.isupper() for char in cleaned_content):
            quality_score += 0.1
        
        # 감정적 어조 적절성
        emotional_words = ["놀랍게도", "확실히", "분명히", "당연히", "절대적으로"]
        if any(word in cleaned_content for word in emotional_words):
            quality_score += 0.05
        
        # 신뢰도 계산
        confidence = quality_score
        if evidence:
            confidence += 0.15
        if len(cleaned_content) > 100:
            confidence += 0.05
        
        return {
            'cleaned_content': cleaned_content,
            'evidence': evidence[:3],
            'confidence': min(confidence, 0.95),
            'quality_score': min(quality_score, 1.0)
        }
    
    def _generate_intelligent_fallback(self) -> Dict:
        """KITECH 방식: 역할별 지능형 폴백 응답"""
        fallback_templates = {
            AgentRole.SEARCHER: "🔍 **현재 관련 자료를 분석 중입니다.** 기존 연구들을 종합해보면, 이 주제에 대한 다양한 관점들이 존재합니다. 더 구체적인 데이터 수집이 필요한 상황입니다.",
            
            AgentRole.ANALYZER: "🧠 **논리적 분석을 진행하겠습니다.** 제시된 논증의 구조를 살펴보면, 전제와 결론 사이의 연결고리를 더 명확히 할 필요가 있어 보입니다.",
            
            AgentRole.WRITER: "✍️ **설득력 있는 관점을 제시하겠습니다.** 이 문제의 핵심은 다각도로 접근해야 한다는 점입니다. 실용적 측면에서 볼 때 중요한 고려사항들이 있습니다.",
            
            AgentRole.REVIEWER: "📋 **품질 검토 관점에서 말씀드리면,** 현재 논의에서 더 보완이 필요한 부분들이 있습니다. 논증의 완성도를 높이기 위한 추가 고려사항을 제안드립니다.",
            
            AgentRole.DEVIL: "😈 **잠깐, 이 부분은 문제가 있어 보입니다!** 🤨 제시된 주장에는 몇 가지 **중대한 허점**이 있습니다. 과연 이것이 최선의 접근방식일까요?",
            
            AgentRole.ANGEL: "😇 **긍정적인 관점에서 보겠습니다!** ✨ 이 접근방식에는 분명한 **장점들**이 있습니다. 특히 장기적 관점에서 매우 **희망적인** 결과를 기대할 수 있습니다! 💖",
            
            AgentRole.ORGANIZER: "🎯 **토론 진행자로서 말씀드리겠습니다.** 📋 현재까지의 논의를 종합해보면, 양측 모두 **의미 있는 관점**들을 제시하고 있습니다. 이제 다음 단계로 나아가겠습니다! 🎪"
        }
        
        fallback_content = fallback_templates.get(
            self.role, 
            "🤔 **신중한 검토가 필요한 시점입니다.** 더 심도 있는 분석을 통해 더 나은 답변을 제공하겠습니다."
        )
        
        return {
            'content': fallback_content,
            'evidence': ["시스템 복구 중 임시 응답"],
            'confidence': 0.6,
            'quality_score': 0.7
        }
    
    def evaluate_opponent_argument(self, argument: Argument) -> Dict[str, float]:
        """
        상대 논증 평가 - M-MAD의 다차원 평가 적용
        """
        dimensions = {
            'logical_coherence': 0.0,
            'evidence_quality': 0.0,
            'persuasiveness': 0.0,
            'relevance': 0.0,
            'originality': 0.0
        }
        
        # 역할별 특화된 평가
        if self.role == AgentRole.ANALYZER:
            # 분석가는 논리적 일관성에 중점
            dimensions['logical_coherence'] = self._evaluate_logic(argument)
        elif self.role == AgentRole.REVIEWER:
            # 검토자는 전반적인 품질 평가
            dimensions = self._comprehensive_evaluation(argument)
        
        return dimensions
    
    def _evaluate_logic(self, argument: Argument) -> float:
        """논리적 일관성 평가"""
        # 실제 구현 필요
        return 0.7
    
    def _comprehensive_evaluation(self, argument: Argument) -> Dict[str, float]:
        """종합적 평가"""
        # 실제 구현 필요
        return {
            'logical_coherence': 0.8,
            'evidence_quality': 0.7,
            'persuasiveness': 0.75,
            'relevance': 0.9,
            'originality': 0.6
        }

class MultiAgentDebater:
    """
    Society of Minds 접근법을 적용한 멀티에이전트 토론 시스템
    """
    
    def __init__(self, agents: List[DebateAgent]):
        self.agents = agents
        self.debate_history: List[Argument] = []
        
    def collaborative_argument_generation(
        self,
        topic: str,
        stance: DebateStance,
        round_number: int
    ) -> Argument:
        """
        여러 에이전트가 협력하여 하나의 강력한 논증 생성
        """
        # 각 역할별 에이전트가 초안 생성
        drafts = []
        for agent in self.agents:
            if agent.stance == stance:
                draft = agent.generate_argument(
                    topic, self.debate_history, round_number
                )
                drafts.append(draft)
        
        # 최종 논증 통합 및 개선
        final_argument = self._integrate_arguments(drafts)
        
        return final_argument
    
    def _integrate_arguments(self, drafts: List[Argument]) -> Argument:
        """
        여러 초안을 통합하여 최종 논증 생성
        Agent4Debate의 동적 조정 메커니즘 적용
        """
        # 각 초안의 장점 추출
        best_evidence = []
        best_points = []
        
        for draft in drafts:
            if draft.evidence:
                best_evidence.extend(draft.evidence)
            best_points.append(draft.content)
        
        # Writer 에이전트가 최종 통합
        writer_agent = next(
            (agent for agent in self.agents if agent.role == AgentRole.WRITER),
            self.agents[0]
        )
        
        integration_prompt = f"""
Integrate these argument drafts into a single, powerful argument:
{best_points}

Available evidence:
{best_evidence}

Create a cohesive, persuasive argument.
"""
        
        # 최종 논증 생성
        final_argument = writer_agent.generate_argument(
            "Integration", drafts, 0, integration_prompt
        )
        
        return final_argument