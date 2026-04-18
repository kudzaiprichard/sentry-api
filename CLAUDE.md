# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands assume the project venv is active (`venv\Scripts\activate` on Windows, `source venv/bin/activate` on POSIX). There is no `requirements.txt` or `pyproject.toml` — dependencies are installed ad-hoc into `venv/`.

```bash
# Run the dev server (factory + reload)
python main.py

# Alembic — env.py pulls DATABASE_URL from src.configs, so the value in alembic.ini is ignored at runtime
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
alembic downgrade -1

# Regenerate the config IDE stub (src/configs/__init__.pyi)
# Boot also regenerates it automatically; run manually only if editing application.yaml outside a boot
python -m src.configs.generate
```

No test suite, linter, or formatter is configured. Don't add one unless asked.

## Architecture

The canonical specs live in two files under `.claude/` (gitignored, local only):

- `.claude/project_base_setup.md` — full scaffold reference for `src/shared/`, `src/configs/`, `src/core/`, Alembic, and middleware. Treat as the source of truth for anything touching the base layer.
- `.claude/module_architecture.md` — the single source of truth for building any new module. The `auth` module is the reference implementation. Read this before creating a new module.

**Read those files** before making non-trivial changes — the rules below are only the highest-signal items that routinely matter.

### Config system (non-standard)

`src/configs/application.yaml` uses a pipe format: `"${ENV_VAR:default} | type"`, `"${ENV_VAR} | type | required"`, or `"literal | type"`. Types: `str`, `int`, `float`, `bool`, `list` (comma-split).

On import, `src/configs/__init__.py` loads the YAML, resolves env vars, validates all required fields (collecting every error before raising), and exposes each top-level section as a module attribute: `from src.configs import database; database.url`. It also regenerates `src/configs/__init__.pyi` for IDE autocomplete. When adding a new config section, update `application.yaml` and `.env.example` together; the stub regenerates itself.

Required keys (startup aborts if unset): `DATABASE_URL`, `JWT_SECRET_KEY`, `ADMIN_PASSWORD`.

### Module layout

Every domain module lives at `src/modules/{name}/` and has this fixed shape:

```
domain/{models,repositories,services}/   # ORM models, data access, business logic
internal/                                 # module-private helpers, seeders, background loops
presentation/{controllers,dtos}/          # FastAPI routers, request/response DTOs
presentation/dependencies.py              # service factories + role guards
```

Cross-module rules:
- A module must never import from another module's `domain/` or `internal/` layer, with two exceptions: (1) any module may import `get_current_user`, `require_role`, `Role`, `User` from auth; (2) a service may import a foreign repository directly for data composition within the same session. Never call another module's service methods.
- When completing a new module, follow the **New Module Registration Checklist** in `.claude/module_architecture.md` — it covers `presentation/__init__.py`, module root `__init__.py`, `src/core/factory.py::_register_routers`, `alembic/env.py` imports, and optional `src/core/lifespan.py` wiring for seeders/background tasks.

### Key base-layer invariants

- **`BaseModel`** (from `src.shared.database`) supplies `id` (UUID, server-side `gen_random_uuid()`), `created_at`, `updated_at` on every table. Never redeclare these.
- **Enums** inherit `(str, enum.Enum)` and are stored with SQLAlchemy `Enum(..., name="{field}_enum")`. The app's roles are `ADMIN` and `IT_ANALYST` (note: `.claude/module_architecture.md` examples sometimes show `DOCTOR` — that's stale template text; the live enum is in `src/modules/auth/domain/models/enums.py`).
- **Sessions**: `get_db` opens `session.begin()` — commits on clean return, rolls back on exception. `get_db_readonly` has no transaction. Repository write methods call `flush` (never `commit`) because the dependency owns the transaction.
- **`BaseRepository[T]`** provides `get_by_id`, `get_one`, `exists`, `get_all`, `paginate` (returns `(records, total)`), `count`, `create`, `create_many`, `update`, `delete`. Use it for equality filters; write custom `select()` in the subclass for `ilike`, `OR`, joins, bulk `update()`, or complex ordering.
- **Responses** always use `ApiResponse.ok(value=..., message=...)` or `PaginatedResponse.ok(value=..., page=..., total=..., page_size=...)`. `value` and `error` are mutually exclusive (validator-enforced). JSON output uses `model_dump(exclude_none=True, by_alias=True)` — response DTOs declare camelCase aliases (`Field(alias="createdAt")`) and `Config: populate_by_name = True; from_attributes = True`, with a `from_{entity}(entity)` static factory that passes values by **alias** name.
- **Errors** — raise an `AppException` subclass (`NotFoundException`, `ConflictException`, `BadRequestException`, `AuthenticationException`, `AuthorizationException`, `ValidationException`, `InternalServerException`, `ServiceUnavailableException`) with an `ErrorDetail`. Use `ErrorDetail.builder(...).add_field_error(...)` when surfacing per-field errors; use direct `ErrorDetail(...)` otherwise. Global handlers in `src/shared/exceptions/error_handlers.py` convert these to the `ApiResponse` envelope.
- **Middleware**: `RequestLoggingMiddleware` is raw ASGI on purpose — `BaseHTTPMiddleware` buffers response bodies and breaks SSE streaming. Keep any new middleware raw ASGI if it may touch streaming responses.

### Lifespan (`src/core/lifespan.py`)

Startup sets up logging, then runs `seed_admin()` (creates an ADMIN from `security.admin.*` env if none exists) and spawns the `start_token_cleanup()` background loop (purges expired JWTs on `TOKEN_CLEANUP_INTERVAL_SECONDS`). Shutdown cancels the cleanup task and disposes the engine.

New background tasks go here: create with `asyncio.create_task(...)` before `yield`, cancel + `await` with `CancelledError` suppression after `yield`. The loop itself must catch `CancelledError` and re-raise to exit cleanly.

### Auth specifics

JWT pair (access + refresh) created on login/register/refresh; each token is also persisted in the `tokens` table so revocation works. `token_provider.verify_token` decodes the JWT *and* checks the DB row is not revoked/expired. `login` and `refresh_token` revoke all prior user tokens before issuing new ones. `logout` revokes all of the user's tokens.
