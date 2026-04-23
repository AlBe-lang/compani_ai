"""Unit tests for EmbeddingPreset + QdrantStorage dimension reconciliation —
Part 8 Stage 1 (R-05B/C)."""

from __future__ import annotations

import pytest

from adapters.qdrant_storage import _QDRANT_AVAILABLE, QdrantStorage
from application.agent_factory import EmbeddingPreset, SystemConfig, preset_vector_size

pytestmark = pytest.mark.skipif(
    not _QDRANT_AVAILABLE, reason="qdrant-client[fastembed] not installed"
)


def test_preset_values_stable() -> None:
    """Enum string values must not change — they map to HuggingFace model ids
    and breaking them invalidates previously-saved vectors."""
    assert (
        EmbeddingPreset.MINILM_FAST.value
        == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert (
        EmbeddingPreset.MPNET_BALANCED.value
        == "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    )
    assert EmbeddingPreset.E5_BEST.value == "intfloat/multilingual-e5-large"


def test_preset_vector_size_mapping() -> None:
    assert preset_vector_size(EmbeddingPreset.MINILM_FAST) == 384
    assert preset_vector_size(EmbeddingPreset.MPNET_BALANCED) == 768
    assert preset_vector_size(EmbeddingPreset.E5_BEST) == 1024


def test_system_config_default_preset() -> None:
    """Stage 1 default is MPNET_BALANCED per Q3 decision."""
    cfg = SystemConfig()
    assert cfg.embedding_preset is EmbeddingPreset.MPNET_BALANCED
    assert cfg.allow_embedding_collection_recreate is True


async def test_qdrant_uses_correct_size_for_minilm() -> None:
    q = QdrantStorage(path=":memory:", embedding_model=EmbeddingPreset.MINILM_FAST.value)
    await q.init()
    assert q.vector_size == 384
    assert q.embedding_model == EmbeddingPreset.MINILM_FAST.value


async def test_qdrant_uses_correct_size_for_mpnet() -> None:
    q = QdrantStorage(path=":memory:", embedding_model=EmbeddingPreset.MPNET_BALANCED.value)
    await q.init()
    assert q.vector_size == 768


async def test_qdrant_recreates_collection_on_dimension_mismatch() -> None:
    """Switching MiniLM(384) → mpnet(768) must recreate collections. Since
    Qdrant's local mode doesn't allow two instances sharing a path, we use
    :memory: and verify the recreation path via direct client inspection.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1st init with MiniLM
        q1 = QdrantStorage(path=tmpdir, embedding_model=EmbeddingPreset.MINILM_FAST.value)
        await q1.init()
        assert q1.vector_size == 384
        await q1.close()

        # 2nd init with mpnet on same path → should trigger recreate (allow_recreate default True)
        q2 = QdrantStorage(path=tmpdir, embedding_model=EmbeddingPreset.MPNET_BALANCED.value)
        await q2.init()
        assert q2.vector_size == 768
        assert q2._get_collection_vector_size("qa_history") == 768
        await q2.close()


async def test_qdrant_refuses_recreate_when_disabled() -> None:
    """allow_recreate=False must raise a clear error instead of silently dropping data."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        q1 = QdrantStorage(
            path=tmpdir,
            embedding_model=EmbeddingPreset.MINILM_FAST.value,
        )
        await q1.init()
        await q1.close()

        q2 = QdrantStorage(
            path=tmpdir,
            embedding_model=EmbeddingPreset.MPNET_BALANCED.value,
            allow_recreate=False,
        )
        with pytest.raises(RuntimeError, match="vector size"):
            await q2.init()
