
"""
토론 제어기 - 토론 흐름 관리 및 조정
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import json
import logging
from datetime import datetime
import asyncio

from debate_agent import DebateAgent, Argument, DebateStance, AgentRole

class DebateFormat(Enum):
    """토론 형식"""
    ADVERSARIAL = "adversarial"  # MAD 스타일 대립 토론
    COLLABORATIVE = "collaborative"  # Society of Minds 협력 토론
    OXFORD = "oxford"  # Oxford 스타일 공식 토론
    ROUNDTABLE = "roundtable"  # 원탁 토론
    COMPETITIVE = "competitive"  # Agent4Debate 경쟁 토론
    CUSTOM = "custom"  # 커스텀 토론

@dataclass
class DebateConfig:
    """토론 설정"""
    topic: str
    format: DebateFormat
    max_rounds: int = 5
    time_limit_per_round: int = 180  # seconds
    enable_fact_checking: bool = True
    enable_audience_feedback: bool = False
    evaluation_dimensions: List[str] = None

class DebateController:
    """
    토론 진행을 관리하는 컨트롤러
    GitHub 저장소들의 베스트 프랙티스 통합
    """
    
    def __init__(
        self,
        config: DebateConfig,
        support_agents: List[DebateAgent],
        oppose_agents: List[DebateAgent],
        moderator_agent: Optional[DebateAgent] = None
    ):
        self.config = config
        self.support_agents = support_agents
        self.oppose_agents = oppose_agents
        self.moderator = moderator_agent
        
        self.current_round = 0
        self.debate_history: List[Argument] = []
        self.round_summaries: List[Dict] = []
        self.is_active = False
        
        self.logger = logging.getLogger("DebateController")
        
        # 평가 차원 설정 (M-MAD 스타일)
        self.evaluation_dimensions = config.evaluation_dimensions or [
            'logical_coherence',
            'evidence_quality',
            'persuasiveness',
            'relevance',
            'originality'
        ]
    
    def start_debate(self) -> Dict:
        """토론 시작"""
        self.is_active = True
        self.logger.info(f"Starting debate on topic: {self.config.topic}")
        
        # 초기 설정 및 브리핑
        initial_briefing = self._generate_initial_briefing()
        
        return {
            'status': 'started',
            'topic': self.config.topic,
            'format': self.config.format.value,
            'briefing': initial_briefing
        }
    
    async def conduct_round(self) -> Dict:
        """
        한 라운드 진행
        형식에 따라 다른 진행 방식 적용
        """
        if not self.is_active:
            return {'error': 'Debate not active'}
        
        self.current_round += 1
        self.logger.info(f"Starting round {self.current_round}")
        
        round_result = {
            'round': self.current_round,
            'arguments': [],
            'evaluations': {}
        }
        
        # 토론 형식별 진행
        if self.config.format == DebateFormat.ADVERSARIAL:
            round_result = await self._conduct_adversarial_round()
        elif self.config.format == DebateFormat.COLLABORATIVE:
            round_result = await self._conduct_collaborative_round()
        elif self.config.format == DebateFormat.COMPETITIVE:
            round_result = await self._conduct_competitive_round()
        else:
            round_result = await self._conduct_standard_round()
        
        # 라운드 요약 생성
        round_summary = self._generate_round_summary(round_result)
        self.round_summaries.append(round_summary)
        
        # 종료 조건 확인
        if self.current_round >= self.config.max_rounds:
            self.is_active = False
            round_result['debate_complete'] = True
            round_result['final_evaluation'] = self._generate_final_evaluation()
        
        return round_result
    
    async def _conduct_adversarial_round(self) -> Dict:
        """
        MAD 스타일 대립 토론 라운드
        악마와 천사가 번갈아가며 논증
        """
        round_arguments = []
        
        # Devil's advocate 먼저 도전
        devil_agents = [a for a in self.oppose_agents if a.role == AgentRole.DEVIL]
        if devil_agents:
            devil_arg = await devil_agents[0].generate_argument(
                self.config.topic,
                self.debate_history,
                self.current_round,
                "Challenge the current position aggressively"
            )
            round_arguments.append(devil_arg)
            self.debate_history.append(devil_arg)
        
        # Angel's response
        angel_agents = [a for a in self.support_agents if a.role == AgentRole.ANGEL]
        if angel_agents:
            angel_arg = await angel_agents[0].generate_argument(
                self.config.topic,
                self.debate_history,
                self.current_round,
                "Defend and strengthen the position"
            )
            round_arguments.append(angel_arg)
            self.debate_history.append(angel_arg)
        
        # Cross-evaluation
        evaluations = self._cross_evaluate_arguments(round_arguments)
        
        return {
            'round': self.current_round,
            'arguments': round_arguments,
            'evaluations': evaluations,
            'style': 'adversarial'
        }
    
    async def _conduct_collaborative_round(self) -> Dict:
        """
        Society of Minds 스타일 협력 토론 라운드
        여러 에이전트가 함께 더 나은 논증 구성
        """
        round_arguments = []
        
        # 각 진영에서 협력적으로 논증 생성
        for stance, agents in [
            (DebateStance.SUPPORT, self.support_agents),
            (DebateStance.OPPOSE, self.oppose_agents)
        ]:
            # 역할별로 초안 생성
            drafts = []
            for agent in agents:
                draft = await agent.generate_argument(
                    self.config.topic,
                    self.debate_history,
                    self.current_round
                )
                drafts.append(draft)
            
            # Writer가 통합
            writer = next((a for a in agents if a.role == AgentRole.WRITER), agents[0])
            integrated_arg = await self._integrate_collaborative_arguments(drafts, writer)
            
            round_arguments.append(integrated_arg)
            self.debate_history.append(integrated_arg)
        
        evaluations = self._cross_evaluate_arguments(round_arguments)
        
        return {
            'round': self.current_round,
            'arguments': round_arguments,
            'evaluations': evaluations,
            'style': 'collaborative'
        }
    
    async def _conduct_competitive_round(self) -> Dict:
        """
        Agent4Debate 스타일 경쟁 토론 라운드
        전문화된 역할이 순차적으로 기여
        """
        round_arguments = []
        
        # 각 진영의 체계적 논증 구성
        for stance, agents in [
            (DebateStance.SUPPORT, self.support_agents),
            (DebateStance.OPPOSE, self.oppose_agents)
        ]:
            # 1. Searcher가 증거 수집
            searcher = next((a for a in agents if a.role == AgentRole.SEARCHER), None)
            evidence = []
            if searcher:
                search_arg = await searcher.generate_argument(
                    self.config.topic,
                    self.debate_history,
                    self.current_round,
                    "Find supporting evidence"
                )
                evidence = search_arg.evidence or []
            
            # 2. Analyzer가 논리 분석
            analyzer = next((a for a in agents if a.role == AgentRole.ANALYZER), None)
            analysis = None
            if analyzer:
                analysis = await analyzer.generate_argument(
                    self.config.topic,
                    self.debate_history,
                    self.current_round,
                    f"Analyze arguments with evidence: {evidence}"
                )
            
            # 3. Writer가 논증 작성
            writer = next((a for a in agents if a.role == AgentRole.WRITER), None)
            if writer:
                main_arg = await writer.generate_argument(
                    self.config.topic,
                    self.debate_history + ([analysis] if analysis else []),
                    self.current_round,
                    "Compose persuasive argument with evidence and analysis"
                )
                
                # 4. Reviewer가 최종 검토
                reviewer = next((a for a in agents if a.role == AgentRole.REVIEWER), None)
                if reviewer:
                    final_arg = await reviewer.generate_argument(
                        self.config.topic,
                        [main_arg],
                        self.current_round,
                        "Review and enhance the argument"
                    )
                    round_arguments.append(final_arg)
                    self.debate_history.append(final_arg)
                else:
                    round_arguments.append(main_arg)
                    self.debate_history.append(main_arg)
        
        evaluations = self._cross_evaluate_arguments(round_arguments)
        
        return {
            'round': self.current_round,
            'arguments': round_arguments,
            'evaluations': evaluations,
            'style': 'competitive'
        }
    
    async def _conduct_standard_round(self) -> Dict:
        """표준 토론 라운드"""
        round_arguments = []
        
        # 번갈아가며 발언
        for agents in [self.support_agents, self.oppose_agents]:
            if agents:
                # 주 발언자 선택 (라운드별 순환)
                speaker_idx = (self.current_round - 1) % len(agents)
                speaker = agents[speaker_idx]
                
                arg = await speaker.generate_argument(
                    self.config.topic,
                    self.debate_history,
                    self.current_round
                )
                round_arguments.append(arg)
                self.debate_history.append(arg)
        
        evaluations = self._cross_evaluate_arguments(round_arguments)
        
        return {
            'round': self.current_round,
            'arguments': round_arguments,
            'evaluations': evaluations,
            'style': 'standard'
        }
    
    def _cross_evaluate_arguments(self, arguments: List[Argument]) -> Dict:
        """
        논증 상호 평가 - M-MAD의 다차원 평가 적용
        """
        evaluations = {}
        
        for arg in arguments:
            arg_evaluations = {
                'self_evaluation': {},
                'opponent_evaluations': [],
                'average_scores': {}
            }
            
            # 자기 평가
            evaluator = next(
                (a for a in self.support_agents + self.oppose_agents 
                 if a.name == arg.agent_name),
                None
            )
            if evaluator:
                arg_evaluations['self_evaluation'] = evaluator.evaluate_opponent_argument(arg)
            
            # 상대 평가
            opponents = (self.oppose_agents if arg.stance == DebateStance.SUPPORT 
                        else self.support_agents)
            
            for opponent in opponents:
                if opponent.role in [AgentRole.ANALYZER, AgentRole.REVIEWER]:
                    eval_scores = opponent.evaluate_opponent_argument(arg)
                    arg_evaluations['opponent_evaluations'].append({
                        'evaluator': opponent.name,
                        'scores': eval_scores
                    })
            
            # 평균 점수 계산
            if arg_evaluations['opponent_evaluations']:
                all_scores = [eval['scores'] for eval in arg_evaluations['opponent_evaluations']]
                for dim in self.evaluation_dimensions:
                    scores = [s.get(dim, 0) for s in all_scores]
                    arg_evaluations['average_scores'][dim] = sum(scores) / len(scores)
            
            evaluations[arg.agent_name] = arg_evaluations
        
        return evaluations
    
    async def _integrate_collaborative_arguments(
        self,
        drafts: List[Argument],
        writer: DebateAgent
    ) -> Argument:
        """협력적 논증 통합"""
        # 모든 초안의 핵심 포인트 추출
        key_points = []
        all_evidence = []
        
        for draft in drafts:
            key_points.append(f"[{draft.agent_name}]: {draft.content}")
            if draft.evidence:
                all_evidence.extend(draft.evidence)
        
        # Writer가 통합
        integration_context = "\n".join(key_points)
        integrated = await writer.generate_argument(
            self.config.topic,
            drafts,
            self.current_round,
            f"Integrate these perspectives:\n{integration_context}"
        )
        
        # 통합된 증거 추가
        integrated.evidence = list(set(all_evidence))  # 중복 제거
        
        return integrated
    
    def _generate_initial_briefing(self) -> str:
        """초기 브리핑 생성"""
        briefing = f"""
=== DEBATE BRIEFING ===
Topic: {self.config.topic}
Format: {self.config.format.value}
Rounds: {self.config.max_rounds}
Time per round: {self.config.time_limit_per_round}s

Supporting Team:
{self._format_team_info(self.support_agents)}

Opposing Team:
{self._format_team_info(self.oppose_agents)}

Evaluation Dimensions: {', '.join(self.evaluation_dimensions)}
=====================
"""
        return briefing
    
    def _format_team_info(self, agents: List[DebateAgent]) -> str:
        """팀 정보 포맷팅"""
        info = []
        for agent in agents:
            info.append(f"- {agent.name} ({agent.role.value})")
        return "\n".join(info)
    
    def _generate_round_summary(self, round_result: Dict) -> Dict:
        """라운드 요약 생성"""
        summary = {
            'round': round_result['round'],
            'timestamp': datetime.now().isoformat(),
            'argument_count': len(round_result['arguments']),
            'key_points': [],
            'evaluation_summary': {}
        }
        
        # 주요 논점 추출
        for arg in round_result['arguments']:
            summary['key_points'].append({
                'agent': arg.agent_name,
                'stance': arg.stance.value,
                'summary': arg.content[:200] + "..." if len(arg.content) > 200 else arg.content
            })
        
        # 평가 요약
        if round_result.get('evaluations'):
            for agent_name, eval_data in round_result['evaluations'].items():
                if eval_data.get('average_scores'):
                    summary['evaluation_summary'][agent_name] = eval_data['average_scores']
        
        return summary
    
    def _generate_final_evaluation(self) -> Dict:
        """
        최종 평가 생성
        M-MAD의 다차원 종합 평가 적용
        """
        final_eval = {
            'winner': None,
            'support_team_score': {},
            'oppose_team_score': {},
            'dimension_analysis': {},
            'summary': "",
            'key_insights': []
        }
        
        # 각 차원별 팀 점수 계산
        for dimension in self.evaluation_dimensions:
            support_scores = []
            oppose_scores = []
            
            for summary in self.round_summaries:
                for agent_name, scores in summary.get('evaluation_summary', {}).items():
                    score = scores.get(dimension, 0)
                    
                    # 에이전트가 어느 팀인지 확인
                    if any(a.name == agent_name for a in self.support_agents):
                        support_scores.append(score)
                    elif any(a.name == agent_name for a in self.oppose_agents):
                        oppose_scores.append(score)
            
            # 평균 계산
            support_avg = sum(support_scores) / len(support_scores) if support_scores else 0
            oppose_avg = sum(oppose_scores) / len(oppose_scores) if oppose_scores else 0
            
            final_eval['support_team_score'][dimension] = support_avg
            final_eval['oppose_team_score'][dimension] = oppose_avg
            final_eval['dimension_analysis'][dimension] = {
                'support': support_avg,
                'oppose': oppose_avg,
                'winner': 'support' if support_avg > oppose_avg else 'oppose'
            }
        
        # 전체 승자 결정
        support_wins = sum(
            1 for d in final_eval['dimension_analysis'].values() 
            if d['winner'] == 'support'
        )
        oppose_wins = len(self.evaluation_dimensions) - support_wins
        
        final_eval['winner'] = 'support' if support_wins > oppose_wins else 'oppose'
        
        # 요약 생성
        final_eval['summary'] = f"""
Debate concluded after {self.current_round} rounds.
Winner: {final_eval['winner'].capitalize()} team
Winning dimensions: {support_wins} vs {oppose_wins}

Strongest dimension for support: {self._get_strongest_dimension(final_eval['support_team_score'])}
Strongest dimension for oppose: {self._get_strongest_dimension(final_eval['oppose_team_score'])}
"""
        
        # 주요 인사이트 도출
        final_eval['key_insights'] = self._extract_key_insights()
        
        return final_eval
    
    def _get_strongest_dimension(self, scores: Dict[str, float]) -> str:
        """가장 높은 점수의 차원 찾기"""
        if not scores:
            return "N/A"
        return max(scores.items(), key=lambda x: x[1])[0]
    
    def _extract_key_insights(self) -> List[str]:
        """토론에서 주요 인사이트 추출"""
        insights = []
        
        # 라운드별 변화 분석
        if len(self.round_summaries) > 1:
            insights.append("Debate showed progression across rounds")
        
        # 가장 설득력 있었던 논증 찾기
        highest_confidence = max(
            (arg for arg in self.debate_history),
            key=lambda x: x.confidence_score,
            default=None
        )
        if highest_confidence:
            insights.append(
                f"Most confident argument by {highest_confidence.agent_name} "
                f"in round {highest_confidence.round_number}"
            )
        
        return insights
    
    def export_debate_transcript(self, format: str = "json") -> str:
        """토론 기록 내보내기"""
        transcript = {
            'metadata': {
                'topic': self.config.topic,
                'format': self.config.format.value,
                'total_rounds': self.current_round,
                'timestamp': datetime.now().isoformat()
            },
            'participants': {
                'support': [a.name for a in self.support_agents],
                'oppose': [a.name for a in self.oppose_agents]
            },
            'debate_history': [
                {
                    'round': arg.round_number,
                    'agent': arg.agent_name,
                    'stance': arg.stance.value,
                    'content': arg.content,
                    'evidence': arg.evidence,
                    'confidence': arg.confidence_score
                }
                for arg in self.debate_history
            ],
            'round_summaries': self.round_summaries,
            'final_evaluation': self._generate_final_evaluation() if not self.is_active else None
        }
        
        if format == "json":
            return json.dumps(transcript, indent=2, ensure_ascii=False)
        else:
            # 추가 형식 지원 가능
            return str(transcript)
