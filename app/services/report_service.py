# 세션 종료 후 전체 로그를 종합하여 최종 리포트를 생성하는 Report Generator 서비스
# 이 서비스는 요약 통계, 강점/약점/개선 포인트, overall score, recovery score,
# 누적 패턴 업데이트, 다음 커리큘럼 추천까지 수행한다.

from statistics import mean

from app.schemas.report import (
    ReportGenerationInput,
    ReportGenerationResult,
    ReportSummary,
    UserPatternOutput,
)


class ReportService:
    """
    Report Generator 서비스

    주요 기능
    - 세션 요약 통계 계산
    - Recovery Score 계산
    - Overall Score 계산
    - 강점 / 약점 / 개선 포인트 도출
    - 누적 패턴 갱신
    - 다음 추천 커리큘럼 생성
    """

    def generate_report(self, data: ReportGenerationInput) -> ReportGenerationResult:
        """
        전체 세션 데이터를 바탕으로 종합 리포트를 생성한다.
        """
        summary = self._build_summary(data)
        recovery_score = self._calculate_recovery_score(data)
        strengths = self._extract_strengths(data, summary, recovery_score)
        weaknesses = self._extract_weaknesses(data, summary, recovery_score)
        improvements = self._build_improvements(weaknesses)
        overall_score = self._calculate_overall_score(
            summary=summary,
            recovery_score=recovery_score,
            weaknesses=weaknesses
        )
        updated_pattern = self._update_user_pattern(data, weaknesses)
        curriculum_next = self._recommend_curriculum(
            updated_pattern=updated_pattern,
            weaknesses=weaknesses,
            recovery_score=recovery_score
        )

        return ReportGenerationResult(
            summary=summary,
            strengths=strengths,
            weaknesses=weaknesses,
            improvements=improvements,
            overall_score=round(overall_score, 2),
            recovery_score=round(recovery_score, 2),
            curriculum_next=curriculum_next,
            updated_pattern=updated_pattern
        )

    def _build_summary(self, data: ReportGenerationInput) -> ReportSummary:
        """
        세션 전체 요약 통계를 계산한다.
        """
        if not data.speech_metrics:
            avg_wpm = 0.0
            max_wpm = 0.0
            filler_count = 0
            silence_count = 0
        else:
            avg_wpm = mean(snapshot.average_wpm for snapshot in data.speech_metrics)
            max_wpm = max(snapshot.recent_wpm for snapshot in data.speech_metrics)
            filler_count = max(snapshot.filler_count for snapshot in data.speech_metrics)
            silence_count = sum(
                1 for snapshot in data.speech_metrics
                if snapshot.silence_duration >= 1000
            )

        if data.answer_evaluation_log:
            avg_answer_score = mean(item.answer_score for item in data.answer_evaluation_log)
        else:
            avg_answer_score = 0.0

        return ReportSummary(
            avg_wpm=round(avg_wpm, 2),
            max_wpm=round(max_wpm, 2),
            filler_count=filler_count,
            silence_count=silence_count,
            interrupt_count=len(data.interrupt_log),
            avg_answer_score=round(avg_answer_score, 2)
        )

    def _calculate_recovery_score(self, data: ReportGenerationInput) -> float:
        """
        Recovery Score 계산

        가중치 예시
        - WPM 회복 속도: 40%
        - filler 감소율: 30%
        - silence 감소 여부: 30%
        """
        recovery = data.recovery_metrics

        score = (
            recovery.wpm_recovery_speed_score * 0.4 +
            recovery.filler_reduction_score * 0.3 +
            recovery.silence_reduction_score * 0.3
        )

        return max(0.0, min(score, 100.0))

    def _extract_strengths(
        self,
        data: ReportGenerationInput,
        summary: ReportSummary,
        recovery_score: float
    ) -> list[str]:
        """
        세션 강점 도출
        """
        strengths = []

        if 110 <= summary.avg_wpm <= 160:
            strengths.append("전체 말속도가 비교적 안정적입니다.")

        if summary.filler_count <= 3:
            strengths.append("필러 사용이 적어 전달력이 좋습니다.")

        if summary.avg_answer_score >= 75:
            strengths.append("질문에 대한 답변 대응력이 좋습니다.")

        if recovery_score >= 75:
            strengths.append("인터럽트 이후 회복 속도가 빠릅니다.")

        if not strengths:
            strengths.append("전반적으로 발표를 끝까지 유지한 점이 좋습니다.")

        return strengths

    def _extract_weaknesses(
        self,
        data: ReportGenerationInput,
        summary: ReportSummary,
        recovery_score: float
    ) -> list[str]:
        """
        세션 약점 도출
        """
        weaknesses = []

        if summary.avg_wpm < 100:
            weaknesses.append("전체 말속도가 다소 느립니다.")
        elif summary.avg_wpm > 170:
            weaknesses.append("전체 말속도가 다소 빠릅니다.")

        if summary.filler_count >= 5:
            weaknesses.append("필러 사용이 많아 답변의 매끄러움이 떨어집니다.")

        if summary.silence_count >= 3:
            weaknesses.append("침묵 구간이 자주 발생합니다.")

        if summary.avg_answer_score < 60 and data.answer_evaluation_log:
            weaknesses.append("질문에 대한 답변 구체성이 부족합니다.")

        if recovery_score < 60:
            weaknesses.append("인터럽트 이후 회복이 느린 편입니다.")

        if not weaknesses:
            weaknesses.append("뚜렷한 약점은 적지만 세부 표현을 더 다듬을 여지가 있습니다.")

        return weaknesses

    def _build_improvements(self, weaknesses: list[str]) -> list[str]:
        """
        약점을 개선 포인트로 변환
        """
        improvements = []

        for weakness in weaknesses:
            if "말속도" in weakness:
                improvements.append("핵심 문장마다 짧은 pause를 두고 일정한 속도로 말하는 연습이 필요합니다.")
            elif "필러" in weakness:
                improvements.append("답변 전에 1초 정도 생각한 뒤 말하는 습관으로 필러를 줄여보세요.")
            elif "침묵" in weakness:
                improvements.append("예상 질문에 대한 답변 템플릿을 준비해 침묵 구간을 줄여보세요.")
            elif "답변 구체성" in weakness:
                improvements.append("답변에 이유, 예시, 근거를 함께 넣는 방식으로 구체성을 높여보세요.")
            elif "회복" in weakness:
                improvements.append("인터럽트 직후 핵심 키워드부터 다시 꺼내 말하는 회복 훈련이 필요합니다.")

        if not improvements:
            improvements.append("다음 세션에서는 표현을 더 자연스럽게 다듬는 연습을 해보세요.")

        return improvements

    def _calculate_overall_score(
        self,
        summary: ReportSummary,
        recovery_score: float,
        weaknesses: list[str]
    ) -> float:
        """
        Overall Score 계산

        단순 예시 기준
        - 평균 답변 점수
        - 회복 점수
        - 필러 / 침묵 / 약점 개수 패널티
        """
        base = 50.0

        base += min(summary.avg_answer_score * 0.3, 30.0)
        base += recovery_score * 0.2

        if summary.filler_count >= 5:
            base -= 8

        if summary.silence_count >= 3:
            base -= 8

        base -= max(len(weaknesses) - 1, 0) * 3

        return max(0.0, min(base, 100.0))

    def _update_user_pattern(
        self,
        data: ReportGenerationInput,
        weaknesses: list[str]
    ) -> UserPatternOutput:
        """
        사용자 누적 패턴 갱신

        - session_count 증가
        - 약점 누적
        - 5회차 이후 반복 약점 추적 시작
        """
        previous_count = data.user_pattern.session_count
        new_count = previous_count + 1

        repeated = list(data.user_pattern.repeated_weaknesses)

        if new_count >= 5:
            for weakness in weaknesses:
                if weakness not in repeated:
                    repeated.append(weakness)

        trend = self._infer_trend(weaknesses)

        return UserPatternOutput(
            session_count=new_count,
            repeated_weaknesses=repeated,
            trend=trend
        )

    def _infer_trend(self, weaknesses: list[str]) -> str:
        """
        장기 추세를 단순 추정
        """
        if len(weaknesses) <= 1:
            return "improving"
        if len(weaknesses) <= 3:
            return "stable"
        return "declining"

    def _recommend_curriculum(
        self,
        updated_pattern: UserPatternOutput,
        weaknesses: list[str],
        recovery_score: float
    ) -> str:
        """
        다음 추천 커리큘럼 생성
        """
        if updated_pattern.session_count >= 5 and updated_pattern.repeated_weaknesses:
            if any("필러" in item for item in updated_pattern.repeated_weaknesses):
                return "필러 감소 집중 훈련 — 짧은 정지 후 답변 연습"

            if any("침묵" in item for item in updated_pattern.repeated_weaknesses):
                return "즉답 훈련 심화 — 예상 질문 템플릿 반복 연습"

            if any("답변 구체성" in item for item in updated_pattern.repeated_weaknesses):
                return "근거·예시 확장 훈련 — STAR 방식 답변 연습"

        if recovery_score < 60:
            return "압박 질문 대응 훈련 — 인터럽트 직후 회복 연습"

        if any("말속도" in weakness for weakness in weaknesses):
            return "발화 속도 조절 훈련 — 문장 끝 pause 연습"

        return "종합 발표 안정화 훈련 — 답변 구조와 전달력 강화"