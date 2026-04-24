"""Supabase from env (same key resolution style as engine)."""
from __future__ import annotations

import os
from supabase import Client, create_client


def _resolve_env(*keys: str) -> str:
    for k in keys:
        v = os.getenv(k)
        if v and str(v).strip():
            return v.strip()
    raise RuntimeError(f"missing env, tried: {', '.join(keys)}")


def _url() -> str:
    return _resolve_env("SUPABASE_URL", "VITE_SUPABASE_URL")


def _anon_key() -> str:
    return _resolve_env("SUPABASE_ANON_KEY", "VITE_SUPABASE_ANON_KEY", "SUPABASE_KEY")


def _service_key() -> str:
    return _resolve_env("SUPABASE_SERVICE_ROLE_KEY", "VITE_SUPABASE_SERVICE_ROLE_KEY")


def make_supabase_for_worker() -> Client:
    return create_client(_url(), _anon_key())


def make_supabase_for_hub() -> Client:
    return create_client(_url(), _service_key())
