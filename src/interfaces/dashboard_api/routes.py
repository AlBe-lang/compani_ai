"""HTTP REST endpoints — Part 8 Stage 2.

Routes:
  GET  /api/run/current    — current run snapshot (partial)
  GET  /api/agents/dna     — every known AgentDNA
  GET  /api/metrics        — current RunSummary
  GET  /api/config         — SystemConfig with reload metadata
  PATCH /api/config        — mutate one field (with classification + confirm)
  GET  /api/environment    — memory / E5 gate info (R-10F)

All endpoints require token auth (see auth.verify_http). WebSocket lives in
websocket.py so this module stays pure REST.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from observability.logger import get_logger

from .auth import verify_http
from .config_mutation import ConfigMutationError, ReloadCategory, apply_mutation, serialise_config
from .snapshot import environment_snapshot

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

    return router


def _mutation_message(category: ReloadCategory) -> str:
    if category is ReloadCategory.HOT_RELOADABLE:
        return "즉시 적용되었습니다."
    if category is ReloadCategory.RESTART_REQUIRED:
        return "다음 프로젝트 실행부터 적용됩니다."
    return "파괴적 변경이 적용됐습니다. 컬렉션이 재생성됩니다."
