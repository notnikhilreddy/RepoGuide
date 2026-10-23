"""Central MLflow/OpenTelemetry-compatible observability.

MLflow spans are distinct from MLflow Runs. Never put bearer tokens, passwords,
connection strings, or user-private content into traces unintentionally.
"""
from __future__ import annotations

import logging
import re
import time
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)
_SECRET = re.compile(r'(?i)(api[_-]?key|authorization|password|secret|access[_-]?token|refresh[_-]?token|private[_-]?key|database[_-]?url|^token$)')
_INLINE_SECRET = re.compile(r'(?i)(Bearer\s+[A-Za-z0-9._-]{12,}|postgresql(?:\+\w+)?://\S+|sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9_]{16,})')


def safe(value: Any, *, content: bool = False, depth: int = 0):
    """Bound trace payload sizes; never serialize credentials as attributes."""
    if depth > 4:
        return '<depth-limited>'
    if isinstance(value, dict):
        return {str(k)[:80]: ('[REDACTED]' if _SECRET.search(str(k)) else safe(v, content=content, depth=depth + 1)) for k, v in list(value.items())[:35]}
    if isinstance(value, (list, tuple)):
        return [safe(v, content=content, depth=depth + 1) for v in list(value)[:20]]
    if isinstance(value, str):
        cleaned = _INLINE_SECRET.sub('[REDACTED]', value)
        return cleaned[:12000] if content else {'length': len(value), 'preview': cleaned[:80]}
    if isinstance(value, (int, float, bool, type(None))):
        return value
    return {'type': type(value).__name__}


def safe_attr(key: str, value: Any):
    """Keep short primitive metadata readable, summarize long arbitrary payloads."""
    if isinstance(value, str) and len(value) <= 200 and not _INLINE_SECRET.search(value) and not _SECRET.search(str(key)):
        return value
    return safe(value, content=False)


@lru_cache(maxsize=1)
def setup_mlflow() -> bool:
    from repoguide.config import settings
    if not settings.mlflow_enabled:
        return False
    try:
        import mlflow
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment)
        # Autolog can store complete prompts/completions. Only opt in locally or
        # for sanitized corpora; custom spans still work without SDK autolog.
        if settings.mlflow_autolog and settings.mlflow_capture_content:
            for integration in ('langchain', 'openai', 'gemini'):
                try:
                    getattr(mlflow, integration).autolog()
                except Exception as exc:
                    logger.warning('MLflow %s autolog unavailable: %s', integration, type(exc).__name__)
        return True
    except Exception as exc:
        logger.warning('MLflow setup unavailable: %s', type(exc).__name__)
        return False


@contextmanager
def span(name: str, kind: str = 'CHAIN', inputs: dict | None = None, attributes: dict | None = None):
    """Capture nested spans and timings; instrumentation must not break requests."""
    from repoguide.config import settings
    begin = time.perf_counter()
    if not setup_mlflow():
        yield None
        return
    import mlflow
    context = mlflow.start_span(name=name, span_type=kind)
    with context as active:
        active.set_inputs(safe(inputs or {}, content=settings.mlflow_capture_content))
        for key, val in (attributes or {}).items():
            active.set_attribute(str(key), safe_attr(key, val))
        try:
            yield active
        except Exception as exc:
            active.set_attribute('error.type', type(exc).__name__)
            raise
        finally:
            active.set_attribute('duration_ms', round((time.perf_counter() - begin) * 1000, 2))


def record(active, outputs: Any = None, **attributes):
    if active is None:
        return
    from repoguide.config import settings
    if outputs is not None:
        active.set_outputs(safe(outputs, content=settings.mlflow_capture_content))
    for k, value in attributes.items():
        active.set_attribute(str(k), safe_attr(k, value))


def feedback(trace_id: str, name: str, value: Any, rationale: str = '', human: bool = False) -> bool:
    if not setup_mlflow():
        return False
    import mlflow
    from mlflow.entities import AssessmentSource, AssessmentSourceType
    mlflow.log_feedback(
        trace_id=trace_id, name=name, value=value, rationale=rationale[:1000],
        source=AssessmentSource(
            source_type=AssessmentSourceType.HUMAN if human else AssessmentSourceType.CODE,
            source_id='repoguide_feedback_api' if human else 'repoguide_checks_v1',
        ),
    )
    return True


def observed(name: str, kind: str = 'CHAIN'):
    """Low-friction instrumentation of code paths; previews only by default."""
    import functools
    import inspect
    def wrap(fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_call(*args, **kwargs):
                with span(name,kind,{'args':args,'kwargs':kwargs}) as sp:
                    result=await fn(*args,**kwargs)
                    record(sp, result)
                    return result
            return async_call
        @functools.wraps(fn)
        def call(*args,**kwargs):
            with span(name,kind,{'args':args,'kwargs':kwargs}) as sp:
                result=fn(*args,**kwargs)
                record(sp,result)
                return result
        return call
    return wrap
