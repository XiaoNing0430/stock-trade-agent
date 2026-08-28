# AGENTS.md

Guidance for AI coding agents working in this repository.

## What This Is

**Atlas Trading Desk** — a local, single-user A-share (Chinese stock market) research & trading-desk web application. Real quote data drives a screener, trade plans, a price-trigger monitoring center, and grid-strategy backtesting. It is a **research tool, not an execution system**: it never connects to a broker and never sends orders.

UI copy is Chinese. Keep new user-facing strings in Chinese unless a task says otherwise.

## Tech Stack

- **Frontend:** Vue 3 (global build, `vue.global.prod.js`), no bundler, no npm build step. Served as static files by FastAPI.
- **Backend:** Python / FastAPI, SQLAlchemy 2.0 (PostgreSQL), Redis (reserved / status ping only), APScheduler (grid backtest scheduling), requests (external quote API).
- **Data source:** Tencent public quote API (`qt.gtimg.cn`, `web.ifzq.gtimg.cn`). Only data source currently integrated.
- **Config:** `.env` (git-ignored) sourced from `.env.example`.

## Project Layout

```
server.py                 Dev entrypoint — starts uvicorn on 127.0.0.1:4173
backend/
  app.py                  FastAPI app, all /api routes, serves frontend
  main.py                 python -m backend.main entrypoint
  data_source.py          Tencent quote API adapter + classification + fetch/retry
  grid_strategy.py        Grid math: build_grid, suggest_grid, backtest_grid, optimize_grid
  grid_scheduler.py       APScheduler wrappers for daily grid backtests (Asia/Shanghai)
  storage.py              SQLAlchemy models + persistence helpers (workspace, plans, alerts, grid)
  settings.py             pydantic-settings; env (POSTGRES_*, REDIS_*, TUSHARE_TOKEN, HTTP_TIMEOUT, HTTP_RETRY)
frontend/
  index.html              Vue template (single file, all views inline)
  app.js                  Vue app setup + all logic (~1200 lines, no build)
  styles.css              All styling (single file, CSS variables)
  vendor/                 Vendored vue.global.prod.js + lucide.min.js (no CDN)
tests/
  test_backend_api.py     FastAPI routes + data_source parsing
  test_grid_strategy.py   Grid math
  test_settings_api.py    Settings API + default settings assertions
  test_data_source_retry.py  HTTP retry/backoff (recent)
docs/superpowers/          specs/ + plans/ (design & implementation docs)
.worktrees/                git worktrees (git-ignored)
```

## Running the App

```powershell
# From the repo root. Requires PostgreSQL + Redis reachable (see .env).
python server.py
# or
python -m backend.main
```

Open <http://127.0.0.1:4173>. API docs at <http://127.0.0.1:4173/docs>.

`.env` is git-ignored. Copy `.env.example` to `.env` and fill in `POSTGRES_*` / `REDIS_*` before first run. Never commit real credentials.

## Testing

```powershell
python -m pytest tests/ -v            # backend tests (fast + offline via monkeypatch)
node --check frontend/app.js          # frontend syntax check (no JS test runner exists)
```

There is **no JS test runner** in this repo. Frontend behavior is verified manually in the browser (`docs/superpowers/specs/...` list the acceptance checks). If you need JS unit tests, that's part of the Phase 4 "frontend engineering" effort — don't invent a test framework without a task.

## Key Conventions / Rules

- **Never fill missing data with mock values.** The frontend shows `--` / empty states instead. Quote failures must surface as cache/stale/error states, never fabricated prices.
- **Preserve existing API field names.** Adding fields is fine; renaming/removing breaks the Vue frontend.
- **Timestamps:** `createdAt` is epoch **milliseconds** (`Date.now()` on the frontend, `int(created_at.timestamp() * 1000)` on the backend). Format for display with `formatTime(ms)`.
- **Plan `status` values:** `执行中`, `已触发`, `已过期`, `已归档`. `activePlans` on the frontend shows only `执行中`/`已触发`.
- **Price-trigger semantics are direction-aware:** for a `buy` plan, `price <= stop` (stop-loss) and `price >= target` (take-profit); for a `sell` plan (already holding), `price >= target` (take-profit sell) and `price <= stop` (stop-loss sell).
- **Grid backtest assumptions are deliberately conservative and disclosed** (T+1, 100-share lots, min commission, stamp duty, transfer fee, slippage, price limits, suspensions; 70/30 train/validation split). Do not present backtest returns as future performance.
- **Classify instruments** via `classify_code()` (exchange / board / securityType). Price-limit ratios differ by board (北交所 30%, 创业板/科创板 20%, else 10%).
- **Security:** XSS-sensitive spots are `showToast` (must use `textContent`) and `chartSvg` (must `escapeHtml` interpolated labels). Keep that discipline.
- **Frontend polling** is driven by `setupRefreshTimer()` and honors `settingsDraft.refreshInterval`; `refreshAll()` guards against concurrent runs via `refreshInFlight`.

## Git Workflow — Git Flow (mandatory)

**The repository REQUIRES Git Flow. All feature / release / hotfix work must go through Git Flow branches.**

- Branches: `main` (releases, tagged), `develop` (integration), `feature/*` (off `develop`), `release/*`, `hotfix/*`.
- Never commit feature work directly to `main` or `develop` — branch from `develop` with `feature/*`, then `git flow feature finish`.
- Commands (`git-flow-avh`):
  - `git flow feature start <name>` (off `develop`)
  - ... do work + commit ...
  - `git flow feature finish <name>` (merge `--no-ff` into `develop`)
  - `git flow release start v0.x.y` / `git flow release finish v0.x.y` (into `main` + tag + sync `develop`)
- `git flow init` requires a **clean working tree** — stash uncommitted changes first.
- The harness command runner cannot execute git in this repo — run git commands yourself and paste output when reporting.

### Commit Message Convention

- **Subject (first line) MUST be written in Chinese.**
- Use Conventional Commits type prefixes (`feat` / `fix` / `refactor` / `perf` / `test` / `docs` / `chore`), optionally followed by a Chinese subject.
  - e.g. `feat: 新增全市场选股与分页`, `fix: 修复计划有效期过期逻辑`, `docs: 完善 AGENTS.md`.
- Body (optional) in Chinese preferred — explain what changed and why.
- One commit per logical change; keep commits small and reviewable.

## Storage & Data Notes

- PostgreSQL stores watchlist, trade plans, alerts, grid strategies/backtests, market bars, and workspace settings. Redis is only pinged for `storage_status()`; the actual quote cache is an in-memory `dict` in `data_source.py` with an 8s TTL.
- The screener currently uses a curated ~50-stock universe (`REAL_UNIVERSE` in `data_source.py`). Expanding to the full A-share market is Phase 2 — do not silently expand it.
- `storage.py` uses raw `ALTER TABLE ... IF NOT EXISTS` for forward migrations rather than Alembic. Prefer adding to that mechanism over a new migration framework.

## When to Ask

Stop and ask rather than guessing when: a raw test/verification fails, an instruction is ambiguous, you're about to exceed the current phase's non-goals (no broker integration, no full-market screener, no new strategy types, no UI rebrand), or the git state is unexpected.
