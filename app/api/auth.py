# app/api/auth.py

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import SignupRequest, LoginRequest, TokenResponse, UserResponse
from app.services.auth_service import signup, login
from app.core.security import decode_access_token

from app.schemas.auth import (
    SignupRequest,
    LoginRequest,
    TokenResponse,
    UserResponse,
    FindPasswordRequest,
    ResetPasswordRequest,
)
from app.services.auth_service import signup, login, find_password, reset_password


router = APIRouter(prefix="/auth", tags=["Auth"])
security = HTTPBearer()


@router.post("/signup", response_model=UserResponse)
def signup_api(
    request: SignupRequest,
    db: Session = Depends(get_db),
):
    return signup(db, request)


@router.post("/login", response_model=TokenResponse)
def login_api(
    request: LoginRequest,
    db: Session = Depends(get_db),
):
    access_token = login(db, request)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
    )

@router.post("/find-password")
def find_password_api(
    request: FindPasswordRequest,
    db: Session = Depends(get_db),
):
    return find_password(db, request)


@router.post("/reset-password")
def reset_password_api(
    request: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    return reset_password(db, request)

@router.get("/me", response_model=UserResponse)
def get_me(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다.",
        )

    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다.",
        )

    user = db.query(User).filter(User.id == int(user_id)).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다.",
        )

    return user

