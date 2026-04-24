# Step-by-step: test each phase (distributed engine)

All commands assume **repo root** as current directory (`cd /path/to/algoshift-bots`).

**Global prep**

1. Install **Python 3.11+** (matches Railway) and `pip install -r requirements.txt` from the repo root.
2. Install **Node** deps: `npm install`.
3. **Supabase CLI** installed; for local DB: `supabase start` or use **remote** project with `supabase link`.
4. **Redis (hosted).** This guide assumes **Option C** — a **managed Redis** URL (`REDIS_URL`) from Railway, Upstash, or similar. Same URL is used for Hub, Worker, and local Phase 1 tests. No local `redis-server` required.

**Env pattern for Python** (macOS/Linux):

```bash
export PYTHONPATH=.
```

Windows (PowerShell): `$env:PYTHONPATH="."`

---

## Phase 0 — Database, seed, TypeScript

**Goal:** Migrations apply; `bots` / `bot_heartbeats` / `trades` exist; seed optional; frontend types build.

### Steps

1. **Apply migrations**
   - Local (resets DB + runs seeds):  
     `supabase db reset`  
   - Or push to linked remote only:  
     `supabase db push`
2. **Verify tables** (Supabase SQL editor or `psql`):

   ```sql
   select table_name
   from information_schema.tables
   where table_schema = 'public'
     and table_name in ('bots', 'bot_heartbeats', 'trades');
   ```

3. **Check idempotency index** (Postgres):

   ```sql
   select indexname from pg_indexes
   where tablename = 'trades' and indexname = 'uniq_trades_signal_id';
   ```

4. **Seed bot** (optional): after `db reset`, if you have at least one `strategies` row, the seed inserts the test bot `00000000-0000-0000-0000-000000000001` (stopped, with placeholder `content`):

   ```sql
   select id, name, status, trading_pair from public.bots;
   ```

5. **Front build** (types + app):  
   `npm run build`  
   Pass = no TypeScript/build errors.

**Pass/fail:** No SQL errors; `npm run build` succeeds; tables and (if data exists) seed row visible.

---

## Phase 1 — Redis ping-pong (`hub_v1` + `worker_v1`)

**Goal:** Hub publishes mock ticks; worker receives; worker sends mock `order_signals`; hub logs them. No Bybit, no Supabase.

**Default: hosted Redis (Option C)** — no Docker, no local `redis-server`. You only need a **`REDIS_URL`** string that both processes can reach over the network.

### 1.1 — Create hosted Redis and get `REDIS_URL`

**Railway (matches production later)**

1. Open your Railway project → **New** → **Database** → **Add Redis** (or **Redis** from the template list).
2. After it provisions, open the Redis service → **Variables** (or **Connect**).
3. Copy **`REDIS_URL`** (often `redis://default:...@...railway.internal:6379` on the private network, or a public URL if the provider shows one).
4. For **testing from your laptop** (outside Railway’s private network), use the **public** / **external** connection string if Railway exposes it, or use **Upstash** below for local dev — or run Phase 1 **inside** a one-off Railway shell with the internal URL.

**Upstash (good for local dev from your machine)**

1. [Upstash](https://upstash.com) → create a Redis database (region near you).
2. Copy the **REST** URL is not what you need — copy the **Redis** connection string (`rediss://` with password).
3. `export REDIS_URL='rediss://default:...@...upstash.io:6379'`

**Rule:** the **same** `REDIS_URL` value must be set in **Terminal A**, **Terminal B**, and later in Hub + Worker env (Railway Variables).

**Test connectivity (optional):** if you have `redis-cli`:

```bash
redis-cli -u "$REDIS_URL" --tls ping
# If non-TLS (redis://...):
redis-cli -u "$REDIS_URL" ping
```

Expect: `PONG` (or provider-specific success). Some `rediss://` endpoints require `--tls` with `redis-cli`.

### 1.2 — Run the mocks (two terminals)

Set your URL once per shell (replace with your real value):

```bash
export REDIS_URL='your-url-here'   # paste from Railway or Upstash — quote if it has special chars
export PYTHONPATH=.
```

**Terminal A — hub mock**

```bash
export PYTHONPATH=.
export REDIS_URL='your-url-here'
python -m railway.hub_v1
```

Expect: `published tick` ~every 2s; `subscribed order_signals`.

**Terminal B — worker mock**

```bash
export PYTHONPATH=.
export REDIS_URL='your-url-here'
python -m railway.worker_v1
```

Expect: `tick#...`; every 5th tick a BUY; Terminal A shows `SIGNAL: {...}` JSON.

### 1.3 — Extra checks

1. **Fail-fast:** unset `REDIS_URL` and run `python -m railway.hub_v1` — should exit with a clear missing-URL error.
2. **Resilience:** stop Terminal B; Terminal A should keep printing ticks.

**Pass/fail:** Ticks + signals in both logs; missing `REDIS_URL` fails fast; hub keeps running after worker is killed.

### Alternatives (if you *don’t* use hosted Redis)

| Option | What |
|--------|------|
| **A — Homebrew (macOS)** | `brew install redis` → `redis-server` → `REDIS_URL=redis://127.0.0.1:6379/0` |
| **B — Linux** | `apt`/`dnf` install `redis-server` → `REDIS_URL=redis://127.0.0.1:6379/0` |
| **D — Docker** | `docker run -p 6379:6379 redis:7` → same `127.0.0.1` URL as A/B |

---

## Phase 2 — Real Hub (Bybit → Redis, no order execution from worker)

**Goal:** `railway.hub` watches live tickers for every **running** bot pair and publishes `market_data:{pair}`. You can **listen with Redis** or run the real worker in “signal only” mode and watch logs (full strategy is Phase 3).

### Steps

1. **Env (Hub)** — set at least (use the **same** hosted `REDIS_URL` as workers / Phase 1):

   - `REDIS_URL`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY` (Hub uses service role)
   - `BYBIT_API_KEY` / `BYBIT_API_SECRET` (many setups need keys even for public WS; if errors, add keys)
   - **Bybit environment (pick one):** `BYBIT_USE_TESTNET=true` for [testnet](https://testnet.bybit.com) keys only. **`BYBIT_USE_DEMO=true`** for [Demo Trading](https://bybit-exchange.github.io/docs/v5/demo) API keys (`api-demo.*`); leave `BYBIT_USE_TESTNET` unset. Demo ≠ testnet — wrong flag → signature errors (`retCode` 10004).

2. **Database:** one row in `bots` with `trading_pair` (e.g. `BTC/USDT`), non-empty `content`, and `status = 'running'`.

3. **Run Hub** (from repo root):

   ```bash
   export PYTHONPATH=.
   python -m railway.hub
   ```

4. **Expect in logs:** `started watcher BTC/USDT` (or your pair), no repeated tracebacks. Optional: use `redis-cli SUBSCRIBE "market_data:BTC/USDT"` to see JSON messages.

5. **Stop feed:** set the same bot to `status = 'stopped'` in SQL or dashboard; within ~10–20s expect `stopped watcher` for that pair.

6. **Two pairs:** two running bots, different `trading_pair` values — two channels, no cross-talk in Redis.

**Pass/fail:** Watcher starts after bot is `running`; stops after `stopped`; prices plausible vs Bybit UI (spot).

---

## Phase 3 — Real Worker (strategy, signals; Hub may still not execute if you use `hub_v1`)

**Goal:** `BOT_ID` worker loads strategy from Supabase, consumes `market_data:{pair}`, runs `on_tick`, publishes `order_signals`, writes `bot_heartbeats`, respects `hub:status` and `paused` / `running`.

**Typical setup:** run **real** `railway.hub` (Phase 2) so ticks are live; Worker does not need Bybit keys.

### Steps

1. **Env (Worker):**

   - `BOT_ID` = UUID of a `bots` row
   - `REDIS_URL` (same Redis as Hub)
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY` (no service key on workers)
   - Optional: `BYBIT_API_KEY` / `BYBIT_API_SECRET` (+ `BYBIT_USE_DEMO` or `BYBIT_USE_TESTNET` like Hub) so the worker can inject **live quote balance** into `market_data.account_equity` for sizing
   - Optional: `STRATEGY_CLASS_NAME` if the code uses a nonstandard class name

2. **DB:** that bot: `status = 'running'`, non-empty `content` (python) defining `Strategy` + `on_tick` (or `def on_tick`). Signal size comes from the strategy (`signal_amount` / `order_size` / `amount` / `size` attribute or `get_signal_amount()`), with optional fallback in `params`. Optional hub caps in `params`: `max_order_size`, `max_notional_usd`, `max_open_positions`.

3. **Run Worker:**

   ```bash
   export PYTHONPATH=.
   python -m railway.worker
   ```

4. **Check:** logs show ticks; `bot_heartbeats` row updates in Supabase every ~15s; after strategy returns a signal, Redis `order_signals` (and Hub logs if Hub is the real one with consumer).

5. **Status `stopped` / `error`:** `update bots set status = 'stopped' where id = '<BOT_ID>'` — worker **stays up** (no ticks/signals until `running` again). **`error`** still exits worker within a few seconds after reload sees it.

6. **Status `paused`:** process **keeps running** but should not emit new signals (while not `running`).

7. **Bad strategy code:** strategy raises → `bots.status = 'error'`, `last_error` set, worker exits.

**Pass/fail:** Heartbeat rows; stop/error exits; pause does not exit; live strategy change reloaded within polling window (~5s loop).

---

## Phase 4 — End-to-end execution (real Hub consumes `order_signals`)

**Goal:** Same as production: Worker emits valid signal → Hub dedupes, checks risk + balance, places order **on Bybit** → row in `trades`. **Use the Bybit [Demo Trading](https://bybit-exchange.github.io/docs/v5/demo) account first** (virtual balance, `api-demo.*` keys, `BYBIT_USE_DEMO=true`); that matches the usual path from Phases 2–3. [Testnet](https://testnet.bybit.com) is an alternative for a separate set of keys (`BYBIT_USE_TESTNET=true`); Demo ≠ testnet — wrong flag → signature errors (`retCode` 10004).

### Steps

1. Run **real** Hub (`python -m railway.hub`) with the same `REDIS_URL` and service-role Supabase, plus Bybit creds for the environment you chose:
   - **Demo (recommended for first live execution):** [Demo](https://www.bybit.com/app/user/api-management) / `api-demo.*` keys, **`BYBIT_USE_DEMO=true`**, and leave `BYBIT_USE_TESTNET` unset.
   - **Testnet (optional):** testnet keys, **`BYBIT_USE_TESTNET=true`**, and leave `BYBIT_USE_DEMO` unset.

2. Run **real** Worker (Phase 3 env). If you use optional Bybit keys on the worker for **balance** sizing, match the Hub’s Demo vs testnet flags and keys. Set `params.signal_amount` and a strategy that occasionally returns `BUY` (or test with a one-off; avoid accidental size on a funded account).

3. **Dup test:** not easy without tooling; duplicate `signal_id` in Hub is ignored and logged (`duplicate signal ignored`).

4. **Risk tests:** send manual signals via `redis-cli` only if you understand the JSON (usually you rely on strategy). Hub enforces optional caps from `bots.params` when those keys are set.

5. **Verify:** Bybit **Demo** (or testnet) “open orders / trades” in the UI for the same environment, and:

   ```sql
   select signal_id, status, preco_entrada, exchange_order_id
   from public.trades
   where bot_id = '<BOT_ID>'
   order by created_at desc
   limit 5;
   ```

**Pass/fail:** No duplicate `signal_id` in DB; rejected cases logged; Demo (or testnet) order visible in the matching Bybit environment; `trades` row with `status = 'OPEN'` for successful opens.

---

## Phase 5 — `hub:status`, Home UI, no monolith in deploy

**Goal:** If Hub is unhealthy (e.g. no tick >30s for a watched pair), `hub:status` shows `degraded` → Worker should **not** emit. Dashboard lists bots and controls.

### Steps

1. **Hub + Worker** both running. Watch Worker logs: when Hub publishes `degraded`, worker should log `hub:status` and stop emitting (strategy may still be called, but signal path is gated—see `worker` code).

2. **Simulate staleness:** stop the bot in DB so Hub drops the pair, or block network to Bybit and wait >30s — Hub should move to degraded; restore and confirm `healthy` again.

3. **App:** `npm run dev`, open Home with `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY` set — you should see bots, heartbeat, start/pause/stop, last open trade, `last_error` when `error`.

4. **Deploy check:** `railway.json` / `boot.sh` should run `python -m railway.hub`, not the old monolith, unless `ENGINE_MONOLITH=1`.

**Pass/fail:** UI updates; `hub:status` reflected in worker behavior; production start command = Hub.

---

## Quick command reference

| Phase | What to run |
|-------|-------------|
| 0 | `supabase db reset` → `npm run build` |
| 1 | `REDIS_URL` (hosted) → `python -m railway.hub_v1` + `python -m railway.worker_v1` |
| 2 | `python -m railway.hub` + DB `bots` running + same `REDIS_URL` |
| 3 | `python -m railway.worker` + same `REDIS_URL` + `BOT_ID` |
| 4 | Hub + Worker + Demo (or testnet); same `BYBIT_*` flags as Phase 2; check `trades` + Bybit |
| 5 | Hub + Worker + `npm run dev` Home page |

**Redis spy** (if `redis-cli` supports your URL; add `--tls` for `rediss://` as needed):

```bash
redis-cli -u "$REDIS_URL" SUBSCRIBE "market_data:BTC/USDT"
```

(Replace channel with your pair.)

For deeper **acceptance tables** (what “pass” means), see [PHASE_CRITERIA.md](PHASE_CRITERIA.md).
