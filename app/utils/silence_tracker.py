# 침묵 구간을 추적하는 유틸리티 모듈

import time


class SilenceTracker:
    """
    1초 이상 침묵 구간을 추적하는 클래스.
    Deepgram 상대 타임스탬프와 Unix 타임스탬프가 혼용되는 문제를 피하기 위해
    내부적으로 wall clock 시간을 사용한다.
    """

    def __init__(self):
        self._last_end_wall_ms: float | None = None
        self.silence_count = 0
        self.total_silence_ms = 0
        self.last_silence_ms = 0

    def update(self, start_ms: int):
        """새로운 발화 시작 시 침묵 계산 (start_ms는 무시하고 wall clock 사용)"""
        now_ms = int(time.time() * 1000)
        if self._last_end_wall_ms is not None:
            silence_duration = now_ms - self._last_end_wall_ms
            self.last_silence_ms = max(0, silence_duration)
            if silence_duration >= 1000:
                self.silence_count += 1
                self.total_silence_ms += silence_duration
        else:
            self.last_silence_ms = 0

    def set_last_end(self, end_ms: int):
        """마지막 발화 종료 시간을 wall clock으로 기록 (end_ms는 무시)"""
        self._last_end_wall_ms = int(time.time() * 1000)