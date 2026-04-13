# 발화 속도(WPM)를 계산하는 유틸리티 모듈

from collections import deque
from typing import Deque, Tuple


class WPMCalculator:
    """
    단어 수와 시간을 기반으로 WPM(Words Per Minute)을 계산하는 클래스
    - 최근 10초 WPM
    - 전체 평균 WPM
    """

    def __init__(self, window_seconds: int = 10):
        # 최근 발화를 저장하는 슬라이딩 윈도우
        self.window_seconds = window_seconds
        self.word_timestamps: Deque[Tuple[int, int]] = deque()
        self.total_words = 0
        self.start_time = None

    def add_segment(self, text: str, start_ms: int, end_ms: int):
        """새로운 발화 세그먼트를 추가"""
        word_count = len(text.split())

        if self.start_time is None:
            self.start_time = start_ms

        self.total_words += word_count
        self.word_timestamps.append((end_ms, word_count))
        self._remove_old_entries(end_ms)

    def _remove_old_entries(self, current_time_ms: int):
        """슬라이딩 윈도우에서 오래된 데이터 제거"""
        window_start = current_time_ms - (self.window_seconds * 1000)
        while self.word_timestamps and self.word_timestamps[0][0] < window_start:
            self.word_timestamps.popleft()

    def get_recent_wpm(self, current_time_ms: int) -> float:
        """최근 10초 WPM 계산"""
        self._remove_old_entries(current_time_ms)
        words = sum(count for _, count in self.word_timestamps)
        minutes = self.window_seconds / 60
        return words / minutes if minutes > 0 else 0.0

    def get_average_wpm(self, current_time_ms: int) -> float:
        """전체 평균 WPM 계산"""
        if self.start_time is None:
            return 0.0

        elapsed_minutes = (current_time_ms - self.start_time) / 60000
        return self.total_words / elapsed_minutes if elapsed_minutes > 0 else 0.0