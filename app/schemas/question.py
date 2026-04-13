# Question Engine에서 사용하는 입력 및 출력 데이터 구조를 정의하는 스키마 파일
# 이 파일은 질문 생성, 추가 질문 생성, 사용자 답변 평가에 필요한 데이터 형식을 정의한다.

from typing import List, Optional
from pydantic import BaseModel, Field


class QuestionGenerationInput(BaseModel):
    """
    질문 생성 입력 데이터

    - recent_context: 최근 발화 문맥
    - current_topic: 현재 발표 주제
    - audience_type: interviewer / professor / investor
    - presentation_type: job_interview / contest / presentation
    - pressure_level: low / medium / high
    - previous_questions: 이전에 했던 질문들
    """
    recent_context: List[str] = Field(default_factory=list)
    current_topic: Optional[str] = None
    audience_type: str
    presentation_type: str
    pressure_level: str = "medium"
    previous_questions: List[str] = Field(default_factory=list)


class QuestionGenerationResult(BaseModel):
    """
    질문 생성 결과

    - question_text: 생성된 질문
    - question_difficulty: easy / medium / hard
    - question_type: clarification / logic_probe / detail_probe / challenge
    """
    question_text: str
    question_difficulty: str
    question_type: str


class AnswerEvaluationInput(BaseModel):
    """
    사용자 답변 평가 입력 데이터

    - question_text: 이전에 던진 질문
    - user_answer: 사용자 답변
    - current_topic: 현재 주제
    - recent_context: 최근 발표 맥락
    - pressure_level: 압박 강도
    """
    question_text: str
    user_answer: str
    current_topic: Optional[str] = None
    recent_context: List[str] = Field(default_factory=list)
    pressure_level: str = "medium"


class AnswerEvaluationResult(BaseModel):
    """
    사용자 답변 평가 결과

    - answer_score: 0~100 점수
    - follow_up_needed: 추가 질문 필요 여부
    - audience_reaction: confused / neutral / satisfied / impressed
    - evaluation_reason: 평가 이유
    - follow_up_question: 추가 질문이 필요할 경우 생성되는 질문
    """
    answer_score: float
    follow_up_needed: bool
    audience_reaction: str
    evaluation_reason: str
    follow_up_question: Optional[str] = None