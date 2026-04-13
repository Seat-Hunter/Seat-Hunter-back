# NLP / LLM 분석 엔진에서 사용하는 입력 및 출력 데이터 구조를 정의하는 스키마 파일

from typing import List, Optional
from pydantic import BaseModel, Field


class AnalysisInput(BaseModel):
    """
    발화 분석 입력 데이터

    - text: 이번에 새로 들어온 final transcript
    - recent_context: 최근 발화 문맥
    - expected_topics: 발표 스크립트/슬라이드 기반 예상 주제 키워드
    - current_time_ms: 현재 발화 시점(ms)
    - is_interrupt_imminent: 인터럽트 직전 여부
    """
    text: str
    recent_context: List[str] = Field(default_factory=list)
    expected_topics: List[str] = Field(default_factory=list)
    current_time_ms: int
    is_interrupt_imminent: bool = False


class NLPAnalysisResult(BaseModel):
    """
    경량 NLP 분석 결과

    - keywords: 핵심 키워드
    - discourse_markers: 논리 전개 연결어
    - topic_match_score: 예상 주제와의 일치도
    - topic_shift_detected: 주제 이탈 징후
    - logic_structure_score: 문장 구조상 논리 전개 정도
    - notes: 간단한 룰 기반 해석 메시지
    """
    keywords: List[str]
    discourse_markers: List[str]
    topic_match_score: float
    topic_shift_detected: bool
    logic_structure_score: float
    notes: List[str]


class LLMAnalysisResult(BaseModel):
    """
    심층 LLM 분석 결과

    - logic_flow_score: 전체 논리 흐름 점수
    - drift_score: 주제 이탈 정도
    - missing_points: 빠진 설명 포인트
    - recommended_interrupt_type: 추천 인터럽트 유형
    - reasoning: 왜 그렇게 판단했는지 요약
    """
    logic_flow_score: float
    drift_score: float
    missing_points: List[str]
    recommended_interrupt_type: Optional[str] = None
    reasoning: str


class CombinedAnalysisResult(BaseModel):
    """
    NLP + LLM 통합 결과

    - nlp: 경량 NLP 결과
    - llm: LLM 결과 (조건부 호출이므로 없을 수 있음)
    - llm_called: 이번 턴에 LLM이 실제 호출되었는지 여부
    """
    nlp: NLPAnalysisResult
    llm: Optional[LLMAnalysisResult] = None
    llm_called: bool