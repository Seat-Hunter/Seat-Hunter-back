# app/schemas/auth.py
# 회원가입, 로그인 요청/응답 스키마 정의 파일

import re

from pydantic import BaseModel, EmailStr, field_validator


class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    nickname: str | None = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, password: str) -> str:

        # 1. 최소 길이
        if len(password) < 8:
            raise ValueError("비밀번호는 최소 8자 이상이어야 합니다.")

        # 2. 영문 포함
        if not re.search(r"[A-Za-z]", password):
            raise ValueError("비밀번호에는 영문자가 포함되어야 합니다.")

        # 3. 숫자 포함
        if not re.search(r"\d", password):
            raise ValueError("비밀번호에는 숫자가 포함되어야 합니다.")

        # 4. 특수문자 포함
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
            raise ValueError("비밀번호에는 특수문자가 포함되어야 합니다.")

        return password


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    nickname: str | None = None

    class Config:
        from_attributes = True