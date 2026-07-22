### Back (Python 3.10+ 필수)

**이미 `Seat-Hunter-back` 폴더에 있으면** `cd` 없이:

```powershell
.\run.ps1
```

프로젝트 루트에서:

```powershell
cd Seat-Hunter-back
.\run.ps1
```

포트 8000이 사용 중이면 스크립트가 8001~8010 중 빈 포트를 자동 선택합니다.
8000이 이미 떠 있다면 그대로 http://127.0.0.1:8000 사용해도 됩니다.

처음 1회 의존성 설치:

```powershell
& "C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe" -m pip install -r requirements.txt
```

### Front

```powershell
cd Seat-Hunter-front\frontend
npm install
npm run dev
```

브라우저: http://localhost:5173
