# 침묵 구간을 추적하는 유틸리티 모듈

class SilenceTracker:
    """
    1초 이상 침묵 구간을 추적하는 클래스
    """

    def __init__(self):
        self.last_end_ms = None
        self.silence_count = 0
        self.total_silence_ms = 0
        self.last_silence_ms = 0  # 직전 세그먼트 간 침묵 (현재 판단용)

    def update(self, start_ms: int):
        """새로운 발화 시작 시 침묵 계산"""
        if self.last_end_ms is not None:
            silence_duration = start_ms - self.last_end_ms
            self.last_silence_ms = max(0, silence_duration)
            if silence_duration >= 1000:
                self.silence_count += 1
                self.total_silence_ms += silence_duration
        else:
            self.last_silence_ms = 0

    def set_last_end(self, end_ms: int):
        """마지막 발화 종료 시간 기록"""
        self.last_end_ms = end_ms