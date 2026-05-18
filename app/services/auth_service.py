# app/services/auth_service.py
# 회원가입, 로그인 비즈니스 로직 처리 파일

from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.user import User
from app.schemas.auth import SignupRequest, LoginRequest
from app.core.security import hash_password, verify_password, create_access_token
from app.schemas.auth import SignupRequest, LoginRequest, FindPasswordRequest, ResetPasswordRequest

def signup(db: Session, request: SignupRequest) -> User:
    existing_user = db.query(User).filter(User.email == request.email).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 가입된 이메일입니다.",
        )

    new_user = User(
        email=request.email,
        password_hash=hash_password(request.password),
        nickname=request.nickname,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


def login(db: Session, request: LoginRequest) -> str:
    user = db.query(User).filter(User.email == request.email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )

    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )

    access_token = create_access_token(
        data={"sub": str(user.id)}
    )

    return access_token

def find_password(db: Session, request: FindPasswordRequest) -> dict:
    user = db.query(User).filter(User.email == request.email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="가입된 이메일이 아닙니다.",
        )

    return {
        "message": "가입된 이메일입니다. 비밀번호 재설정이 가능합니다.",
        "email": user.email,
    }


def reset_password(db: Session, request: ResetPasswordRequest) -> dict:
    user = db.query(User).filter(User.email == request.email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="가입된 이메일이 아닙니다.",
        )

    user.password_hash = hash_password(request.new_password)

    db.commit()
    db.refresh(user)

    return {
        "message": "비밀번호가 성공적으로 변경되었습니다.",
    }