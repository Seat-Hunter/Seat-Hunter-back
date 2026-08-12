# Seat Hunter Backend

발표를 실제 상황처럼 연습하고, 말하기 데이터를 바탕으로 개선점을 확인할 수 있도록 지원하는 **AI 발표 시뮬레이션 서비스**의 백엔드입니다.

사용자는 발표 세션을 생성해 실시간으로 말하고, 서비스는 음성을 텍스트로 변환해 발화 속도·침묵·추임새 등을 분석합니다. 발표 중에는 청중의 질문과 음성 응답을 제공하며, 종료 후에는 종합 평가 리포트와 발표 기록을 제공합니다.

## 주요 기능

- 회원가입·로그인 및 JWT 기반 인증
- 발표 세션 생성, 시작, 종료, 취소
- WebSocket 기반 실시간 음성 데이터 처리
- STT를 통한 발표 대본 생성과 발화 분석
- AI 청중 질문 및 TTS 음성 응답
- 발화 속도, 침묵, 추임새, 질문 응답 등을 반영한 발표 리포트
- 발표 이력, 대본, 질문·답변 조회 및 관리

## 기술 구성

| 영역 | 사용 기술 |
| --- | --- |
| API 서버 | FastAPI, Uvicorn, Pydantic |
| 실시간 통신 | WebSocket, Redis |
| 데이터·인증 | Supabase, SQLAlchemy, JWT |
| AI·음성 | OpenAI, Google Gemini, Deepgram STT, ElevenLabs TTS |

## 빠른 시작

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경 변수 설정

프로젝트 루트에 `.env` 파일을 만들고 필요한 값을 설정합니다.

```env
REDIS_URL=redis://localhost:6379
SUPABASE_URL=
SUPABASE_KEY=
DEEPGRAM_API_KEY=
ELEVENLABS_API_KEY=
GEMINI_API_KEY=
OPENAI_API_KEY=
SECRET_KEY=
```

### 3. 서버 실행

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

서버 실행 후 다음 주소에서 상태와 API 문서를 확인할 수 있습니다.

- 상태 확인: `http://localhost:8000/health`
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 문서

- [API 명세](API.md)
- [개발 환경 실행 가이드](docs/DEVELOPMENT.md)

## 프로젝트 구조

```text
app/
├── api/        # REST API 라우터 및 인증 의존성
├── core/       # 환경 설정, Redis, Supabase, 보안, WebSocket 관리
├── schemas/    # 요청·응답 데이터 모델
├── services/   # 세션, 음성, AI 분석, 리포트 등 비즈니스 로직
├── utils/      # 발화 속도, 침묵, 추임새 분석 유틸리티
├── ws/         # 실시간 발표 세션 WebSocket
└── main.py     # FastAPI 애플리케이션 진입점
```
