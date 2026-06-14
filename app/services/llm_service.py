# 발표 발화 내용을 심층적으로 분석하는 LLM 서비스
# 이 서비스는 매 발화마다 호출하지 않고, 특정 조건(10초 주기 / 주제 전환 / 인터럽트 직전)에서만 선택적으로 호출된다.

from app.schemas.analysis import AnalysisInput, LLMAnalysisResult, NLPAnalysisResult


class LLMService:
    """
    심층 LLM 분석 서비스

    현재 단계에서는 외부 LLM API 대신 mock 분석 결과를 반환한다.
    추후 OpenAI / Gemini API 연동 시 이 파일 내부 구현만 교체하면 된다.
    """

    def analyze(
        self,
        data: AnalysisInput,
        nlp_result: NLPAnalysisResult
    ) -> LLMAnalysisResult:
        """
        심층 분석 수행

        현재는 mock 규칙 기반으로 동작:
        - NLP 점수가 낮으면 논리 흐름 낮게
        - topic_shift_detected면 drift_score 높게
        - 키워드가 적으면 missing_points 추가
        """
        logic_flow_score = self._estimate_logic_flow_score(nlp_result)
        drift_score = self._estimate_drift_score(nlp_result)
        missing_points = self._estimate_missing_points(nlp_result)
        recommended_interrupt_type = self._recommend_interrupt_type(
            logic_flow_score=logic_flow_score,
            drift_score=drift_score,
            is_interrupt_imminent=data.is_interrupt_imminent
        )
        reasoning = self._build_reasoning(
            logic_flow_score=logic_flow_score,
            drift_score=drift_score,
            missing_points=missing_points,
            interrupt_type=recommended_interrupt_type
        )

        return LLMAnalysisResult(
            logic_flow_score=round(logic_flow_score, 3),
            drift_score=round(drift_score, 3),
            missing_points=missing_points,
            recommended_interrupt_type=recommended_interrupt_type,
            reasoning=reasoning
        )

    def _estimate_logic_flow_score(self, nlp_result: NLPAnalysisResult) -> float:
        """
        논리 흐름 점수를 추정
        """
        base = nlp_result.logic_structure_score

        if len(nlp_result.discourse_markers) >= 2:
            base += 0.2

        if nlp_result.topic_match_score >= 0.5:
            base += 0.2

        return min(base, 1.0)

    def _estimate_drift_score(self, nlp_result: NLPAnalysisResult) -> float:
        """
        주제 이탈 점수를 추정
        0에 가까울수록 안정적, 1에 가까울수록 많이 벗어남
        """
        drift = 1.0 - nlp_result.topic_match_score

        if nlp_result.topic_shift_detected:
            drift += 0.2

        return min(drift, 1.0)

    def _estimate_missing_points(self, nlp_result: NLPAnalysisResult) -> list[str]:
        """
        설명이 부족한 포인트를 추정
        """
        missing_points = []

        if not nlp_result.keywords:
            missing_points.append("핵심 키워드 설명 부족")

        if not nlp_result.discourse_markers:
            missing_points.append("논리 연결 표현 부족")

        if nlp_result.topic_match_score < 0.3:
            missing_points.append("예상 주제와의 연결 부족")

        return missing_points

    def _recommend_interrupt_type(
        self,
        logic_flow_score: float,
        drift_score: float,
        is_interrupt_imminent: bool
    ) -> str | None:
        """
        인터럽트 유형 추천
        """
        if not is_interrupt_imminent and drift_score < 0.65:
            return None

        if drift_score >= 0.7:
            return "topic_clarification"

        if logic_flow_score < 0.4:
            return "logic_probe"

        return "detail_probe"

    def _build_reasoning(
        self,
        logic_flow_score: float,
        drift_score: float,
        missing_points: list[str],
        interrupt_type: str | None
    ) -> str:
        """
        분석 이유를 간단한 자연어로 설명
        """
        reasons = [
            f"논리 흐름 점수는 {logic_flow_score:.2f}입니다.",
            f"주제 이탈 점수는 {drift_score:.2f}입니다.",
        ]

        if missing_points:
            reasons.append(f"부족한 포인트: {', '.join(missing_points)}")

        if interrupt_type:
            reasons.append(f"추천 인터럽트 유형: {interrupt_type}")

        return " ".join(reasons)