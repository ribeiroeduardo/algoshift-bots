"""Blocking Redis — pub/sub, publish, idempotency cache (Hub)."""
from __future__ import annotations

import os

import redis


def _redis_url() -> str:
    url = os.getenv("REDIS_URL")
    if not url or not str(url).strip():
        raise RuntimeError("missing REDIS_URL: set on Railway (Redis addon)")
    return str(url).strip()


def make_redis_client() -> redis.Redis:
    client = redis.Redis.from_url(
        _redis_url(),
        decode_responses=True,
        socket_keepalive=True,
        socket_timeout=5,
        retry_on_timeout=True,
        health_check_interval=30,
    )
    client.ping()
    return client
