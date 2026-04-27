"""Todo / User SQLAlchemy + Pydantic 모델.

생성: T-001 (Backend agent)
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Boolean
from sqlalchemy.orm import relationship

from database import Base


# ── SQLAlchemy ORM ──────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    todos = relationship("Todo", back_populates="owner", cascade="all, delete-orphan")


class Todo(Base):
    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False, index=True)
    description = Column(String, default="")
    completed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    owner = relationship("User", back_populates="todos")


# ── Pydantic schemas ────────────────────────────────────────────────


class TodoBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    completed: bool = False


class TodoCreate(TodoBase):
    pass


class TodoPatch(BaseModel):
    """JSON Merge Patch (RFC 7396) — 모든 필드 optional."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    completed: Optional[bool] = None


class TodoOut(TodoBase):
    id: int
    created_at: datetime
    updated_at: datetime
    owner_id: int

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    email: str
    password: str = Field(..., min_length=8)


class UserOut(BaseModel):
    id: int
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
