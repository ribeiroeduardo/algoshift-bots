# Phase criteria — how to test each stage

**Step-by-step commands and order of operations:** [TESTING_PHASES.md](TESTING_PHASES.md)

## Trade time limit (max hold X minutes)

- **Backtest rule**: any open trade older than `X` minutes must close, profit or not.
- **In this system**: same logic belongs in **user strategy** (`on_tick`):
  - Store `entry_time` / position side in instance when you emit `BUY` / `SELL` (or when Hub confirms, if you only track after fill — for parity, usually strategy tracks "paper" state from your own signal, or you read from DB; simplest: internal state in `Strategy`).
  - On each tick: if position open and `elapsed >= X * 60s` → return `CLOSE_LONG` / `CLOSE_SHORT` (or opposite side) per your backtester.
- **Config**: use `bots.params` JSON (e.g. `max_trade_minutes: 15`) and read it in `__init__` — no Hub/Redis/DB change required.
- **Hub** does not auto-timer-exit; optional future: cron/Hub job reading `trades` — out of current scope.

---

## Phase 0 — Schema, seed, types

| # | Criterion (pass = true) | How to verify |
|---|-------------------------|---------------|
| 0.1 | Migrations apply on clean + existing project DB | `supabase db reset` (local) or `supabase db push` to staging; no SQL errors. |
| 0.2 | `public.bots`, `public.bot_heartbeats`, `bot_status` exist; `public.trades` created with new columns + partial unique on `signal_id` | `psql` or Supabase table editor: `\d+ public.bots` etc. |
| 0.3 | Seed inserts test bot (id `00000000-...001`) when at least one `strategy_version` is `active` | After apply: `select id, name, status from bots;` has row with that id or 0 rows if no active version (0 rows = OK, no crash). |
| 0.4 | TypeScript compiles with new `Database` tables | `npm run build` (or `tsc --noEmit` if in pipeline). |

---

## Phase 1 — Redis, mock Hub/Worker (ping-pong)

| # | Criterion | How to verify |
|---|-----------|---------------|
| 1.1 | Redis URL required; startup fails fast if missing | Unset `REDIS_URL` → `python -m railway.hub_v1` exits with clear error. |
| 1.2 | Hub publishes & Worker receives | `REDIS_URL` = hosted (Railway/Upstash) or local; same URL in both processes; Hub logs `published tick`; Worker logs `tick` at ~2s cadence. |
| 1.3 | Worker mock signal → Hub log | Every 5th tick, Hub log line shows mock signal / JSON. |
| 1.4 | Kill Worker, Hub still runs | Stop Worker; Hub still prints ticks. |

**Default setup:** hosted Redis — see [TESTING_PHASES.md](TESTING_PHASES.md) Phase 1.1. Local Homebrew/Docker-only Redis is optional.

---

## Phase 2 — Real Bybit → Redis (no order execution)

| # | Criterion | How to verify |
|---|-----------|---------------|
| 2.1 | `bots.status='running'` + pair → Hub starts `watch_ticker` and publishes to `market_data:{pair}` | Set bot running in DB; logs `started watcher`; message on Redis channel. |
| 2.2 | `status` → `stopped` → watcher stops within ~15s | `stopped watcher` in logs; no new ticks. |
| 2.3 | Ticker price near Bybit (spot) UI for same symbol | Compare last price ± tolerance (e.g. 0.5 on BTCUSDT). |
| 2.4 | No crash on missing optional ticker field | If exchange omits field, Hub still JSON payload (use `None` / skip field in JSON with default). |
| 2.5 | Two different pairs, two channels | Two bots running, two `market_data:...` channels, no cross-mix. |

**Needs**: `SUPABASE_*`, `BYBIT_*` (or read-only for public — spot ticker may work without keys on some paths; if Bybit needs keys, set in env).

---

## Phase 3 — Worker + `strategy_loader` (signals only, no execute)

| # | Criterion | How to verify |
|---|-----------|---------------|
| 3.1 | `BOT_ID` for running bot, Worker processes ticks in &lt;5s of start | Logs show ticks, `on_tick` runs. |
| 3.2 | `bots.content` update → recompile &lt;15s | Change code in Strategies UI / SQL; new behavior without redeploy. |
| 3.3 | `stopped` → worker stays up (no signals); `error` → exit ~5s | `UPDATE ... status='stopped'` logs idle; `status='error'` ends process. |
| 3.4 | `paused` does not exit process | `paused` → logs show no new signals, process still up. |
| 3.5 | `bot_heartbeats` row updates ~15s | `SELECT` heartbeat timestamps advancing. |
| 3.6 | `on_tick` returns BUY/SELL → `order_signals` on Redis; Hub (if v1 still logging) sees JSON | Grep signal_id in logs. |
| 3.7 | Strategy `exec` raises → `bots.status='error'`, `last_error` set, worker exit | Injected bad code, row updated. |

---

## Phase 4 — Hub executes, risk, `trades` row

| # | Criterion | How to verify |
|---|-----------|---------------|
| 4.1 | Duplicate `signal_id` | Publish same `signal_id` twice → one DB row, second "duplicate" log, no 2nd insert. |
| 4.2 | `amount` &gt; `params.max_order_size` (when set) | Rejected, log warning, no order. |
| 4.3 | Notional &gt; `params.max_notional_usd` (when set) | Rejected, no order. |
| 4.4 | `status='paused'` / not `running` | Signal ignored, log, no order. |
| 4.5 | Valid testnet order | `BYBIT_USE_TESTNET=true`; order in Bybit testnet UI. |
| 4.6 | Row in `trades` with `signal_id`, `status=OPEN` | `SELECT` after good signal. |
| 4.7 | API error (e.g. balance) | `status='error'` and `last_error` on bot, no duplicate trade. |
| 4.8 | Balance &lt; notional | Rejected, log (no mainnet test required for doc). |

---

## Phase 5 — `hub:status`, dashboard, monolith off

| # | Criterion | How to verify |
|---|-----------|---------------|
| 5.1 | Hub dead → `hub:status` (or worker’s view) shows degraded, worker stops new signals in &lt;5s of publish | Simulated WS stall / kill feed. |
| 5.2 | Hub healthy again → worker resumes | WS back; worker emits when strategy says so. |
| 5.3 | Home page lists bots, last heartbeat, status, `last_error` | Manual UI. |
| 5.4 | `engine.py` not used in deploy | `boot.sh` / `railway.json` point to `python -m railway.hub`, not `engine.py`. |

---

## Global “done” (before mainnet)

- See project checklist (7d testnet, heartbeats, duplicate signal audit, p95 latency, etc.).
