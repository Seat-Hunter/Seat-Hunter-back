from fastapi import HTTPException, status
from app.core.supabase_client import get_supabase
from app.core.security import hash_password, verify_password, create_access_token
from app.schemas.auth import SignupRequest, LoginRequest


def signup(request: SignupRequest) -> dict:
    sb = get_supabase()

    existing = sb.table("users").select("id").eq("email", request.email).execute()
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 가입된 이메일입니다.",
        )

    result = sb.table("users").insert({
        "email": request.email,
        "password_hash": hash_password(request.password),
        "nickname": request.nickname,
    }).execute()

    user = result.data[0]
    return {"id": user["id"], "email": user["email"], "nickname": user.get("nickname")}


def login(request: LoginRequest) -> str:
    sb = get_supabase()

    result = sb.table("users").select("*").eq("email", request.email).execute()
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )

    user = result.data[0]
    if not verify_password(request.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )

    return create_access_token(data={"sub": str(user["id"])})


def get_user_by_id(user_id: int) -> dict:
    sb = get_supabase()
    result = sb.table("users").select("id, email, nickname").eq("id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자를 찾을 수 없습니다.")
    return result.data[0]
