# 개발 환경 실행 가이드

기존 README에 있던 로컬 실행 절차입니다.

## 백엔드

```powershell
cd C:\code\Seat-Hunter-back
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 프런트엔드

프런트엔드 저장소에서 다음 명령을 실행합니다.

```powershell
cd C:\code\Seat-Hunter\frontend
npm install
npm run dev
```
