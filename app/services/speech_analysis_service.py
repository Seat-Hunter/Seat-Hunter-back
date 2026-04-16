# 발화 품질을 실시간으로 분석하는 핵심 서비스 모듈

from app.utils.wpm_calculator import WPMCalculator
from app.utils.filler_detector import FillerDetector
from app.utils.silence_tracker import SilenceTracker
from app.schemas.speech_analysis import (
    SpeechAnalysisInput,
    SpeechAnalysisResult
)


class SpeechAnalysisService:
    """
    Speech Analyzer 서비스

    기능:
    - WPM 계산
    - 필러 탐지
    - 침묵 구간 분석
    - 응답 지연 계산
    - hesitation 및 stress score 산출
    """

    def __init__(self):
        self.wpm_calculator = WPMCalculator()
        self.filler_detector = FillerDetector()
        self.silence_tracker = SilenceTracker()
        self.total_fillers = 0
        self.last_interrupt_time = None
        self.previous_wpm = 0

    def analyze(self, data: SpeechAnalysisInput) -> SpeechAnalysisResult:
        """발화 데이터를 분석하여 지표를 반환"""

        text = data.text
        start_ms = data.start_ms
        end_ms = data.end_ms

        # 1. WPM 계산
        self.wpm_calculator.add_segment(text, start_ms, end_ms)
        recent_wpm = self.wpm_calculator.get_recent_wpm(end_ms)
        average_wpm = self.wpm_calculator.get_average_wpm(end_ms)

        # 2. 필러 계산
        filler_count_segment = self.filler_detector.count_fillers(text)
        self.total_fillers += filler_count_segment

        # 3. 침묵 계산
        self.silence_tracker.update(start_ms)
        self.silence_tracker.set_last_end(end_ms)

        silence_duration = self.silence_tracker.total_silence_ms
        current_silence_ms = self.silence_tracker.last_silence_ms
        silence_count = self.silence_tracker.silence_count

        # 4. 응답 지연 계산
        response_latency = 0
        if self.last_interrupt_time is not None:
            response_latency = start_ms - self.last_interrupt_time
            self.last_interrupt_time = None

        # 5. 인터럽트 발생 기록
        if data.is_interrupt:
            self.last_interrupt_time = end_ms

        # 6. Hesitation Score 계산
        hesitation_score = min(
            1.0,
            (filler_count_segment * 0.1) + (silence_count * 0.05)
        )

        # 7. Stress Score 계산 — per-segment 필러와 WPM 변화량 기반
        wpm_change = abs(recent_wpm - self.previous_wpm)
        stress_score = min(
            1.0,
            (wpm_change * 0.02) + (filler_count_segment * 0.15)
        )
        self.previous_wpm = recent_wpm

        return SpeechAnalysisResult(
            recent_wpm=round(recent_wpm, 2),
            average_wpm=round(average_wpm, 2),
            filler_count=self.total_fillers,
            filler_count_segment=filler_count_segment,
            silence_duration=silence_duration,
            current_silence_ms=current_silence_ms,
            silence_count=silence_count,
            response_latency=response_latency,
            hesitation_score=round(hesitation_score, 3),
            stress_score=round(stress_score, 3),
        )