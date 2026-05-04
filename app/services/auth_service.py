import uuid
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


def create_access_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


async def create_user(
    session: AsyncSession,
    email: str,
    password: str,
    username: str | None = None,
    invite_code: str | None = None,
) -> User:
    existing = await session.scalar(select(User).where(User.email == email))
    if existing:
        raise ValueError("Email already registered")

    # Beta gate: when BETA_INVITE_CODE is configured, every signup must supply it.
    is_tester = False
    if settings.BETA_INVITE_CODE:
        if not invite_code or invite_code.strip() != settings.BETA_INVITE_CODE:
            raise PermissionError("Invalid invite code")
        is_tester = True

    user = User(
        email=email,
        username=username,
        password_hash=hash_password(password),
        role="player",
        is_active=True,
        is_tester=is_tester,
    )
    session.add(user)
    await session.flush()
    return user


async def authenticate_user(
    session: AsyncSession,
    email: str,
    password: str,
) -> User | None:
    user = await session.scalar(select(User).where(User.email == email))
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def get_current_user(session: AsyncSession, token: str) -> User | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id_str = payload.get("sub")
        if user_id_str is None:
            return None
        user_id = uuid.UUID(user_id_str)
    except (JWTError, ValueError):
        return None
    return await session.get(User, user_id)
