"""HTTP REST endpoints — Part 8 Stage 2 + v1.1 demo entry.

Routes:
  GET   /api/run/current    — current run snapshot (partial)
  POST  /api/run            — start a pipeline subprocess (v1.1 demo)
  POST  /api/cancel         — terminate the running pipeline (v1.1 demo)
  GET   /api/run/stream     — Server-Sent Events stream of stderr lines
  GET   /api/agents/dna     — every known AgentDNA
  GET   /api/metrics        — current RunSummary
  GET   /api/config         — SystemConfig with reload metadata
  PATCH /api/config         — mutate one field (with classification + confirm)
  GET   /api/environment    — memory / E5 gate info (R-10F)
  GET   /api/output/download — pipeline 산출물 ZIP 다운로드 (v1.1 demo)
  GET   /api/output/tree     — 산출물 디렉토리 트리 JSON
  GET   /api/output/file     — 단일 파일 텍스트 미리보기

All endpoints require token auth (see auth.verify_http). WebSocket lives in
websocket.py so this module stays pure REST.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel

from observability.logger import get_logger

from .auth import verify_http
from .config_mutation import ConfigMutationError, ReloadCategory, apply_mutation, serialise_config
from .snapshot import environment_snapshot

OUTPUTS_ROOT = Path("outputs")
# 산출물 미리보기 최대 크기 (1MB) — 큰 binary 가 메모리 폭주하지 않게
_MAX_PREVIEW_BYTES = 1_000_000

if TYPE_CHECKING:
    from .app import DashboardDeps

log = get_logger(__name__)


class ConfigPatchRequest(BaseModel):
    """Single-field mutation payload. ``confirm`` must be True for destructive fields."""

    field: str
    value: Any
    confirm: bool = False


class ConfigPatchResponse(BaseModel):
    field: str
    new_value: Any
    category: str
    message: str


class RunStartRequest(BaseModel):
    """v1.1 demo run payload — natural-language project request.

    ``mock`` 이 True 면 RunManager 가 ``main.py`` 대신
    ``scripts/mock_pipeline.py`` 를 spawn — 시연 안전 모드 (Ollama 불필요,
    ~38초 안에 완전한 파이프라인 시각화). 기본은 False (실제 LLM 호출).
    """

    request: str
    mock: bool = False


def create_router(deps: "DashboardDeps") -> APIRouter:
    router = APIRouter(prefix="/api")

    def _auth(request: Request) -> None:
        verify_http(request, deps.auth_token)

    # ----- GET /api/run/current --------------------------------------
    @router.get("/run/current", dependencies=[Depends(_auth)])
    async def get_current_run() -> dict[str, Any]:
        workitem_count = len(getattr(deps.workspace, "_cache", {})) if deps.workspace else 0
        return {
            "run_id": deps.config.run_id,
            "workitem_count": workitem_count,
            "config_summary": {
                "cto_model": deps.config.cto_model,
                "slm_model": deps.config.slm_model,
                "mlops_model": deps.config.mlops_model,
                "embedding_preset": deps.config.embedding_preset.value,
            },
        }

    # ----- GET /api/agents/dna ---------------------------------------
    @router.get("/agents/dna", dependencies=[Depends(_auth)])
    async def get_all_dna() -> list[dict[str, Any]]:
        if deps.dna_manager is None:
            return []
        cache = getattr(deps.dna_manager, "_cache", {})
        return [
            {
                "agent_id": agent_id,
                "role": dna.role,
                "success_rate": dna.success_rate,
                "avg_duration": dna.avg_duration,
                "total_tasks": dna.total_tasks,
                "genes": dict(dna.genes),
                "meeting_participation_count": dna.meeting_participation_count,
                "review_count": dna.review_count,
            }
            for agent_id, dna in cache.items()
        ]

    # ----- GET /api/metrics ------------------------------------------
    @router.get("/metrics", dependencies=[Depends(_auth)])
    async def get_metrics() -> dict[str, Any]:
        if deps.metrics is None:
            return {"available": False}
        deps.metrics.sample_memory(deps.config.run_id)
        summary = deps.metrics.get_run_summary(deps.config.run_id)
        return {
            "available": True,
            "run_id": summary.run_id,
            "total_tasks": summary.total_tasks,
            "success_count": summary.success_count,
            "fail_count": summary.fail_count,
            "avg_duration_sec": summary.avg_duration_sec,
            "total_retries": summary.total_retries,
            "fallback_count": summary.fallback_count,
            "memory_peak_gb": summary.memory_peak_gb,
        }

    # ----- GET /api/config -------------------------------------------
    @router.get("/config", dependencies=[Depends(_auth)])
    async def get_config() -> dict[str, Any]:
        return serialise_config(deps.config)

    # ----- PATCH /api/config -----------------------------------------
    @router.patch("/config", dependencies=[Depends(_auth)])
    async def patch_config(payload: ConfigPatchRequest) -> ConfigPatchResponse:
        try:
            category = apply_mutation(
                deps.config,
                field_name=payload.field,
                new_value=payload.value,
                confirm=payload.confirm,
            )
        except ConfigMutationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        # Propagate to the LLMConcurrencyLimiter when the field is one of its
        # live-tunable slots. Other hot-reloadable fields are already read from
        # config on-demand by their owning component.
        if category is ReloadCategory.HOT_RELOADABLE and payload.field.startswith(
            "llm_concurrency_"
        ):
            if deps.limiter is not None:
                deps.limiter.update_limits(
                    cto=deps.config.llm_concurrency_cto,
                    slm=deps.config.llm_concurrency_slm,
                    mlops=deps.config.llm_concurrency_mlops,
                    total=deps.config.llm_concurrency_total,
                )

        return ConfigPatchResponse(
            field=payload.field,
            new_value=getattr(deps.config, payload.field),
            category=category.value,
            message=_mutation_message(category),
        )

    # ----- GET /api/environment --------------------------------------
    @router.get("/environment", dependencies=[Depends(_auth)])
    async def get_environment() -> dict[str, Any]:
        return environment_snapshot(deps.config)

    # ----- POST /api/run ---------------------------------------------
    # v1.1 demo entry. RunManager 가 None 이면 503 — pipeline-disabled 모드.
    @router.post("/run", dependencies=[Depends(_auth)])
    async def post_run(payload: RunStartRequest) -> dict[str, Any]:
        if deps.run_manager is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="run manager not configured",
            )
        if not payload.request.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="request must not be empty",
            )
        try:
            state = await deps.run_manager.start(payload.request, mock=payload.mock)
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return {
            "run_id": state.run_id,
            "pid": state.pid,
            "started_at": state.started_at,
            "mock": payload.mock,
        }

    # ----- POST /api/cancel ------------------------------------------
    @router.post("/cancel", dependencies=[Depends(_auth)])
    async def post_cancel() -> dict[str, Any]:
        if deps.run_manager is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="run manager not configured",
            )
        cancelled = await deps.run_manager.cancel()
        return {"cancelled": cancelled}

    # ----- GET /api/run/stream (SSE) ---------------------------------
    # 인증은 헤더 대신 ``?token=`` 쿼리만 — EventSource 가 헤더를 못 보내기 때문.
    # ``verify_http`` 가 query fallback 을 이미 지원하므로 동일 헬퍼 사용.
    @router.get("/run/stream")
    async def get_run_stream(request: Request) -> StreamingResponse:
        verify_http(request, deps.auth_token)
        if deps.run_manager is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="run manager not configured",
            )
        return StreamingResponse(
            deps.run_manager.stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # ----- GET /api/output/download ---------------------------------
    # outputs/<slug>/ 를 ZIP 으로 압축해 반환. EventSource 와 마찬가지로
    # 인증은 ``?token=`` 쿼리 fallback 사용 (브라우저 다운로드는 헤더 못 줌).
    @router.get("/output/download")
    async def get_output_download(request: Request, slug: str = Query(...)) -> Response:
        verify_http(request, deps.auth_token)
        target = _resolve_output_dir(slug)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(target.rglob("*")):
                if f.is_file():
                    arcname = str(Path(slug) / f.relative_to(target))
                    zf.write(f, arcname=arcname)
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
        )

    # ----- GET /api/output/tree -------------------------------------
    @router.get("/output/tree", dependencies=[Depends(_auth)])
    async def get_output_tree(slug: str = Query(...)) -> dict[str, Any]:
        target = _resolve_output_dir(slug)
        return _build_tree(target, target)

    # ----- GET /api/output/file -------------------------------------
    # 단일 파일 텍스트 반환 (미리보기). binary 는 첫 N 바이트만 + 표시.
    @router.get("/output/file")
    async def get_output_file(
        request: Request,
        slug: str = Query(...),
        path: str = Query(...),
    ) -> PlainTextResponse:
        verify_http(request, deps.auth_token)
        target = _resolve_output_dir(slug)
        # path traversal 방어 — 정규화 후 target 내부인지 확인
        resolved = (target / path).resolve()
        if not str(resolved).startswith(str(target.resolve())):
            raise HTTPException(status_code=400, detail="invalid path")
        if not resolved.is_file():
            raise HTTPException(status_code=404, detail="file not found")
        size = resolved.stat().st_size
        if size > _MAX_PREVIEW_BYTES:
            return PlainTextResponse(
                f"<file too large: {size} bytes — preview disabled. "
                f"Use download endpoint for full content.>",
                status_code=200,
            )
        try:
            text = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return PlainTextResponse(
                f"<binary file: {size} bytes — text preview not available.>",
                status_code=200,
            )
        return PlainTextResponse(text)

    return router


def _mutation_message(category: ReloadCategory) -> str:
    if category is ReloadCategory.HOT_RELOADABLE:
        return "즉시 적용되었습니다."
    if category is ReloadCategory.RESTART_REQUIRED:
        return "다음 프로젝트 실행부터 적용됩니다."
    return "파괴적 변경이 적용됐습니다. 컬렉션이 재생성됩니다."


def _resolve_output_dir(slug: str) -> Path:
    """slug 검증 후 outputs/<slug>/ 경로 반환. path traversal / 비존재 가드."""
    if "/" in slug or ".." in slug or not slug.strip():
        raise HTTPException(status_code=400, detail="invalid slug")
    target = (OUTPUTS_ROOT / slug).resolve()
    root = OUTPUTS_ROOT.resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=400, detail="invalid slug path")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"output not found: {slug}")
    return target


def _build_tree(root: Path, current: Path) -> dict[str, Any]:
    """디렉토리 → 트리 JSON 변환. file 은 size 포함, dir 은 children 재귀."""
    rel = str(current.relative_to(root)) if current != root else ""
    if current.is_file():
        return {
            "name": current.name,
            "path": rel,
            "type": "file",
            "size": current.stat().st_size,
        }
    children = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    return {
        "name": current.name if rel else "",
        "path": rel,
        "type": "dir",
        "children": [_build_tree(root, c) for c in children],
    }
