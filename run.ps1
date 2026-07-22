# Seat-Hunter-back 실행 스크립트 (Python 3.11+ 필요)
$Python311 = "C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe"
$DefaultPort = 8000

if (-not (Test-Path $Python311)) {
    Write-Error "Python 3.11을 찾을 수 없습니다: $Python311"
    Write-Error "Python 3.10 이상을 설치한 뒤 다시 실행하세요."
    exit 1
}

Set-Location $PSScriptRoot

function Test-PortFree([int]$Port) {
    $inUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return -not $inUse
}

$Port = $DefaultPort
if (-not (Test-PortFree $Port)) {
    Write-Host "포트 $Port 이(가) 이미 사용 중입니다."
    $found = $false
    foreach ($candidate in 8001..8010) {
        if (Test-PortFree $candidate) {
            $Port = $candidate
            $found = $true
            break
        }
    }
    if (-not $found) {
        Write-Error "8000~8010 포트가 모두 사용 중입니다. 다른 uvicorn/python 프로세스를 종료한 뒤 다시 실행하세요."
        Write-Host "예: 작업 관리자에서 python 종료, 또는 기존 서버 터미널에서 Ctrl+C"
        exit 1
    }
    Write-Host "대신 포트 $Port 로 시작합니다."
    if ($Port -ne $DefaultPort) {
        Write-Host "프론트 .env 에 VITE_API_BASE_URL=http://localhost:$Port 설정이 필요할 수 있습니다."
    }
}

Write-Host "Python: $(& $Python311 -c 'import sys; print(sys.version.split()[0])')"
Write-Host "Server:  http://127.0.0.1:$Port"
Write-Host "Swagger: http://127.0.0.1:$Port/docs"
Write-Host ""
Write-Host "이미 Seat-Hunter-back 폴더에 있다면 cd 없이 .\run.ps1 만 실행하세요."
Write-Host ""

& $Python311 -m uvicorn app.main:app --host 127.0.0.1 --port $Port --reload
