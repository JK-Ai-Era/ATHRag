"""认证模块 - JWT Token 认证"""

import bcrypt
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel

from src.rag_api.config import get_settings

# HTTP Bearer 安全方案
security = HTTPBearer(auto_error=False)


class TokenData(BaseModel):
    """Token 数据模型"""
    username: Optional[str] = None


class User(BaseModel):
    """用户模型"""
    username: str


class UserInDB(User):
    """数据库用户模型"""
    hashed_password: str


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    try:
        # 处理存储的哈希密码（可能是 bcrypt 格式）
        if hashed_password.startswith('$2'):
            # bcrypt 格式
            return bcrypt.checkpw(
                plain_password.encode('utf-8'),
                hashed_password.encode('utf-8')
            )
        return False
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """获取密码哈希"""
    # bcrypt 自动处理 salt 生成
    password_bytes = password.encode('utf-8')
    # bcrypt 有72字节限制
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12))
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    settings = get_settings()
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """解码令牌"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        return payload
    except JWTError:
        return None


def authenticate_user(username: str, password: str) -> Optional[User]:
    """验证用户"""
    settings = get_settings()
    
    if not settings.AUTH_ENABLED:
        return User(username=username)
    
    # 检查用户名
    if username != settings.ADMIN_USERNAME:
        return None
    
    # 检查密码哈希是否已配置
    if not settings.ADMIN_PASSWORD_HASH:
        return None
    
    # 验证密码
    if not verify_password(password, settings.ADMIN_PASSWORD_HASH):
        return None
    
    return User(username=username)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> User:
    """获取当前用户（依赖函数）"""
    settings = get_settings()
    
    # 如果认证未启用，返回默认用户
    if not settings.AUTH_ENABLED:
        return User(username="anonymous")
    
    # 检查是否提供了凭证
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    payload = decode_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    username: Optional[str] = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token_data = TokenData(username=username)
    user = User(username=token_data.username)
    
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """获取当前活跃用户"""
    return current_user
