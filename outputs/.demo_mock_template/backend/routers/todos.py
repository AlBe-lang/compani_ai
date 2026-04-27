"""Todo CRUD 라우터.

생성: T-001 (Backend agent)
T-001 ↔ Frontend Q&A: PATCH 는 JSON Merge Patch (RFC 7396) 사용.
Peer review (Frontend reviewer): PASSED with MINOR — POST 시 201 응답 권장.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Todo, TodoCreate, TodoOut, TodoPatch, User


router = APIRouter()


@router.get("", response_model=List[TodoOut])
def list_todos(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """현재 사용자의 todo 목록 조회."""
    return (
        db.query(Todo)
        .filter(Todo.owner_id == current_user.id)
        .order_by(Todo.created_at.desc())
        .all()
    )


@router.post("", response_model=TodoOut, status_code=status.HTTP_201_CREATED)
def create_todo(
    payload: TodoCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """새 todo 생성. 201 Created 반환 (peer review 권고)."""
    todo = Todo(**payload.model_dump(), owner_id=current_user.id)
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return todo


@router.get("/{todo_id}", response_model=TodoOut)
def get_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    todo = (
        db.query(Todo)
        .filter(Todo.id == todo_id, Todo.owner_id == current_user.id)
        .first()
    )
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


@router.patch("/{todo_id}", response_model=TodoOut)
def patch_todo(
    todo_id: int,
    patch: TodoPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """JSON Merge Patch (RFC 7396) — 부분 필드만 업데이트."""
    todo = (
        db.query(Todo)
        .filter(Todo.id == todo_id, Todo.owner_id == current_user.id)
        .first()
    )
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")

    update_data = patch.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(todo, field, value)
    db.commit()
    db.refresh(todo)
    return todo


@router.delete("/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(
    todo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    todo = (
        db.query(Todo)
        .filter(Todo.id == todo_id, Todo.owner_id == current_user.id)
        .first()
    )
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    db.delete(todo)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
