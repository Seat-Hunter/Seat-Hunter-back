# Speech Analyzer 동작 테스트용 코드
# 이 파일은 발화 품질 분석 로직이 정상적으로 작동하는지 확인하기 위한 테스트 스크립트입니다.

from app.services.speech_analysis_service import SpeechAnalysisService
from app.schemas.speech_analysis import SpeechAnalysisInput


def run_test():
    """Speech Analyzer 테스트 실행 함수"""
    
    # 서비스 인스턴스 생성
    service = SpeechAnalysisService()

    # 테스트용 발화 데이터
    test_inputs = [
        SpeechAnalysisInput(
            text="음 안녕하세요 저는 AI 발표를 시작하겠습니다",
            start_ms=0,
            end_ms=4000,
            is_speaking=True
        ),
        SpeechAnalysisInput(
            text="어 이번 연구의 목적은 음성 분석입니다",
            start_ms=5000,
            end_ms=8000,
            is_speaking=True
        ),
        SpeechAnalysisInput(
            text="이상으로 발표를 마치겠습니다",
            start_ms=10000,
            end_ms=12000,
            is_speaking=True
        )
    ]

    # 분석 실행
    for i, data in enumerate(test_inputs, start=1):
        result = service.analyze(data)
        print(f"\n===== Test Case {i} =====")
        print(result.model_dump())


if __name__ == "__main__":
    run_test()