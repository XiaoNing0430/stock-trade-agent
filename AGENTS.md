# AGENTS.md

Guidance for AI coding agents working in this repository.

## What This Is

**Atlas Trading Desk** — a local, single-user A-share (Chinese stock market) research & trading-desk web application. Real quote data drives a screener, trade plans, a price-trigger monitoring center, and grid-strategy backtesting. It is a **research tool, not an execution system**: it never connects to a broker and never sends orders.

UI copy is Chinese. Keep new user-facing strings in Chinese unless a task says otherwise.

## Tech Stack

- **Frontend:** Vue 3 + TypeScript 5.9 (strict) + Vite 8 + Pinia 4 + vitest 4 + @vue/test-utils + lucide. Source in `frontend/src/` (stores/, modules/, views/, types/, api/, app.ts, main.ts, App.vue). Built by Vite, served as static files or via Vite dev server.
- **Backend:** Python / FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Alembic 1.14 (migrations in `backend/migrations/`) + APScheduler (grid backtest scheduling) + ruff + mypy + pytest-cov.
- **Data source:** Tencent public quote API (`qt.gtimg.cn`, `web.ifzq.gtimg.cn`). Only data source currently integrated.
- **Config:** `.env` (git-ignored) sourced from `.env.example`.

## Project Layout

```
server.py                 Dev entrypoint — starts uvicorn on 127.0.0.1:4173
backend/
  app.py                  FastAPI app, all /api routes, serves frontend
  main.py                 python -m backend.main entrypoint
  data_source.py          Tencent quote API adapter + classification + fetch/retry + runtime config
  grid_strategy.py        Grid math: build_grid, suggest_grid, backtest_grid, optimize_grid (+ benchmark/risk metrics)
  grid_scheduler.py       APScheduler wrappers for daily grid backtests (Asia/Shanghai)
  schemas.py              24 Pydantic request/response models (+ 1 alias)
  storage.py              SQLAlchemy models + persistence helpers (10 tables)
  strategy_engines.py     Strategy backtest engines (grid, SMA, DCA, MACD)
  settings.py             pydantic-settings; env (POSTGRES_*, REDIS_*, TUSHARE_TOKEN)
  migrations/             Alembic migration scripts (baseline + forward)
frontend/
  index.html              Vite entry HTML — references /src/main.ts
  src/
    main.ts               Vue app bootstrap (createApp, Pinia, mount)
    app.ts                Vue app setup, router, polling, error handling
    App.vue               Root SFC — layout shell
    styles.css            All styling (CSS variables, single file)
    api/
      client.ts           Axios-like fetch wrapper
    stores/               8 Pinia stores
      useWorkspaceStore.ts / useQuotesStore.ts / useScreenerStore.ts
      useGridStore.ts / useStrategyStore.ts / usePlansStore.ts
      useAlertsStore.ts / useSettingsStore.ts
    modules/              Pure logic helpers
      constants.ts / format.ts / chart.ts / planUtils.ts
      marketUtils.ts / signalUtils.ts / alertUtils.ts
    views/                7 SFC views
      ViewSettings.vue / ViewOverview.vue / ViewMonitor.vue
      ViewScreener.vue / ViewStockDetail.vue / ViewGrid.vue / ViewPlans.vue
    types/
      models.ts           TypeScript type definitions
tests/
  test_backend_api.py     FastAPI routes + data_source parsing (+ HTTP retry/backoff, runtime config)
  test_grid_strategy.py   Grid math (+ benchmark/risk metrics, candidate robustness)
  test_grid_scheduler_coverage.py
  test_settings_api.py    Settings API + default settings assertions
  test_schemas.py         Pydantic model validation tests
  test_storage_coverage.py
  test_strategy_engines.py
  frontend/               10 vitest test files (66 tests total)
docs/superpowers/          specs/ + plans/ (design & implementation docs)
.worktrees/                git worktrees (git-ignored)
```

## Running the App

The app supports **dual-track** operation:

### Development (hot-reload mode)

```powershell
# From the repo root. Requires PostgreSQL + Redis reachable (see .env).
npm run dev
```

This starts both the Vite dev server on `:5173` (frontend HMR) and the FastAPI backend on `:4173` (API). Frontend proxies `/api` requests to the backend.

Open <http://127.0.0.1:5173>. API docs at <http://127.0.0.1:4173/docs>.

### Production (static build)

```powershell
npm run build
python server.py
# or
python -m backend.main
```

`npm run build` runs `vue-tsc --noEmit` (type checking) + `vite build` → outputs to `frontend/dist/`. The FastAPI backend serves the static build on `:4173`.

Open <http://127.0.0.1:4173>.

**Compatibility:** If `frontend/dist/` does not exist, `python server.py` falls back to serving the raw `frontend/` source files — but this requires the Vite dev server to be running separately for the frontend to function. Without either `dist/` or `npm run dev`, the frontend is unavailable (the backend API still works).

`.env` is git-ignored. Copy `.env.example` to `.env` and fill in `POSTGRES_*` / `REDIS_*` before first run. Never commit real credentials.

## Testing

```powershell
npm run verify                        # full regression: vitest + vue-tsc + pytest
npx vitest run                        # frontend unit tests (66 tests, 10 files, jsdom + @vue/test-utils)
python -m pytest tests/ -v            # backend tests (139 tests, fast + offline via monkeypatch)
python -m ruff check backend tests server.py
python -m ruff format --check backend tests server.py
python -m mypy backend
pre-commit run --all-files            # run all pre-commit hooks (ruff / mypy / eslint / prettier / vue-tsc)
```

Notes:

- Backend pytest runs with coverage (≥80% gate, currently 97.8%).
- Pre-commit hooks (`ruff --fix` / `ruff-format` / `mypy` / `eslint` / `prettier` / `vue-tsc --noEmit`) run automatically on `git commit`.
- `npm run build` also runs `vue-tsc --noEmit` as a type-check gate before Vite bundling.

## Key Conventions / Rules

- **Never fill missing data with mock values.** The frontend shows `--` / empty states instead. Quote failures must surface as cache/stale/error states, never fabricated prices.
- **Preserve existing API field names.** Adding fields is fine; renaming/removing breaks the Vue frontend.
- **Timestamps:** the canonical machine timestamp is `createdAtMs` — epoch **milliseconds** (`Date.now()` on the frontend, `int(created_at.timestamp() * 1000)` on the backend). `createdAt` is a display convenience string (`HH:MM`). Format for display with `formatTime(ms)`.
- **Plan `status` values:** `执行中`, `已触发`, `已过期`, `已归档`. `activePlans` on the frontend shows only `执行中`/`已触发`.
- **Price-trigger semantics are direction-aware:** for a `buy` plan, `price <= stop` (stop-loss) and `price >= target` (take-profit); for a `sell` plan (already holding), `price >= target` (take-profit sell) and `price <= stop` (stop-loss sell).
- **Grid backtest assumptions are deliberately conservative and disclosed** (T+1, 100-share lots, min commission, stamp duty, transfer fee, slippage, price limits, suspensions; 70/30 train/validation split). Do not present backtest returns as future performance.
- **Classify instruments** via `classify_code()` (exchange / board / securityType). Price-limit ratios differ by board (北交所 30%, 创业板/科创板 20%, else 10%).
- **Explicit `any` is an accepted convention** in `frontend/src/` for dynamically structured quote payloads from external APIs (`eslint.config.js` sets `@typescript-eslint/no-explicit-any: 'off'`). Keep the type surface as narrow as practical; prefer precise types for new code.
- **Security:** XSS-sensitive spots are `showToast` (must use `textContent`) and `chartSvg` (must `escapeHtml` interpolated labels). Keep that discipline.
- **Frontend polling** is driven by `armRefreshTimer()` and honors `settingsDraft.refreshInterval`; `refreshAll()` guards against concurrent runs via `refreshInFlight`.
- **Workspace sync is revision-locked:** `GET /api/workspace` returns `revision`; `PUT /api/workspace` accepts `baseRevision` (conflict → 409 with the server snapshot in `detail.workspace`) and `force=true` to override. The frontend keeps the latest known `revision` in `workspaceRevision` and resolves 409 by `settingsDraft.conflictPolicy`: `server` (default) auto-adopts the server snapshot, `local` auto-force-saves the local one, `ask` shows the conflict banner with "采用服务器版本" / "用本地覆盖" actions — never auto-retry a 409.
- **Grid backtest day classification:** suspension = `volume <= 0` only. A one-price day (`high == low`, volume > 0) at limit-up is tradeable for sells only; at limit-down, buys only. Counters: `onePriceLimitUpDays` / `onePriceLimitDownDays` (new metrics fields, additive).

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

- PostgreSQL stores watchlist, trade plans, alerts, grid strategies/backtests, market bars, and workspace settings. Redis is only pinged for `storage_status()`; the actual quote cache is an in-memory `dict` in `data_source.py`. The HTTP timeout/retry/cache-TTL are driven by workspace settings via `data_source.apply_runtime_config(...)` (defaults: TTL 8s, timeout 10s, retry 1).
- The screener currently uses a curated ~50-stock universe (`REAL_UNIVERSE` in `data_source.py`). Expanding to the full A-share market is Phase 2 — do not silently expand it.
- Schema migrations use **Alembic** (`backend/migrations/`). Baseline migration at `c1a08e78583e_baseline_schema.py`. Add new migrations via `alembic revision --autogenerate -m "description"` and review the generated script before committing.

## When to Ask

Stop and ask rather than guessing when: a raw test/verification fails, an instruction is ambiguous, you're about to exceed the current phase's non-goals (no broker integration, no full-market screener, no new strategy types, no UI rebrand), or the git state is unexpected.