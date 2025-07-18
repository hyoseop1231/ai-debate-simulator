"""
토론 평가 시스템 - M-MAD의 다차원 평가 프레임워크 구현
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import numpy as np
import re
from collections import Counter
import logging

from debate_agent import Argument, DebateStance

logger = logging.getLogger(__name__)

class EvaluationDimension(Enum):
    """평가 차원 - M-MAD 방식"""
    LOGICAL_COHERENCE = "logical_coherence"       # 논리적 일관성
    EVIDENCE_QUALITY = "evidence_quality"          # 증거 품질
    PERSUASIVENESS = "persuasiveness"             # 설득력
    RELEVANCE = "relevance"                       # 관련성
    ORIGINALITY = "originality"                   # 독창성
    CLARITY = "clarity"                           # 명확성
    FACTUAL_ACCURACY = "factual_accuracy"         # 사실 정확성
    EMOTIONAL_APPEAL = "emotional_appeal"         # 감정적 호소력

@dataclass
class DimensionScore:
    """차원별 점수"""
    dimension: EvaluationDimension
    score: float  # 0.0 ~ 1.0
    confidence: float  # 평가 신뢰도
    rationale: str  # 평가 이유

@dataclass
class ArgumentEvaluation:
    """논증 평가 결과"""
    argument: Argument
    dimension_scores: Dict[EvaluationDimension, DimensionScore]
    overall_score: float
    strengths: List[str]
    weaknesses: List[str]
    improvement_suggestions: List[str]

class DebateEvaluator:
    """
    종합 토론 평가 시스템
    M-MAD의 다차원 평가와 GitHub 저장소들의 평가 방식 통합
    """
    
    def __init__(self, evaluation_dimensions: List[EvaluationDimension] = None):
        """
        :param evaluation_dimensions: 평가할 차원들 (기본값: 모든 차원)
        """
        self.dimensions = evaluation_dimensions or list(EvaluationDimension)
        self.evaluation_cache = {}
        
        # 논리적 오류 패턴
        self.logical_fallacies = {
            'ad_hominem': r'(당신은|너는|그는|그녀는).*때문에.*틀렸',
            'strawman': r'(전혀 다른|관계없는).*주장',
            'false_dilemma': r'(오직|단지).*아니면',
            'circular_reasoning': r'왜냐하면.*그래서.*왜냐하면',
            'hasty_generalization': r'(모든|전부|항상|절대)',
        }
        
        # 강력한 논증 패턴
        self.strong_argument_patterns = {
            'evidence_based': r'(연구|데이터|통계|실험).*에 따르면',
            'logical_structure': r'(첫째|둘째|결론적으로|따라서)',
            'counterargument': r'(비록|하지만|그러나).*인정하지만',
            'specific_example': r'(예를 들어|구체적으로|실제로)',
        }
        
    def evaluate_argument(
        self,
        argument: Argument,
        context: List[Argument],
        topic: str
    ) -> ArgumentEvaluation:
        """
        단일 논증 평가
        
        :param argument: 평가할 논증
        :param context: 이전 논증들 (컨텍스트)
        :param topic: 토론 주제
        :return: 평가 결과
        """
        dimension_scores = {}
        
        # 각 차원별 평가
        for dimension in self.dimensions:
            score = self._evaluate_dimension(argument, dimension, context, topic)
            dimension_scores[dimension] = score
        
        # 전체 점수 계산 (가중 평균)
        weights = self._get_dimension_weights()
        overall_score = sum(
            dimension_scores[dim].score * weights.get(dim, 1.0) 
            for dim in self.dimensions
        ) / sum(weights.values())
        
        # 강점과 약점 분석
        strengths, weaknesses = self._analyze_strengths_weaknesses(dimension_scores)
        
        # 개선 제안
        suggestions = self._generate_improvement_suggestions(
            argument, dimension_scores, weaknesses
        )
        
        return ArgumentEvaluation(
            argument=argument,
            dimension_scores=dimension_scores,
            overall_score=overall_score,
            strengths=strengths,
            weaknesses=weaknesses,
            improvement_suggestions=suggestions
        )
    
    def _evaluate_dimension(
        self,
        argument: Argument,
        dimension: EvaluationDimension,
        context: List[Argument],
        topic: str
    ) -> DimensionScore:
        """차원별 평가 수행"""
        
        evaluators = {
            EvaluationDimension.LOGICAL_COHERENCE: self._evaluate_logical_coherence,
            EvaluationDimension.EVIDENCE_QUALITY: self._evaluate_evidence_quality,
            EvaluationDimension.PERSUASIVENESS: self._evaluate_persuasiveness,
            EvaluationDimension.RELEVANCE: self._evaluate_relevance,
            EvaluationDimension.ORIGINALITY: self._evaluate_originality,
            EvaluationDimension.CLARITY: self._evaluate_clarity,
            EvaluationDimension.FACTUAL_ACCURACY: self._evaluate_factual_accuracy,
            EvaluationDimension.EMOTIONAL_APPEAL: self._evaluate_emotional_appeal,
        }
        
        evaluator = evaluators.get(dimension)
        if evaluator:
            return evaluator(argument, context, topic)
        else:
            return DimensionScore(dimension, 0.5, 0.5, "평가 방법 미구현")
    
    def _evaluate_logical_coherence(
        self,
        argument: Argument,
        context: List[Argument],
        topic: str
    ) -> DimensionScore:
        """논리적 일관성 평가"""
        score = 0.8  # 기본 점수
        confidence = 0.7
        issues = []
        
        # 논리적 오류 검사
        for fallacy, pattern in self.logical_fallacies.items():
            if re.search(pattern, argument.content, re.IGNORECASE):
                score -= 0.2
                issues.append(f"논리적 오류 감지: {fallacy}")
        
        # 논리적 구조 검사
        structure_score = 0
        for pattern_name, pattern in self.strong_argument_patterns.items():
            if re.search(pattern, argument.content, re.IGNORECASE):
                structure_score += 0.1
        
        score = max(0, min(1, score + structure_score))
        
        # 일관성 검사 (이전 발언과의 모순 검사)
        agent_history = [a for a in context if a.agent_name == argument.agent_name]
        if agent_history:
            # 간단한 모순 검사 (실제로는 더 정교한 NLP 필요)
            contradiction_score = self._check_contradiction(argument, agent_history)
            score *= contradiction_score
        
        rationale = f"논리 구조 점수: {structure_score:.2f}, 문제: {issues if issues else '없음'}"
        
        return DimensionScore(
            EvaluationDimension.LOGICAL_COHERENCE,
            score,
            confidence,
            rationale
        )
    
    def _evaluate_evidence_quality(
        self,
        argument: Argument,
        context: List[Argument],
        topic: str
    ) -> DimensionScore:
        """증거 품질 평가"""
        score = 0.3  # 기본 점수 (증거 없음)
        confidence = 0.8
        
        if argument.evidence:
            # 증거 개수에 따른 점수
            evidence_count = len(argument.evidence)
            score = min(0.6 + (evidence_count * 0.1), 0.9)
            
            # 증거 품질 검사 (키워드 기반)
            quality_keywords = ['연구', '논문', '통계', '데이터', '전문가', '기관']
            quality_score = 0
            for evidence in argument.evidence:
                for keyword in quality_keywords:
                    if keyword in evidence:
                        quality_score += 0.05
            
            score = min(score + quality_score, 1.0)
            rationale = f"증거 {evidence_count}개 제시, 품질 점수: {quality_score:.2f}"
        else:
            # 본문에서 증거 언급 검사
            if re.search(r'(연구|데이터|통계|실험).*에 따르면', argument.content):
                score = 0.5
                rationale = "본문에 증거 언급 있으나 구체적 출처 없음"
            else:
                rationale = "증거 없음"
        
        return DimensionScore(
            EvaluationDimension.EVIDENCE_QUALITY,
            score,
            confidence,
            rationale
        )
    
    def _evaluate_persuasiveness(
        self,
        argument: Argument,
        context: List[Argument],
        topic: str
    ) -> DimensionScore:
        """설득력 평가"""
        score = 0.6  # 기본 점수
        confidence = 0.6
        
        # 설득력 요소 검사
        persuasive_elements = {
            'emotional_appeal': r'(우리|함께|모두|희망|미래|가치)',
            'call_to_action': r'(해야|필요|중요|시급|반드시)',
            'rhetorical_question': r'.*\?',
            'strong_conclusion': r'(따라서|결론적으로|명백히|분명히)',
        }
        
        element_scores = []
        for element, pattern in persuasive_elements.items():
            if re.search(pattern, argument.content):
                element_scores.append(0.15)
        
        score = min(score + sum(element_scores), 1.0)
        
        # 논증 길이와 구체성
        word_count = len(argument.content.split())
        if 50 < word_count < 200:  # 적절한 길이
            score = min(score + 0.1, 1.0)
        
        rationale = f"설득 요소 {len(element_scores)}개, 단어 수: {word_count}"
        
        return DimensionScore(
            EvaluationDimension.PERSUASIVENESS,
            score,
            confidence,
            rationale
        )
    
    def _evaluate_relevance(
        self,
        argument: Argument,
        context: List[Argument],
        topic: str
    ) -> DimensionScore:
        """관련성 평가"""
        score = 0.5
        confidence = 0.7
        
        # 주제 키워드 추출
        topic_keywords = set(topic.lower().split())
        topic_keywords.discard('은')
        topic_keywords.discard('는')
        topic_keywords.discard('이')
        topic_keywords.discard('가')
        
        # 논증에서 주제 키워드 출현 빈도
        argument_words = argument.content.lower().split()
        keyword_matches = sum(1 for word in argument_words if word in topic_keywords)
        
        # 관련성 점수 계산
        relevance_ratio = keyword_matches / max(len(argument_words), 1)
        score = min(0.3 + (relevance_ratio * 10), 1.0)
        
        # 직전 논증에 대한 응답인지 확인
        if context and len(context) > 0:
            last_argument = context[-1]
            if self._is_direct_response(argument, last_argument):
                score = min(score + 0.2, 1.0)
                rationale = f"주제 키워드 매칭: {keyword_matches}개, 직접 응답"
            else:
                rationale = f"주제 키워드 매칭: {keyword_matches}개"
        else:
            rationale = f"주제 키워드 매칭: {keyword_matches}개"
        
        return DimensionScore(
            EvaluationDimension.RELEVANCE,
            score,
            confidence,
            rationale
        )
    
    def _evaluate_originality(
        self,
        argument: Argument,
        context: List[Argument],
        topic: str
    ) -> DimensionScore:
        """독창성 평가"""
        score = 0.7  # 기본 점수
        confidence = 0.5
        
        if not context:
            return DimensionScore(
                EvaluationDimension.ORIGINALITY,
                score,
                confidence,
                "첫 번째 논증"
            )
        
        # 이전 논증들과의 유사도 검사
        similarities = []
        for prev_arg in context:
            similarity = self._calculate_similarity(argument.content, prev_arg.content)
            similarities.append(similarity)
        
        # 가장 유사한 논증과의 유사도
        max_similarity = max(similarities) if similarities else 0
        
        # 독창성 점수 (유사도가 낮을수록 높은 점수)
        score = 1.0 - (max_similarity * 0.7)
        
        # 새로운 관점이나 접근법 제시 보너스
        new_perspective_keywords = ['새로운', '다른', '혁신적', '독특한', '참신한']
        for keyword in new_perspective_keywords:
            if keyword in argument.content:
                score = min(score + 0.1, 1.0)
                break
        
        rationale = f"최대 유사도: {max_similarity:.2f}, 새로운 관점: {'있음' if any(k in argument.content for k in new_perspective_keywords) else '없음'}"
        
        return DimensionScore(
            EvaluationDimension.ORIGINALITY,
            score,
            confidence,
            rationale
        )
    
    def _evaluate_clarity(
        self,
        argument: Argument,
        context: List[Argument],
        topic: str
    ) -> DimensionScore:
        """명확성 평가"""
        score = 0.7
        confidence = 0.8
        
        # 문장 길이 분석
        sentences = argument.content.split('.')
        avg_sentence_length = np.mean([len(s.split()) for s in sentences if s.strip()])
        
        # 적절한 문장 길이 (10-25 단어)
        if 10 <= avg_sentence_length <= 25:
            score += 0.2
        elif avg_sentence_length > 40:
            score -= 0.2
        
        # 전문 용어와 일반 용어의 균형
        technical_terms = len(re.findall(r'\b[A-Z][a-zA-Z]{2,}\b', argument.content))
        total_words = len(argument.content.split())
        technical_ratio = technical_terms / max(total_words, 1)
        
        if technical_ratio < 0.2:  # 적절한 수준
            score = min(score + 0.1, 1.0)
        
        # 구조화 확인 (번호, 불릿 포인트 등)
        if re.search(r'(첫째|둘째|셋째|\d+\.|\-\s)', argument.content):
            score = min(score + 0.1, 1.0)
        
        score = max(0, min(score, 1.0))
        rationale = f"평균 문장 길이: {avg_sentence_length:.1f} 단어, 전문용어 비율: {technical_ratio:.2f}"
        
        return DimensionScore(
            EvaluationDimension.CLARITY,
            score,
            confidence,
            rationale
        )
    
    def _evaluate_factual_accuracy(
        self,
        argument: Argument,
        context: List[Argument],
        topic: str
    ) -> DimensionScore:
        """사실 정확성 평가 (간단한 휴리스틱)"""
        score = 0.7  # 중립 기본 점수
        confidence = 0.4  # 낮은 신뢰도 (실제 팩트체킹 없이)
        
        # 확실성 표현 검사
        certainty_words = ['확실히', '분명히', '절대적으로', '100%', '모든']
        uncertainty_words = ['아마도', '추측하건대', '~인 것 같다', '가능성이']
        
        certainty_count = sum(1 for word in certainty_words if word in argument.content)
        uncertainty_count = sum(1 for word in uncertainty_words if word in argument.content)
        
        # 과도한 확실성은 감점
        if certainty_count > 3:
            score -= 0.2
            rationale = "과도한 확실성 표현"
        elif uncertainty_count > 0:
            score += 0.1
            rationale = "적절한 불확실성 인정"
        else:
            rationale = "중립적 표현"
        
        # 수치나 통계 언급 시 가산점
        if re.search(r'\d+%|\d+명|\d+년', argument.content):
            score = min(score + 0.1, 1.0)
            rationale += ", 구체적 수치 제시"
        
        return DimensionScore(
            EvaluationDimension.FACTUAL_ACCURACY,
            max(0, min(score, 1.0)),
            confidence,
            rationale
        )
    
    def _evaluate_emotional_appeal(
        self,
        argument: Argument,
        context: List[Argument],
        topic: str
    ) -> DimensionScore:
        """감정적 호소력 평가"""
        score = 0.5
        confidence = 0.6
        
        # 감정적 언어 패턴
        emotional_patterns = {
            'positive': ['희망', '기쁨', '사랑', '열정', '꿈', '미래', '함께'],
            'negative': ['두려움', '위험', '걱정', '위기', '실패', '고통'],
            'empathy': ['우리', '함께', '모두', '공감', '이해'],
        }
        
        emotional_scores = {}
        for emotion_type, keywords in emotional_patterns.items():
            count = sum(1 for keyword in keywords if keyword in argument.content)
            emotional_scores[emotion_type] = count
        
        # 감정적 언어 사용량에 따른 점수
        total_emotional_words = sum(emotional_scores.values())
        if total_emotional_words > 0:
            score = min(0.5 + (total_emotional_words * 0.1), 0.9)
            
            # 균형잡힌 감정 사용 보너스
            if emotional_scores['positive'] > 0 and emotional_scores['empathy'] > 0:
                score = min(score + 0.1, 1.0)
        
        rationale = f"감정적 언어: {total_emotional_words}개 (긍정: {emotional_scores['positive']}, 공감: {emotional_scores['empathy']})"
        
        return DimensionScore(
            EvaluationDimension.EMOTIONAL_APPEAL,
            score,
            confidence,
            rationale
        )
    
    def _check_contradiction(self, current: Argument, history: List[Argument]) -> float:
        """모순 검사 (간단한 버전)"""
        # 실제로는 더 정교한 NLP 기법 필요
        # 여기서는 단순히 반대 표현 검사
        
        contradiction_score = 1.0
        
        for prev in history:
            # 정반대 입장 표현 검사
            if ('아니다' in current.content and '이다' in prev.content) or \
               ('이다' in current.content and '아니다' in prev.content):
                contradiction_score *= 0.8
        
        return contradiction_score
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """두 텍스트의 유사도 계산 (간단한 Jaccard 유사도)"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        if not union:
            return 0.0
        
        return len(intersection) / len(union)
    
    def _is_direct_response(self, current: Argument, previous: Argument) -> bool:
        """직접적인 응답인지 확인"""
        # 이전 논증의 핵심 키워드가 현재 논증에 포함되는지 확인
        prev_keywords = set(previous.content.lower().split()[:10])  # 처음 10단어
        curr_words = set(current.content.lower().split())
        
        overlap = len(prev_keywords.intersection(curr_words))
        return overlap >= 3  # 3개 이상 겹치면 직접 응답으로 간주
    
    def _get_dimension_weights(self) -> Dict[EvaluationDimension, float]:
        """차원별 가중치 반환"""
        return {
            EvaluationDimension.LOGICAL_COHERENCE: 1.5,
            EvaluationDimension.EVIDENCE_QUALITY: 1.3,
            EvaluationDimension.PERSUASIVENESS: 1.2,
            EvaluationDimension.RELEVANCE: 1.4,
            EvaluationDimension.ORIGINALITY: 1.0,
            EvaluationDimension.CLARITY: 1.1,
            EvaluationDimension.FACTUAL_ACCURACY: 1.3,
            EvaluationDimension.EMOTIONAL_APPEAL: 0.8,
        }
    
    def _analyze_strengths_weaknesses(
        self,
        dimension_scores: Dict[EvaluationDimension, DimensionScore]
    ) -> Tuple[List[str], List[str]]:
        """강점과 약점 분석"""
        strengths = []
        weaknesses = []
        
        for dim, score_obj in dimension_scores.items():
            if score_obj.score >= 0.8:
                strengths.append(f"{dim.value}: {score_obj.rationale}")
            elif score_obj.score <= 0.4:
                weaknesses.append(f"{dim.value}: {score_obj.rationale}")
        
        return strengths, weaknesses
    
    def _generate_improvement_suggestions(
        self,
        argument: Argument,
        dimension_scores: Dict[EvaluationDimension, DimensionScore],
        weaknesses: List[str]
    ) -> List[str]:
        """개선 제안 생성"""
        suggestions = []
        
        # 낮은 점수 차원에 대한 제안
        for dim, score_obj in dimension_scores.items():
            if score_obj.score < 0.5:
                if dim == EvaluationDimension.EVIDENCE_QUALITY:
                    suggestions.append("구체적인 출처와 함께 더 많은 증거를 제시하세요.")
                elif dim == EvaluationDimension.LOGICAL_COHERENCE:
                    suggestions.append("논리적 구조를 명확히 하고 전제와 결론을 분명히 연결하세요.")
                elif dim == EvaluationDimension.CLARITY:
                    suggestions.append("문장을 더 간결하게 만들고 전문용어 사용을 줄이세요.")
                elif dim == EvaluationDimension.RELEVANCE:
                    suggestions.append("주제와 더 직접적으로 연관된 논점에 집중하세요.")
                elif dim == EvaluationDimension.ORIGINALITY:
                    suggestions.append("기존 논증과 차별화된 새로운 관점을 제시하세요.")
        
        return suggestions

class CompetitiveDebateJudge:
    """
    경쟁 토론 심사 시스템
    Agent4Debate 스타일의 승부 판정
    """
    
    def __init__(self, evaluator: DebateEvaluator):
        self.evaluator = evaluator
        
    def judge_debate(
        self,
        support_arguments: List[Argument],
        oppose_arguments: List[Argument],
        topic: str
    ) -> Dict:
        """
        토론 승부 판정
        
        :return: 판정 결과 (승자, 점수, 상세 분석)
        """
        # 각 팀의 논증 평가
        support_evaluations = []
        oppose_evaluations = []
        
        all_arguments = support_arguments + oppose_arguments
        all_arguments.sort(key=lambda x: x.round_number)
        
        for arg in support_arguments:
            eval_result = self.evaluator.evaluate_argument(arg, all_arguments, topic)
            support_evaluations.append(eval_result)
        
        for arg in oppose_arguments:
            eval_result = self.evaluator.evaluate_argument(arg, all_arguments, topic)
            oppose_evaluations.append(eval_result)
        
        # 팀별 점수 집계
        support_scores = self._aggregate_team_scores(support_evaluations)
        oppose_scores = self._aggregate_team_scores(oppose_evaluations)
        
        # 승자 결정
        winner = self._determine_winner(support_scores, oppose_scores)
        
        # 상세 분석
        analysis = self._generate_detailed_analysis(
            support_evaluations, oppose_evaluations, support_scores, oppose_scores
        )
        
        return {
            'winner': winner,
            'support_scores': support_scores,
            'oppose_scores': oppose_scores,
            'detailed_analysis': analysis,
            'support_evaluations': support_evaluations,
            'oppose_evaluations': oppose_evaluations,
        }
    
    def _aggregate_team_scores(
        self,
        evaluations: List[ArgumentEvaluation]
    ) -> Dict[str, float]:
        """팀 점수 집계"""
        if not evaluations:
            return {dim.value: 0.0 for dim in EvaluationDimension}
        
        dimension_scores = {dim: [] for dim in EvaluationDimension}
        
        for eval_result in evaluations:
            for dim, score_obj in eval_result.dimension_scores.items():
                dimension_scores[dim].append(score_obj.score)
        
        # 평균 계산
        aggregated = {}
        for dim, scores in dimension_scores.items():
            aggregated[dim.value] = np.mean(scores) if scores else 0.0
        
        # 전체 평균
        aggregated['overall'] = np.mean([eval.overall_score for eval in evaluations])
        
        return aggregated
    
    def _determine_winner(
        self,
        support_scores: Dict[str, float],
        oppose_scores: Dict[str, float]
    ) -> str:
        """승자 결정"""
        # 전체 점수 비교
        if support_scores['overall'] > oppose_scores['overall']:
            return 'support'
        elif oppose_scores['overall'] > support_scores['overall']:
            return 'oppose'
        else:
            # 동점일 경우 더 많은 차원에서 우위를 점한 팀
            support_wins = sum(
                1 for dim in EvaluationDimension 
                if support_scores.get(dim.value, 0) > oppose_scores.get(dim.value, 0)
            )
            oppose_wins = sum(
                1 for dim in EvaluationDimension 
                if oppose_scores.get(dim.value, 0) > support_scores.get(dim.value, 0)
            )
            
            if support_wins > oppose_wins:
                return 'support'
            elif oppose_wins > support_wins:
                return 'oppose'
            else:
                return 'draw'
    
    def _generate_detailed_analysis(
        self,
        support_evaluations: List[ArgumentEvaluation],
        oppose_evaluations: List[ArgumentEvaluation],
        support_scores: Dict[str, float],
        oppose_scores: Dict[str, float]
    ) -> Dict:
        """상세 분석 생성"""
        analysis = {
            'key_moments': [],
            'turning_points': [],
            'best_arguments': {
                'support': None,
                'oppose': None
            },
            'improvement_areas': {
                'support': [],
                'oppose': []
            }
        }
        
        # 최고 논증 찾기
        if support_evaluations:
            best_support = max(support_evaluations, key=lambda x: x.overall_score)
            analysis['best_arguments']['support'] = {
                'agent': best_support.argument.agent_name,
                'round': best_support.argument.round_number,
                'score': best_support.overall_score,
                'content_preview': best_support.argument.content[:100] + '...'
            }
        
        if oppose_evaluations:
            best_oppose = max(oppose_evaluations, key=lambda x: x.overall_score)
            analysis['best_arguments']['oppose'] = {
                'agent': best_oppose.argument.agent_name,
                'round': best_oppose.argument.round_number,
                'score': best_oppose.overall_score,
                'content_preview': best_oppose.argument.content[:100] + '...'
            }
        
        # 개선 필요 영역
        for dim in EvaluationDimension:
            if support_scores.get(dim.value, 0) < 0.5:
                analysis['improvement_areas']['support'].append(dim.value)
            if oppose_scores.get(dim.value, 0) < 0.5:
                analysis['improvement_areas']['oppose'].append(dim.value)
        
        return analysis