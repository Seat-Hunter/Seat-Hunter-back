# Seat Hunter — API 명세서

> **Swagger UI**: `http://localhost:8000/docs`  
> **ReDoc**: `http://localhost:8000/redoc`

---

## 목차

1. [공통 사항](#공통-사항)
2. [REST API](#rest-api)
   - [Health](#health)
   - [Session](#session)
   - [Report](#report)
3. [WebSocket API](#websocket-api)
   - [연결](#연결)
   - [클라이언트 → 서버 메시지](#클라이언트--서버-메시지)
   - [서버 → 클라이언트 메시지](#서버--클라이언트-메시지)
4. [세션 상태 머신](#세션-상태-머신)
5. [React 연동 예시](#react-연동-예시)

---

## 공통 사항

| 항목 | 값 |
|---|---|
| Base URL | `http://localhost:8000` |
| API 접두사 | `/api/v1` |
| WebSocket | `ws://localhost:8000/ws/sessions/{session_id}` |
| Content-Type | `application/json` |

### CORS 허용 오리진

`.env`의 `CORS_ORIGINS` 값으로 제어합니다 (기본: `http://localhost:3000,http://localhost:5173`).

프로덕션 배포 시 반드시 실제 프론트엔드 도메인으로 변경하세요.

```env
CORS_ORIGINS=https://your-frontend.com
```

---

## REST API

### Health

#### `GET /health`

서버 상태를 확인합니다.

**Response 200**
```json
{ "status": "ok" }
```

---

### Session

#### `POST /api/v1/sessions` — 세션 생성

발표 시뮬레이션 세션을 생성합니다.  
반환된 `session_id`로 WebSocket에 연결한 뒤 `/start`를 호출하세요.

**Request Body**
```json
{
  "user_id": 1,
  "presentation_type": "academic",
  "audience_type": "professor",
  "audience_count": 30,
  "pressure_level": "medium",
  "duration_seconds": 300,
  "interrupt_enabled": true,
  "script_text": "오늘 발표할 주제는...",
  "slide_texts": ["슬라이드 1 내용", "슬라이드 2 내용"]
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `user_id` | int | ✅ | 유저 ID |
| `presentation_type` | string | ✅ | 발표 유형 (예: `"academic"`, `"business"`) |
| `audience_type` | string | ✅ | 청중 유형 (예: `"professor"`, `"investor"`) |
| `audience_count` | int | | 청중 수 |
| `pressure_level` | `"low"` \| `"medium"` \| `"high"` | | 압박 강도 (기본: `"medium"`) |
| `duration_seconds` | int | | 발표 제한 시간 초 (기본: `300`) |
| `interrupt_enabled` | bool | | 인터럽트 활성화 여부 (기본: `true`) |
| `script_text` | string | | 발표 스크립트 전문 |
| `slide_texts` | string[] | | 슬라이드별 텍스트 목록 |

**Response 201**
```json
{
  "session_id": "sess_a1b2c3d4e5f6",
  "state": "READY"
}
```

---

#### `POST /api/v1/sessions/{session_id}/start` — 세션 시작

세션 상태를 `READY` → `RUNNING`으로 전환합니다.

**Path Parameter**
| 파라미터 | 타입 | 설명 |
|---|---|---|
| `session_id` | string | 세션 ID |

**Response 200**
```json
{
  "session_id": "sess_a1b2c3d4e5f6",
  "state": "RUNNING"
}
```

---

#### `POST /api/v1/sessions/{session_id}/end` — 세션 종료

세션을 종료하고 분석 리포트를 자동 생성합니다.  
종료 후 `/report` 엔드포인트로 결과를 조회할 수 있습니다.

**Response 200**
```json
{
  "session_id": "sess_a1b2c3d4e5f6",
  "state": "FINISHED"
}
```

---

### Report

#### `GET /api/v1/sessions/{session_id}/report` — 세션 리포트 조회

세션 종료 후 생성된 분석 리포트를 반환합니다.

**Response 200**
```json
{
  "session_id": "sess_a1b2c3d4e5f6",
  "summary": {
    "avg_wpm": 132.5,
    "max_wpm": 178.0,
    "filler_count": 7,
    "silence_count": 3,
    "interrupt_count": 2,
    "avg_answer_score": 0.72
  },
  "feedback": {
    "strengths": ["안정적인 말속도", "명확한 논리 구조"],
    "weaknesses": ["필러 단어 과다 사용", "침묵 구간 빈번"],
    "improvements": ["호흡 조절 연습", "핵심 키워드 정리 후 발표"]
  },
  "curriculum_next": "필러 없이 1분 스피치 연습"
}
```

**Response 404**
```json
{ "detail": "리포트 없음. 세션이 아직 종료되지 않았거나 생성 전입니다." }
```

---

#### `GET /api/v1/users/{user_id}/sessions` — 유저 세션 목록

특정 유저의 전체 발표 세션 이력을 반환합니다.

**Response 200**
```json
[
  {
    "session_id": "sess_a1b2c3d4e5f6",
    "created_at": "2026-04-15T10:00:00Z",
    "state": "FINISHED"
  }
]
```

---

#### `GET /api/v1/sessions/{session_id}/interrupts` — 인터럽트 목록

세션 중 발생한 모든 인터럽트 질문 이력을 반환합니다.

**Response 200**
```json
[
  {
    "question_text": "방금 언급하신 내용을 좀 더 구체적으로 설명해주실 수 있나요?",
    "reason": "[pressure=medium] 3초 이상 침묵이 감지되었습니다.",
    "interrupt_type": "encouragement_probe",
    "answered": true,
    "answer_score": 0.8
  }
]
```

---

## WebSocket API

### 연결

```
ws://localhost:8000/ws/sessions/{session_id}
```

세션 생성 → `start` 호출 → WebSocket 연결 순서로 진행하세요.

---

### 클라이언트 → 서버 메시지

#### `audio_chunk` — 음성 데이터 전송

마이크에서 캡처한 PCM/WebM 오디오를 base64로 인코딩하여 전송합니다.

```json
{
  "type": "audio_chunk",
  "timestamp_ms": 1713180000000,
  "audio_base64": "UklGRiQA..."
}
```

---

#### `partial_transcript` — 부분 텍스트

클라이언트 측 VAD/STT 중간 결과를 전송합니다 (선택사항).

```json
{
  "type": "partial_transcript",
  "timestamp_ms": 1713180001000,
  "text": "안녕하세요 오늘 발표"
}
```

---

#### `vad_state` — 발화 감지 상태

사용자가 말하고 있는지 여부를 서버에 알립니다.

```json
{
  "type": "vad_state",
  "timestamp_ms": 1713180002000,
  "is_speaking": true
}
```

---

#### `tts_finished` — TTS 재생 완료

클라이언트에서 인터럽트 음성 재생이 완료됐음을 서버에 알립니다.  
서버는 이를 받아 세션 상태를 `INTERRUPTED` → `RUNNING`으로 복귀시킵니다.

```json
{
  "type": "tts_finished",
  "question_id": "q_1"
}
```

---

#### `answer_state` — 답변 시작/종료

인터럽트 질문에 대한 답변 시작/종료를 서버에 알립니다.

```json
{
  "type": "answer_state",
  "question_id": "q_1",
  "state": "started"
}
```

| `state` | 설명 |
|---|---|
| `"started"` | 답변 시작 → 세션 상태 `ANSWERING` |
| `"ended"` | 답변 종료 |

---

### 서버 → 클라이언트 메시지

#### `live_metrics` — 실시간 발화 지표

발화 세그먼트마다 전송됩니다.

```json
{
  "type": "live_metrics",
  "wpm": 132.5,
  "filler_count": 3,
  "silence_ms": 800,
  "stress_score": 0.42
}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `wpm` | float | 최근 분당 단어 수 |
| `filler_count` | int | 누적 필러 단어 수 |
| `silence_ms` | int | 누적 침묵 시간 (ms) |
| `stress_score` | float | 스트레스 점수 (0~1) |

---

#### `live_feedback` — 실시간 피드백

임계치 초과 시 1회성 코칭 메시지를 전송합니다.

```json
{
  "type": "live_feedback",
  "message": "말속도가 너무 빠릅니다. 천천히 말씀해보세요."
}
```

| 트리거 조건 | 메시지 |
|---|---|
| WPM > 170 | 말속도가 너무 빠릅니다 |
| WPM < 60 (발화 중) | 말속도가 너무 느립니다 |
| filler_count ≥ 5 | 필러 단어가 늘고 있습니다 |
| stress_score > 0.7 | 긴장이 감지됩니다 |
| silence_duration > 4000ms | 침묵이 길어지고 있습니다 |

---

#### `interrupt_question` — 인터럽트 질문

AI 청중이 발표자에게 끼어드는 질문입니다.

```json
{
  "type": "interrupt_question",
  "question_id": "q_1",
  "question_text": "방금 언급하신 내용을 좀 더 구체적으로 설명해주실 수 있나요?",
  "pressure_level": "medium"
}
```

---

#### `tts_audio` — 인터럽트 질문 음성

`interrupt_question` 직후 TTS 변환된 MP3를 base64로 전송합니다.  
수신 즉시 자동 재생하고, 완료 후 `tts_finished`를 서버로 보내세요.

```json
{
  "type": "tts_audio",
  "question_text": "방금 언급하신 내용을 좀 더 구체적으로 설명해주실 수 있나요?",
  "audio_base64": "/+MYxAA...",
  "format": "mp3"
}
```

---

#### `session_state` — 세션 상태 변경

세션 상태가 바뀔 때마다 전송됩니다.

```json
{
  "type": "session_state",
  "state": "INTERRUPTED"
}
```

| 상태 | 설명 |
|---|---|
| `READY` | 생성됨, 시작 대기 |
| `RUNNING` | 발표 진행 중 |
| `INTERRUPTED` | 인터럽트 발생, TTS 재생 중 |
| `ANSWERING` | 질문 답변 중 |
| `FINISHED` | 세션 종료 |

---

#### `audience_reaction` — 청중 반응

발화 지표 기반 가상 청중 반응을 전송합니다.

```json
{
  "type": "audience_reaction",
  "reaction": "nodding",
  "intensity": 0.6
}
```

---

## 세션 상태 머신

```
READY
  │ POST /start
  ▼
RUNNING ──────────────────────────┐
  │ 인터럽트 트리거                    │
  ▼                               │
INTERRUPTED (TTS 재생 중)          │
  │ tts_finished 수신              │
  ▼                               │
RUNNING ◄───────────────────────  │
  │ answer_state: started         │
  ▼                               │
ANSWERING                          │
  │ answer_state: ended           │
  ▼                               │
RUNNING ◄───────────────────────  │
  │ POST /end                     │
  ▼                               │
FINISHED ◄──────────────────────── ┘
```

**인터럽트 트리거 조건** (30초 쿨다운 적용)

| 조건 | 인터럽트 유형 |
|---|---|
| 침묵 ≥ 3초 | `encouragement_probe` |
| WPM 25% 이상 급감 | `recovery_probe` |
| 필러 2개 이상 급증 | `logic_probe` |
| 주제 이탈 점수 > 0.65 | `topic_clarification` |
| 고압박 + 주제 전환 감지 | `pressure_probe` |

---

## React 연동 예시

### 세션 생성 및 WebSocket 연결

```typescript
// 1. 세션 생성
const res = await fetch('http://localhost:8000/api/v1/sessions', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    user_id: 1,
    presentation_type: 'academic',
    audience_type: 'professor',
    pressure_level: 'medium',
    duration_seconds: 300,
    interrupt_enabled: true,
  }),
});
const { session_id } = await res.json();

// 2. 세션 시작
await fetch(`http://localhost:8000/api/v1/sessions/${session_id}/start`, {
  method: 'POST',
});

// 3. WebSocket 연결
const ws = new WebSocket(`ws://localhost:8000/ws/sessions/${session_id}`);

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  switch (msg.type) {
    case 'live_metrics':
      // WPM, 필러, 침묵, 스트레스 지표 업데이트
      break;
    case 'live_feedback':
      // 코칭 메시지 표시
      break;
    case 'interrupt_question':
      // 질문 텍스트 화면에 표시
      break;
    case 'tts_audio':
      // MP3 base64 → Audio 재생
      const audio = new Audio(
        `data:audio/mp3;base64,${msg.audio_base64}`
      );
      audio.onended = () => {
        ws.send(JSON.stringify({ type: 'tts_finished', question_id: msg.question_id }));
      };
      audio.play();
      break;
    case 'session_state':
      // RUNNING / INTERRUPTED / ANSWERING / FINISHED
      break;
  }
};

// 4. 음성 청크 전송 (MediaRecorder 사용)
function sendAudioChunk(blob: Blob) {
  const reader = new FileReader();
  reader.onload = () => {
    const base64 = (reader.result as string).split(',')[1];
    ws.send(JSON.stringify({
      type: 'audio_chunk',
      timestamp_ms: Date.now(),
      audio_base64: base64,
    }));
  };
  reader.readAsDataURL(blob);
}

// 5. 세션 종료
await fetch(`http://localhost:8000/api/v1/sessions/${session_id}/end`, {
  method: 'POST',
});

// 6. 리포트 조회
const report = await fetch(
  `http://localhost:8000/api/v1/sessions/${session_id}/report`
).then(r => r.json());
```
