# NLP / LLM 분석 엔진이 함께 잘 동작하는지 확인하는 테스트 코드

from app.schemas.analysis import AnalysisInput
from app.services.nlp_service import NLPService
from app.services.llm_service import LLMService
from app.services.analysis_scheduler_service import AnalysisSchedulerService


def run_test():
    """
    경량 NLP 분석 후, 조건에 따라 LLM 분석이 호출되는지 테스트한다.
    """
    nlp_service = NLPService()
    llm_service = LLMService()
    scheduler = AnalysisSchedulerService()

    inputs = [
        AnalysisInput(
            text="먼저 이 서비스의 핵심 기능은 실시간 음성 분석입니다.",
            recent_context=[],
            expected_topics=["실시간", "음성", "분석", "피드백"],
            current_time_ms=1000,
            is_interrupt_imminent=False
        ),
        AnalysisInput(
            text="그리고 다음으로 발표 중 필러 단어와 침묵 구간을 측정합니다.",
            recent_context=["먼저 이 서비스의 핵심 기능은 실시간 음성 분석입니다."],
            expected_topics=["실시간", "음성", "분석", "피드백"],
            current_time_ms=4000,
            is_interrupt_imminent=False
        ),
        AnalysisInput(
            text="갑자기 날씨 이야기로 넘어가보면 오늘은 비가 옵니다.",
            recent_context=[
                "먼저 이 서비스의 핵심 기능은 실시간 음성 분석입니다.",
                "그리고 다음으로 발표 중 필러 단어와 침묵 구간을 측정합니다."
            ],
            expected_topics=["실시간", "음성", "분석", "피드백"],
            current_time_ms=12000,
            is_interrupt_imminent=False
        ),
    ]

    for idx, item in enumerate(inputs, start=1):
        print(f"\n===== Test Case {idx} =====")

        nlp_result = nlp_service.analyze(item)
        print("[NLP RESULT]")
        print(nlp_result.model_dump())

        should_call = scheduler.should_call_llm(
            current_time_ms=item.current_time_ms,
            nlp_result=nlp_result,
            is_interrupt_imminent=item.is_interrupt_imminent
        )

        print(f"[SHOULD CALL LLM] {should_call}")

        if should_call:
            llm_result = llm_service.analyze(item, nlp_result)
            scheduler.mark_llm_called(item.current_time_ms)
            print("[LLM RESULT]")
            print(llm_result.model_dump())


if __name__ == "__main__":
    run_test()