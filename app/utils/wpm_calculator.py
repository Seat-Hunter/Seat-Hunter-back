# app/utils/wpm_calculator.py

# 발화 속도(WPM)를 계산하는 유틸리티 모듈

from collections import deque
from typing import Deque, Tuple


class WPMCalculator:
    """
    단어 수와 시간을 기반으로 WPM(Words Per Minute)을 계산하는 클래스

    recent_wpm:
    - 최근 window_seconds 동안 들어온 단어 수를 기준으로 계산
    - 기본값: 최근 10초 기준

    average_wpm: 
    - 발표 시작 후 전체 경과 시간이 아니라
    - 실제 발화가 발생한 시간만 누적해서 계산
    - 침묵, 대기 시간 때문에 평균 WPM이 과도하게 낮아지는 문제를 줄임
    """

    def __init__(self, window_seconds: int = 10):
        # 최근 WPM 계산에 사용할 시간 창
        self.window_seconds = window_seconds

        # 최근 발화 저장
        # 형태: (발화 종료 시각 ms, 단어 수)
        self.word_timestamps: Deque[Tuple[int, int]] = deque()

        # 전체 단어 수
        self.total_words = 0

        # 첫 발화 시작 시간
        self.start_time = None

        # 실제 말한 시간만 누적한 값
        self.total_speaking_ms = 0

    def add_segment(self, text: str, start_ms: int, end_ms: int):
        """
        새로운 발화 세그먼트를 추가한다.

        text:
        - STT로 인식된 최종 발화 텍스트

        start_ms, end_ms:
        - 해당 발화의 시작/종료 시간
        """

        if not text or not text.strip():
            return

        # 한국어에서는 정확히 word라기보다 띄어쓰기 기준 어절 수에 가까움
        word_count = len(text.split())

        if word_count <= 0:
            return

        if self.start_time is None:
            self.start_time = start_ms

        # 발화 시간 계산
        duration_ms = end_ms - start_ms

        # duration이 비정상적으로 들어오는 경우 방어
        # 예: end_ms == start_ms, duration 없음, 음수 등
        if duration_ms <= 0:
            # fallback:
            # 단어당 약 400ms 정도로 임시 추정
            # 1분에 약 150어절 정도의 속도
            duration_ms = word_count * 400

        self.total_words += word_count
        self.total_speaking_ms += duration_ms

        self.word_timestamps.append((end_ms, word_count))
        self._remove_old_entries(end_ms)

    def _remove_old_entries(self, current_time_ms: int):
        """
        최근 window_seconds 범위를 벗어난 발화 기록 제거
        """
        window_start = current_time_ms - (self.window_seconds * 1000)

        while self.word_timestamps and self.word_timestamps[0][0] < window_start:
            self.word_timestamps.popleft()

    def get_recent_wpm(self, current_time_ms: int) -> float:
        """
        최근 window_seconds 기준 WPM 계산

        예:
        - window_seconds = 10
        - 최근 10초 동안 20어절 말함
        - 20 / (10 / 60) = 120 WPM
        """

        self._remove_old_entries(current_time_ms)

        recent_words = sum(count for _, count in self.word_timestamps)
        recent_minutes = self.window_seconds / 60

        if recent_minutes <= 0:
            return 0.0

        return recent_words / recent_minutes

    def get_average_wpm(self, current_time_ms: int, excluded_ms: int = 0) -> float:
        """
        전체 평균 WPM 계산

        기존 방식:
        - 발표 시작 후 현재까지의 전체 경과 시간 기준
        - 침묵이나 대기 시간이 포함되어 평균 WPM이 낮게 잡힐 수 있음

        수정 방식:
        - 실제 발화 세그먼트 시간만 누적해서 평균 계산
        - 즉, 사용자가 실제로 말한 시간 기준 WPM
        """

        if self.total_words <= 0:
            return 0.0

        if self.total_speaking_ms <= 0:
            return 0.0

        speaking_minutes = self.total_speaking_ms / 60000

        if speaking_minutes <= 0:
            return 0.0

        return self.total_words / speaking_minutes

    def reset(self):
        """
        세션 재시작 또는 계산기 초기화가 필요할 때 사용
        """
        self.word_timestamps.clear()
        self.total_words = 0
        self.start_time = None
        self.total_speaking_ms = 0