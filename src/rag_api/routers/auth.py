"""认证路由模块"""

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from src.rag_api.auth import authenticate_user, create_access_token
from src.rag_api.config import get_settings

router = APIRouter(tags=["authentication"])


class Token(BaseModel):
    """令牌响应模型"""
    access_token: str
    token_type: str
    expires_in: int


class LoginRequest(BaseModel):
    """登录请求模型"""
    username: str
    password: str


class UserInfo(BaseModel):
    """用户信息模型"""
    username: str
    auth_enabled: bool


@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> Token:
    """用户登录
    
    使用表单数据提交:
    - username: 用户名
    - password: 密码
    
    返回 JWT access token。
    """
    user = authenticate_user(form_data.username, form_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    settings = get_settings()
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/login/json", response_model=Token)
async def login_json(login_data: LoginRequest) -> Token:
    """用户登录 (JSON 格式)
    
    使用 JSON 提交:
    ```json
    {
        "username": "admin",
        "password": "your-password"
    }
    ```
    
    返回 JWT access token。
    """
    user = authenticate_user(login_data.username, login_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    settings = get_settings()
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserInfo)
async def get_current_user_info() -> UserInfo:
    """获取当前认证状态"""
    settings = get_settings()
    return UserInfo(
        username=settings.ADMIN_USERNAME,
        auth_enabled=settings.AUTH_ENABLED,
    )
