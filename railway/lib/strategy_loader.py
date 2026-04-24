"""
Dynamic strategy from DB — same entry rules as engine (Strategy / on_tick / etc.).
Code is stored on public.bots (content column).
"""
from __future__ import annotations

import inspect
import json
import logging
import os
from typing import Any

from supabase import Client

logger = logging.getLogger(__name__)


def _trace(msg: str) -> None:
    logger.info("[strategy] %s", msg)


class _OnTickFnAdapter:
    __slots__ = ("_fn",)

    def __init__(self, fn):
        self._fn = fn

    def on_tick(self, market_data):
        return self._fn(market_data)


def _strategy_from_exec_locals(local_context: dict, params: dict) -> tuple[object | None, str | None]:
    explicit = os.getenv("STRATEGY_CLASS_NAME", "").strip()
    if explicit and explicit in local_context:
        obj = local_context[explicit]
        if isinstance(obj, type) and callable(getattr(obj, "on_tick", None)):
            return obj(params), None
        if not isinstance(obj, type) and callable(getattr(obj, "on_tick", None)):
            return obj, None

    for key in ("strategy", "bot", "runner"):
        obj = local_context.get(key)
        if obj is None or isinstance(obj, type):
            continue
        if callable(getattr(obj, "on_tick", None)):
            return obj, None

    st = local_context.get("Strategy")
    if isinstance(st, type) and callable(getattr(st, "on_tick", None)):
        return st(params), None

    fn = local_context.get("on_tick")
    if fn is not None and callable(fn) and not isinstance(fn, type):
        if inspect.isroutine(fn) or inspect.isfunction(fn):
            return _OnTickFnAdapter(fn), None

    bad = (
        "matplotlib",
        "numpy",
        "pandas",
        "PIL",
        "sklearn",
        "scipy",
        "typing",
        "collections.",
        "ccxt",
        "supabase",
    )
    cands: list[tuple[str, type]] = []
    for name, obj in local_context.items():
        if name.startswith("_") or not isinstance(obj, type):
            continue
        if not callable(getattr(obj, "on_tick", None)):
            continue
        mod = getattr(obj, "__module__", "") or ""
        if any(mod.startswith(p) for p in bad):
            continue
        cands.append((name, obj))

    if len(cands) == 1:
        return cands[0][1](params), None
    for name, cls in cands:
        if name.lower() == "strategy":
            return cls(params), None
    if len(cands) > 1:
        names = [n for n, _ in cands]
        return None, f"multiple on_tick classes {names}; set STRATEGY_CLASS_NAME or class Strategy"
    tnames = sorted(k for k, v in local_context.items() if isinstance(v, type))[:40]
    return None, f"no Strategy or on_tick; types={tnames}"


def _coerce_params(raw: Any) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    return {}


def compile_code_to_instance(code: str, params: dict) -> tuple[object | None, str | None]:
    try:
        # Single mapping: class bodies + methods must see module-level names (constants,
        # helpers). exec(code, {}, locals) leaves globals empty so Strategy.__init__ misses BASE_TF.
        local_context: dict[str, Any] = {}
        exec(code or "", local_context)
        return _strategy_from_exec_locals(local_context, params)
    except Exception as e:  # noqa: BLE001
        logger.exception("exec failed: %s", e)
        return None, str(e)


def load_strategy_from_db(
    supabase: Client, bot_id: str
) -> tuple[object | None, str | None]:
    """
    Load runnable strategy from bots.content for this bot_id.
    Returns (instance, error).
    """
    try:
        br = (
            supabase.table("bots")
            .select("id, params, content")
            .eq("id", bot_id)
            .single()
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        return None, f"bot query: {e}"
    if not br.data:
        return None, "bot not found"
    row = br.data
    params = _coerce_params(row.get("params"))
    code = row.get("content") or ""
    if not str(code).strip():
        return None, "bot has empty content"
    inst, err = compile_code_to_instance(code, params)
    return inst, err
