from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.schemas.auth import SignupRequest, LoginRequest, TokenResponse, UserResponse
from app.services.auth_service import signup, login, get_user_by_id
from app.core.security import decode_access_token
from app.core.supabase_client import get_supabase

router = APIRouter(prefix="/auth", tags=["Auth"])
security = HTTPBearer()


@router.post("/signup", response_model=UserResponse)
def signup_api(request: SignupRequest):
    return signup(request)


@router.post("/login", response_model=TokenResponse)
def login_api(request: LoginRequest):
    access_token = login(request)
    return TokenResponse(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserResponse)
def get_me(credentials: HTTPAuthorizationCredentials = Depends(security)):
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰입니다.")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="유효하지 않은 토큰입니다.")
    return get_user_by_id(int(user_id))


@router.get("/user-count", tags=["Auth"])
def get_user_count():
    sb = get_supabase()
    res = sb.table("users").select("id", count="exact").execute()
    return {"count": res.count or 0}