# FastAPI Project Base Setup

A complete, copy-pasteable scaffold for a production-ready FastAPI project with async PostgreSQL, SQLAlchemy, Alembic, YAML-driven config, and a consistent API response layer.

---

## 1. Project Structure

```
project/
├── src/
│   ├── configs/
│   │   ├── __init__.py
│   │   ├── loader.py
│   │   ├── generate.py
│   │   └── application.yaml
│   ├── core/
│   │   ├── __init__.py 
│   │   ├── factory.py
│   │   ├── lifespan.py
│   │   └── middleware.py
│   └── shared/
│       ├── __init__.py
│       ├── database/
│       │   ├── __init__.py
│       │   ├── engine.py
│       │   ├── base_model.py
│       │   ├── repository.py
│       │   ├── dependencies.py
│       │   └── pagination.py
│       ├── responses/
│       │   ├── __init__.py
│       │   └── api_response.py
│       └── exceptions/
│           ├── __init__.py
│           ├── exceptions.py
│           └── error_handlers.py
├── alembic/
│   └── env.py
├── main.py
├── alembic.ini
├── .env.example
└── .gitignore
```

---

## 2. All Packages

```bash
pip install fastapi uvicorn[standard] sqlalchemy[asyncio] asyncpg alembic \
    pydantic pydantic-settings python-dotenv pyyaml
```

Full pinned install (recommended for reproducibility):

```bash
pip install \
    fastapi \
    "uvicorn[standard]" \
    "sqlalchemy[asyncio]" \
    asyncpg \
    alembic \
    pydantic \
    pydantic-settings \
    python-dotenv \
    pyyaml
```

---

## 3. Complete File Contents

### `src/configs/loader.py`

```python
import os
import re
import yaml
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when configuration validation fails."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        msg = "Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
        super().__init__(msg)


# ──────────────────────────────────────────────
# Type casting
# ──────────────────────────────────────────────

_TYPE_CASTERS = {
    "str": str,
    "int": int,
    "float": float,
    "bool": lambda v: str(v).lower() in ("true", "1", "yes", "on"),
    "list": lambda v: [
        item.strip() for item in str(v).split(",") if item.strip()
    ],
}


def _cast(value: Any, type_hint: str, key_path: str) -> Any:
    """Cast a resolved value to the declared type."""
    caster = _TYPE_CASTERS.get(type_hint)
    if caster is None:
        raise ValueError(f"{key_path}: unknown type '{type_hint}'")
    try:
        return caster(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"{key_path}: expected {type_hint}, got '{value}' — {e}")


# ──────────────────────────────────────────────
# Env var resolution
# ──────────────────────────────────────────────

_ENV_PATTERN = re.compile(r"^\$\{([^}]+)\}$")


def _resolve_value(raw: str) -> tuple[Optional[str], bool]:
    """
    Resolve a ${VAR} or ${VAR:default} placeholder.

    Returns:
        (resolved_value, was_from_env)
    """
    match = _ENV_PATTERN.match(raw)
    if not match:
        return raw, False

    expr = match.group(1)

    if ":" in expr:
        var_name, default = expr.split(":", 1)
        value = os.environ.get(var_name, default)
        return value, var_name in os.environ
    else:
        value = os.environ.get(expr)
        if value is None:
            return None, False
        return value, True


# ──────────────────────────────────────────────
# Pipe format parsing
# ──────────────────────────────────────────────

def _parse_pipe(raw: str) -> tuple[str, str, bool]:
    """
    Parse a pipe-delimited config value.

    Format: "${VAR:default} | type" or "${VAR} | type | required"

    Returns:
        (value_part, type_hint, is_required)
    """
    parts = [p.strip() for p in raw.rsplit("|", raw.count("|"))]

    if len(parts) == 3:
        return parts[0], parts[1], parts[2].lower() == "required"
    elif len(parts) == 2:
        return parts[0], parts[1], False
    else:
        return raw, "str", False


def _is_leaf(node: Any) -> bool:
    """Check if a YAML node is a pipe-formatted leaf string."""
    return isinstance(node, str) and "|" in node


def _is_section(node: Any) -> bool:
    """Check if a YAML node is a nested section."""
    return isinstance(node, dict)


# ──────────────────────────────────────────────
# Core loader
# ──────────────────────────────────────────────

def _process_node(
    node: Any,
    path: str,
    errors: List[str],
) -> Any:
    """Recursively process a YAML node into resolved, typed values."""
    if _is_section(node):
        ns = SimpleNamespace()
        for key, child in node.items():
            child_path = f"{path}.{key}" if path else key
            python_key = key.replace("-", "_").replace(" ", "_")
            setattr(ns, python_key, _process_node(child, child_path, errors))
        return ns

    if _is_leaf(node):
        value_part, type_hint, required = _parse_pipe(node)
        resolved, from_env = _resolve_value(value_part)

        if resolved is None:
            if required:
                errors.append(f"{path}: required but not set")
            return None

        try:
            return _cast(resolved, type_hint, path)
        except ValueError as e:
            errors.append(str(e))
            return None

    # Plain value (no pipe) — return as-is
    return node


def load_config(
    config_path: Optional[str] = None,
    env_path: Optional[str] = None,
) -> Dict[str, SimpleNamespace]:
    """
    Load YAML config, resolve env vars, validate types.

    Args:
        config_path: Path to application.yaml (defaults to ./application.yaml)
        env_path: Path to .env file (defaults to project root .env)

    Returns:
        Dict mapping top-level section names to SimpleNamespace objects.

    Raises:
        FileNotFoundError: If application.yaml is missing.
        ConfigError: If any required values are missing or types are invalid.
    """
    configs_dir = Path(__file__).resolve().parent
    if config_path is None:
        config_path = configs_dir / "application.yaml"
    else:
        config_path = Path(config_path)

    if env_path is None:
        env_path = configs_dir.parent.parent / ".env"
    else:
        env_path = Path(env_path)

    # Load .env (silently skip if missing — env vars may come from system)
    if env_path.exists():
        load_dotenv(env_path)

    # Load YAML
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        raw_config = yaml.safe_load(f) or {}

    # Process all sections
    errors: List[str] = []
    sections: Dict[str, SimpleNamespace] = {}

    for section_name, section_data in raw_config.items():
        sections[section_name] = _process_node(
            section_data, section_name, errors
        )

    # Fail fast
    if errors:
        raise ConfigError(errors)

    return sections
```

---

### `src/configs/generate.py`

```python
# Generates __init__.pyi stub file from application.yaml for
# IDE autocomplete support.
#
# Usage:
#   python -m src.configs.generate
# ============================================================
import yaml
from pathlib import Path
from typing import Any, Dict


_TYPE_MAP = {
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "list": "list[str]",
}


def _is_leaf(node: Any) -> bool:
    return isinstance(node, str) and "|" in node


def _is_section(node: Any) -> bool:
    return isinstance(node, dict)


def _parse_pipe(raw: str) -> tuple[str, str, bool]:
    parts = [p.strip() for p in raw.rsplit("|", raw.count("|"))]
    if len(parts) == 3:
        return parts[0], parts[1], parts[2].lower() == "required"
    elif len(parts) == 2:
        return parts[0], parts[1], False
    return raw, "str", False


def _class_name(key: str) -> str:
    return "".join(
        part.capitalize() for part in key.replace("-", "_").split("_")
    )


def _generate_class(
    name: str,
    node: Dict[str, Any],
    indent: int = 0,
) -> list[str]:
    pad = "    " * indent
    lines = [f"{pad}class {_class_name(name)}:"]

    has_attrs = False
    for key, child in node.items():
        python_key = key.replace("-", "_").replace(" ", "_")

        if _is_leaf(child):
            _, type_hint, _ = _parse_pipe(child)
            py_type = _TYPE_MAP.get(type_hint, "Any")
            lines.append(f"{pad}    {python_key}: {py_type}")
            has_attrs = True

        elif _is_section(child):
            nested = _generate_class(python_key, child, indent + 1)
            lines.extend(nested)
            lines.append(f"{pad}    {python_key}: {_class_name(python_key)}")
            has_attrs = True

        else:
            if isinstance(child, bool):
                lines.append(f"{pad}    {python_key}: bool")
            elif isinstance(child, int):
                lines.append(f"{pad}    {python_key}: int")
            elif isinstance(child, float):
                lines.append(f"{pad}    {python_key}: float")
            else:
                lines.append(f"{pad}    {python_key}: str")
            has_attrs = True

    if not has_attrs:
        lines.append(f"{pad}    ...")

    return lines


def generate_stub(
    config_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> Path:
    configs_dir = Path(__file__).resolve().parent

    if config_path is None:
        config_path = configs_dir / "application.yaml"
    else:
        config_path = Path(config_path)

    if output_path is None:
        output_path = configs_dir / "__init__.pyi"
    else:
        output_path = Path(output_path)

    with open(config_path, "r") as f:
        raw_config = yaml.safe_load(f) or {}

    stub_lines = [
        "# AUTO-GENERATED by src.configs.generate — do not edit manually",
        "# Regenerate: python -m src.configs.generate",
        "",
    ]

    for section_name, section_data in raw_config.items():
        python_name = section_name.replace("-", "_").replace(" ", "_")

        if _is_section(section_data):
            class_lines = _generate_class(python_name, section_data)
            stub_lines.extend(class_lines)
            stub_lines.append("")
            stub_lines.append(f"{python_name}: {_class_name(python_name)}")
        elif _is_leaf(section_data):
            _, type_hint, _ = _parse_pipe(section_data)
            py_type = _TYPE_MAP.get(type_hint, "Any")
            stub_lines.append(f"{python_name}: {py_type}")
        else:
            stub_lines.append(f"{python_name}: Any")

        stub_lines.append("")

    stub_lines.append("def reload_config() -> None: ...")
    stub_lines.append("")

    output_path.write_text("\n".join(stub_lines))
    return output_path


if __name__ == "__main__":
    generate_stub()
    print("Stub generated.")
```

---

### `src/configs/__init__.py`

```python
import sys
import logging
from src.configs.loader import load_config, ConfigError
from src.configs.generate import generate_stub

logger = logging.getLogger("configs")
logging.basicConfig(level=logging.INFO)


def _boot_config():
    """Load config with clean error reporting."""
    logger.info("Loading system configs...")

    try:
        sections = load_config()
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except ConfigError as e:
        logger.error("Found %d configuration error(s):", len(e.errors))
        for err in e.errors:
            logger.error("  %s", err)
        logger.error("Fix the above in your .env or application.yaml and restart.")
        sys.exit(1)

    for name in sections:
        logger.info("Loaded section: %s", name)

    logger.info("Config loaded successfully (%d sections)", len(sections))

    try:
        generate_stub()
    except Exception as e:
        logger.warning("Stub generation failed: %s", e)

    return sections


_sections = _boot_config()

for _name, _ns in _sections.items():
    globals()[_name] = _ns


def reload_config() -> None:
    """Reload configuration from YAML and regenerate stub."""
    global _sections
    _sections = _boot_config()
    for name, ns in _sections.items():
        globals()[name] = ns
```

---

### `src/configs/application.yaml`

```yaml
# ============================================================
# Application Configuration
# ============================================================
# Format: "${ENV_VAR:default} | type"
# Required: "${ENV_VAR} | type | required"
# Static:   "value | type"
# Types:    str, int, float, bool, list

application:
  name: "${APP_NAME:MyApp} | str"
  version: "${APP_VERSION:0.1.0} | str"
  debug: "${DEBUG:false} | bool"
  environment: "${ENVIRONMENT:development} | str"

database:
  url: "${DATABASE_URL} | str | required"
  pool_size: "${DB_POOL_SIZE:5} | int"
  max_overflow: "${DB_MAX_OVERFLOW:10} | int"
  pool_timeout: "${DB_POOL_TIMEOUT:30} | int"
  echo: "${DB_ECHO:false} | bool"
  pool_pre_ping: "true | bool"
  pool_recycle: "1800 | int"

security:
  jwt:
    secret_key: "${JWT_SECRET_KEY} | str | required"
    algorithm: "${JWT_ALGORITHM:HS256} | str"
    access_token_expire_minutes: "${ACCESS_TOKEN_EXPIRE_MINUTES:30} | int"
    refresh_token_expire_days: "${REFRESH_TOKEN_EXPIRE_DAYS:7} | int"

server:
  cors:
    origins: "${CORS_ORIGINS:*} | list"
    allow_credentials: "${CORS_ALLOW_CREDENTIALS:true} | bool"
    allow_methods: "${CORS_ALLOW_METHODS:*} | list"
    allow_headers: "${CORS_ALLOW_HEADERS:*} | list"

logging:
  level: "${LOG_LEVEL:INFO} | str"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s | str"
  file_path: "${LOG_FILE_PATH:logs/app.log} | str"
```

---

### `src/core/__init__.py`

```python
from src.core.factory import create_app

__all__ = ["create_app"]
```

---

### `src/core/lifespan.py`

```python
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.shared.database.engine import engine
from src.configs import logging as log_config


logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    log_dir = os.path.dirname(log_config.file_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_level = getattr(logging, log_config.level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format=log_config.format,
        handlers=[
            logging.FileHandler(log_config.file_path),
            logging.StreamHandler(),
        ],
        force=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    _setup_logging()
    logger.info("Starting up — logging configured, DB pool initialised")

    yield

    # ── Shutdown ──
    await engine.dispose()
    logger.info("Shutting down — DB pool disposed")
```

---

### `src/core/middleware.py`

```python
import time
import logging
from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.middleware.cors import CORSMiddleware
from src.configs import server

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    """
    Raw ASGI middleware for request logging.
    Unlike BaseHTTPMiddleware / @app.middleware("http"),
    this does NOT buffer the response body — so SSE streaming works.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        method = scope.get("method", "?")
        path = scope.get("path", "?")

        status_code = None

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        await self.app(scope, receive, send_wrapper)

        elapsed = round(time.perf_counter() - start, 4)
        logger.info(f"{method} {path} — {status_code} ({elapsed}s)")


def register_middleware(app: FastAPI) -> None:
    # Order matters: first added = outermost middleware
    # CORS must be outermost to handle preflight requests
    _add_cors(app)
    # Logging as raw ASGI middleware — does NOT break SSE
    app.add_middleware(RequestLoggingMiddleware)


def _add_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=server.cors.origins,
        allow_credentials=server.cors.allow_credentials,
        allow_methods=server.cors.allow_methods,
        allow_headers=server.cors.allow_headers,
    )
```

---

### `src/core/factory.py`

```python
from fastapi import FastAPI
from src.configs import application
from src.core.lifespan import lifespan
from src.core.middleware import register_middleware
from src.shared.exceptions.error_handlers import register_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(
        title=application.name,
        version=application.version,
        debug=application.debug,
        lifespan=lifespan,
    )

    register_middleware(app)
    register_error_handlers(app)
    _register_routers(app)

    return app


def _register_routers(app: FastAPI) -> None:
    # Register your domain routers here
    pass
```

---

### `src/shared/__init__.py`

```python
# Database
from src.shared.database import (
    engine,
    async_session,
    Base,
    BaseModel,
    BaseRepository,
    get_db,
    get_db_readonly,
)

# Responses
from src.shared.responses import (
    ApiResponse,
    PaginatedResponse,
    PaginationInfo,
    ErrorDetail,
)

# Exceptions
from src.shared.exceptions import (
    AppException,
    NotFoundException,
    AuthenticationException,
    AuthorizationException,
    BadRequestException,
    ConflictException,
    ValidationException,
    InternalServerException,
    ServiceUnavailableException,
)

__all__ = [
    # Database
    "engine",
    "async_session",
    "Base",
    "BaseModel",
    "BaseRepository",
    "get_db",
    "get_db_readonly",
    # Responses
    "ApiResponse",
    "PaginatedResponse",
    "PaginationInfo",
    "ErrorDetail",
    # Exceptions
    "AppException",
    "NotFoundException",
    "AuthenticationException",
    "AuthorizationException",
    "BadRequestException",
    "ConflictException",
    "ValidationException",
    "InternalServerException",
    "ServiceUnavailableException",
]
```

---

### `src/shared/database/__init__.py`

```python
from src.shared.database.engine import engine, async_session
from src.shared.database.base_model import Base, BaseModel
from src.shared.database.repository import BaseRepository
from src.shared.database.dependencies import get_db, get_db_readonly
from src.shared.database.pagination import PaginationParams, get_pagination

__all__ = [
    "engine",
    "async_session",
    "Base",
    "BaseModel",
    "BaseRepository",
    "get_db",
    "get_db_readonly",
    "PaginationParams",
    "get_pagination",
]
```

---

### `src/shared/database/engine.py`

```python
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from src.configs import database

engine = create_async_engine(
    database.url,
    echo=database.echo,
    pool_size=database.pool_size,
    max_overflow=database.max_overflow,
    pool_timeout=database.pool_timeout,
    pool_pre_ping=database.pool_pre_ping,
    pool_recycle=database.pool_recycle,
)

async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

---

### `src/shared/database/base_model.py`

```python
import uuid
from datetime import datetime
from sqlalchemy import DateTime, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID


class Base(DeclarativeBase):
    pass


class BaseModel(Base):
    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        server_onupdate=func.now(),
    )
```

---

### `src/shared/database/repository.py`

```python
from typing import TypeVar, Generic, Type, Sequence, Dict, Any, Optional, Tuple
from uuid import UUID
from sqlalchemy import select, func, asc, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from src.shared.database.base_model import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseRepository(Generic[T]):
    def __init__(self, model: Type[T], session: AsyncSession):
        self.model = model
        self.session = session

    # ──────────────────────────────────────────
    # Single record
    # ──────────────────────────────────────────

    async def get_by_id(self, id: UUID) -> T | None:
        return await self.session.get(self.model, id)

    async def get_one(self, **filters: Any) -> T | None:
        """Get a single record matching the given filters."""
        stmt = select(self.model).filter_by(**filters)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def exists(self, **filters: Any) -> bool:
        """Check if a record matching the given filters exists."""
        stmt = select(func.count()).select_from(self.model).filter_by(**filters)
        result = await self.session.execute(stmt)
        return result.scalar_one() > 0

    # ──────────────────────────────────────────
    # Multiple records
    # ──────────────────────────────────────────

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        order_by: Optional[str] = None,
        descending: bool = False,
        **filters: Any,
    ) -> Sequence[T]:
        """Get records with optional filtering, ordering, and offset/limit."""
        stmt = self._apply_filters(select(self.model), **filters)
        stmt = self._apply_ordering(stmt, order_by, descending)
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def paginate(
        self,
        page: int = 1,
        page_size: int = 20,
        order_by: Optional[str] = None,
        descending: bool = False,
        **filters: Any,
    ) -> Tuple[Sequence[T], int]:
        """
        Get a page of records with total count.

        Returns:
            (records, total_count)
        """
        base = self._apply_filters(select(self.model), **filters)

        # Total count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Page of records
        stmt = self._apply_ordering(base, order_by, descending)
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        result = await self.session.execute(stmt)
        records = result.scalars().all()

        return records, total

    async def count(self, **filters: Any) -> int:
        """Count records with optional filtering."""
        stmt = select(func.count()).select_from(self.model)
        if filters:
            stmt = stmt.filter_by(**filters)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    # ──────────────────────────────────────────
    # Write operations
    # ──────────────────────────────────────────

    async def create(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def create_many(self, entities: Sequence[T]) -> Sequence[T]:
        """Bulk insert multiple entities."""
        self.session.add_all(entities)
        await self.session.flush()
        for entity in entities:
            await self.session.refresh(entity)
        return entities

    async def update(self, entity: T, data: Dict[str, Any]) -> T:
        for key, value in data.items():
            if not hasattr(entity, key):
                raise AttributeError(
                    f"{self.model.__name__} has no attribute '{key}'"
                )
            setattr(entity, key, value)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    # ──────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────

    def _apply_filters(self, stmt: Select, **filters: Any) -> Select:
        if filters:
            stmt = stmt.filter_by(**filters)
        return stmt

    def _apply_ordering(
        self, stmt: Select, order_by: Optional[str], descending: bool
    ) -> Select:
        if order_by and hasattr(self.model, order_by):
            col = getattr(self.model, order_by)
            stmt = stmt.order_by(desc(col) if descending else asc(col))
        return stmt
```

---

### `src/shared/database/dependencies.py`

```python
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from src.shared.database.engine import async_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Transactional session — auto-commits on success, rolls back on error."""
    async with async_session() as session:
        async with session.begin():
            yield session


async def get_db_readonly() -> AsyncGenerator[AsyncSession, None]:
    """Read-only session — no explicit transaction, no auto-commit."""
    async with async_session() as session:
        yield session
```

---

### `src/shared/database/pagination.py`

```python
from dataclasses import dataclass
from fastapi import Query


@dataclass
class PaginationParams:
    page: int
    page_size: int

    @property
    def skip(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


def get_pagination(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize", description="Items per page"),
) -> PaginationParams:
    return PaginationParams(page=page, page_size=page_size)
```

---

### `src/shared/responses/__init__.py`

```python
from src.shared.responses.api_response import (
    ApiResponse,
    PaginatedResponse,
    PaginationInfo,
    ErrorDetail,
)

__all__ = [
    "ApiResponse",
    "PaginatedResponse",
    "PaginationInfo",
    "ErrorDetail",
]
```

---

### `src/shared/responses/api_response.py`

```python
from __future__ import annotations

from typing import Generic, TypeVar, Optional, List, Dict
from pydantic import BaseModel, model_validator, Field
from math import ceil

T = TypeVar("T")


# ──────────────────────────────────────────────
# ErrorDetail
# ──────────────────────────────────────────────

class ErrorDetail(BaseModel):
    title: str
    code: str
    status: int
    details: Optional[List[str]] = Field(default=None, exclude_none=True)
    field_errors: Optional[Dict[str, List[str]]] = Field(
        default=None, exclude_none=True, alias="fieldErrors"
    )

    class Config:
        populate_by_name = True

    class Builder:
        def __init__(self, title: str, code: str, status: int):
            self._title = title
            self._code = code
            self._status = status
            self._details: List[str] = []
            self._field_errors: Dict[str, List[str]] = {}

        def add_detail(self, detail: str) -> ErrorDetail.Builder:
            self._details.append(detail)
            return self

        def add_field_error(self, field: str, error: str) -> ErrorDetail.Builder:
            self._field_errors.setdefault(field, []).append(error)
            return self

        def add_field_errors(self, field: str, errors: List[str]) -> ErrorDetail.Builder:
            self._field_errors.setdefault(field, []).extend(errors)
            return self

        def build(self) -> ErrorDetail:
            return ErrorDetail(
                title=self._title,
                code=self._code,
                status=self._status,
                details=self._details if self._details else None,
                field_errors=self._field_errors if self._field_errors else None,
            )

    @staticmethod
    def builder(title: str, code: str, status: int) -> ErrorDetail.Builder:
        return ErrorDetail.Builder(title, code, status)

    def has_details(self) -> bool:
        return bool(self.details)

    def has_field_errors(self) -> bool:
        return bool(self.field_errors)


# ──────────────────────────────────────────────
# ApiResponse
# ──────────────────────────────────────────────

class ApiResponse(BaseModel, Generic[T]):
    success: bool
    message: Optional[str] = None
    value: Optional[T] = None
    error: Optional[ErrorDetail] = None

    class Config:
        json_encoders = {None: lambda _: None}

    @model_validator(mode="after")
    def validate_exclusive(self):
        if self.error is not None and self.value is not None:
            raise ValueError("ApiResponse cannot have both error and value")
        return self

    @staticmethod
    def ok(value: T, message: Optional[str] = None) -> ApiResponse[T]:
        return ApiResponse(success=True, message=message, value=value)

    @staticmethod
    def failure(error: ErrorDetail, message: Optional[str] = None) -> ApiResponse[T]:
        return ApiResponse(success=False, message=message, error=error)


# ──────────────────────────────────────────────
# PaginatedResponse
# ──────────────────────────────────────────────

class PaginationInfo(BaseModel):
    page: int
    total: int
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")

    class Config:
        populate_by_name = True

    @model_validator(mode="before")
    @classmethod
    def compute_total_pages(cls, values):
        page_size = values.get("pageSize") or values.get("page_size")
        total = values.get("total", 0)
        if page_size is not None and page_size <= 0:
            raise ValueError("Page size must be greater than 0")
        if page_size and "totalPages" not in values and "total_pages" not in values:
            values["totalPages"] = ceil(total / page_size)
        return values


class PaginatedResponse(ApiResponse[List[T]], Generic[T]):
    pagination: Optional[PaginationInfo] = None

    @staticmethod
    def ok(
        value: List[T],
        page: int,
        total: int,
        page_size: int,
        message: Optional[str] = None,
    ) -> PaginatedResponse[T]:
        pagination = PaginationInfo(page=page, total=total, pageSize=page_size)
        return PaginatedResponse(
            success=True,
            message=message,
            value=value,
            pagination=pagination,
        )
```

---

### `src/shared/exceptions/__init__.py`

```python
from src.shared.exceptions.exceptions import (
    AppException,
    NotFoundException,
    ValidationException,
    AuthenticationException,
    AuthorizationException,
    ConflictException,
    BadRequestException,
    InternalServerException,
    ServiceUnavailableException,
)

__all__ = [
    "AppException",
    "NotFoundException",
    "ValidationException",
    "AuthenticationException",
    "AuthorizationException",
    "ConflictException",
    "BadRequestException",
    "InternalServerException",
    "ServiceUnavailableException",
]
```

---

### `src/shared/exceptions/exceptions.py`

```python
"""
Exception hierarchy for API responses.
Each exception wraps an ErrorDetail object for consistent error handling.
"""

from typing import Optional
from src.shared.responses.api_response import ErrorDetail


class AppException(Exception):
    def __init__(self, message: str = "An error occurred", error_detail: Optional[ErrorDetail] = None):
        self.message = message
        self.error_detail = error_detail or ErrorDetail(
            title="Application Error",
            code="APP_ERROR",
            status=500,
            details=[message] if message else [],
        )
        super().__init__(self.message)


class NotFoundException(AppException):
    def __init__(self, message: str = "The requested resource was not found", error_detail: Optional[ErrorDetail] = None):
        if error_detail is None:
            error_detail = ErrorDetail(title="Not Found", code="NOT_FOUND", status=404, details=[message])
        super().__init__(message, error_detail)


class ValidationException(AppException):
    def __init__(self, message: str = "Please check your input and try again", error_detail: Optional[ErrorDetail] = None):
        if error_detail is None:
            error_detail = ErrorDetail(title="Validation Failed", code="VALIDATION_ERROR", status=400, details=[message])
        super().__init__(message, error_detail)


class AuthenticationException(AppException):
    def __init__(self, message: str = "Please log in to continue", error_detail: Optional[ErrorDetail] = None):
        if error_detail is None:
            error_detail = ErrorDetail(title="Authentication Failed", code="AUTH_FAILED", status=401, details=[message])
        super().__init__(message, error_detail)


class AuthorizationException(AppException):
    def __init__(self, message: str = "You don't have permission to perform this action", error_detail: Optional[ErrorDetail] = None):
        if error_detail is None:
            error_detail = ErrorDetail(title="Access Denied", code="FORBIDDEN", status=403, details=[message])
        super().__init__(message, error_detail)


class ConflictException(AppException):
    def __init__(self, message: str = "This resource already exists", error_detail: Optional[ErrorDetail] = None):
        if error_detail is None:
            error_detail = ErrorDetail(title="Conflict", code="CONFLICT", status=409, details=[message])
        super().__init__(message, error_detail)


class BadRequestException(AppException):
    def __init__(self, message: str = "Your request could not be processed", error_detail: Optional[ErrorDetail] = None):
        if error_detail is None:
            error_detail = ErrorDetail(title="Bad Request", code="BAD_REQUEST", status=400, details=[message])
        super().__init__(message, error_detail)


class InternalServerException(AppException):
    def __init__(self, message: str = "Something went wrong. Please try again later", error_detail: Optional[ErrorDetail] = None):
        if error_detail is None:
            error_detail = ErrorDetail(title="Internal Server Error", code="INTERNAL_ERROR", status=500, details=[message])
        super().__init__(message, error_detail)


class ServiceUnavailableException(AppException):
    def __init__(self, message: str = "The service is temporarily unavailable. Please try again later", error_detail: Optional[ErrorDetail] = None):
        if error_detail is None:
            error_detail = ErrorDetail(title="Service Unavailable", code="SERVICE_UNAVAILABLE", status=503, details=[message])
        super().__init__(message, error_detail)
```

---

### `src/shared/exceptions/error_handlers.py`

```python
"""
Global error handlers for FastAPI application.
Catches all exceptions and returns consistent API responses.
"""

import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src.shared.responses.api_response import ApiResponse, ErrorDetail
from src.shared.exceptions.exceptions import AppException

logger = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:

    @app.exception_handler(AppException)
    async def handle_app_exception(_req: Request, exc: AppException):
        response = ApiResponse.failure(error=exc.error_detail, message=exc.message)
        return JSONResponse(
            status_code=exc.error_detail.status,
            content=response.model_dump(exclude_none=True, by_alias=True),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(_req: Request, exc: RequestValidationError):
        builder = ErrorDetail.builder("Validation Failed", "VALIDATION_ERROR", 400)
        for error in exc.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            builder.add_field_error(field, error["msg"])
        response = ApiResponse.failure(
            error=builder.build(),
            message="Please check your input and try again",
        )
        return JSONResponse(status_code=400, content=response.model_dump(exclude_none=True, by_alias=True))

    @app.exception_handler(ValidationError)
    async def handle_pydantic_validation_error(_req: Request, exc: ValidationError):
        builder = ErrorDetail.builder("Validation Failed", "VALIDATION_ERROR", 400)
        for error in exc.errors():
            field = ".".join(str(loc) for loc in error["loc"])
            builder.add_field_error(field, error["msg"])
        response = ApiResponse.failure(
            error=builder.build(),
            message="Please check your input and try again",
        )
        return JSONResponse(status_code=400, content=response.model_dump(exclude_none=True, by_alias=True))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(req: Request, exc: StarletteHTTPException):
        user_messages = {
            400: "Please check your request and try again",
            401: "Please log in to continue",
            403: "You don't have permission to perform this action",
            404: "The page you're looking for doesn't exist",
            405: "This action is not allowed",
            500: "Something went wrong. Please try again later",
            503: "The service is temporarily unavailable",
        }
        detail_messages = {
            404: f"{req.method} {req.url.path} was not found",
            405: f"{req.method} is not allowed for {req.url.path}",
        }
        error = ErrorDetail(
            title=str(exc.detail),
            code=str(exc.detail).upper().replace(" ", "_"),
            status=exc.status_code,
            details=[detail_messages.get(exc.status_code, str(exc.detail))],
        )
        response = ApiResponse.failure(
            error=error,
            message=user_messages.get(exc.status_code, "An error occurred. Please try again"),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=response.model_dump(exclude_none=True, by_alias=True),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_req: Request, exc: Exception):
        logger.error(f"Unexpected error: {exc}", exc_info=True)
        error = ErrorDetail(
            title="Internal Server Error",
            code="INTERNAL_ERROR",
            status=500,
            details=["An unexpected error occurred. Please try again later."],
        )
        response = ApiResponse.failure(
            error=error,
            message="Something went wrong. Please try again later",
        )
        return JSONResponse(status_code=500, content=response.model_dump(exclude_none=True, by_alias=True))
```

---

### `main.py`

```python
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "src.core.factory:create_app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        factory=True,
    )
```

---

### `alembic/env.py`

```python
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

from src.configs import database
from src.shared.database.base_model import Base

# Import your models here so Alembic can detect them
# Example:
#   from src.modules.users.domain.models.user import User
#   from src.modules.posts.domain.models.post import Post


config = context.config

# Set the database URL from our config system
config.set_main_option("sqlalchemy.url", database.url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in offline mode (generates SQL without DB connection)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in online mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

---

### `.env.example`

```dotenv
# ──────────────────────────────────────────────
# Application
# ──────────────────────────────────────────────
APP_NAME=MyApp
APP_VERSION=0.1.0
# Set to true to enable FastAPI debug mode and auto-reload
DEBUG=false
# One of: development, staging, production
ENVIRONMENT=development

# ──────────────────────────────────────────────
# Database
# ──────────────────────────────────────────────
# Async PostgreSQL URL — must use asyncpg driver
# Format: postgresql+asyncpg://user:password@host:port/dbname
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/myapp

# Connection pool settings
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
# Set to true to echo all SQL statements (useful for debugging)
DB_ECHO=false

# ──────────────────────────────────────────────
# Security — JWT
# ──────────────────────────────────────────────
# Generate a strong random key: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=replace-this-with-a-secure-random-string
JWT_ALGORITHM=HS256
# Access token lifetime in minutes
ACCESS_TOKEN_EXPIRE_MINUTES=30
# Refresh token lifetime in days
REFRESH_TOKEN_EXPIRE_DAYS=7

# ──────────────────────────────────────────────
# Server — CORS
# ──────────────────────────────────────────────
# Comma-separated list of allowed origins, or * for all
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
CORS_ALLOW_CREDENTIALS=true
# Comma-separated list of allowed HTTP methods, or * for all
CORS_ALLOW_METHODS=*
# Comma-separated list of allowed headers, or * for all
CORS_ALLOW_HEADERS=*

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
# One of: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO
# Path to the log file (directory will be created if it does not exist)
LOG_FILE_PATH=logs/app.log
```

---

### `.gitignore`

```gitignore
# Environment
.env
.env.*
!.env.example
venv/
.venv/

# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
*.egg

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Auto-generated config stubs
*.pyi

# Alembic — ignore pycache but keep migration files
alembic/versions/__pycache__/
!alembic/versions/*.py

# Logs
*.log
logs/
```

---

## 4. Lifespan Rules

The `lifespan` function in `src/core/lifespan.py` **must only**:

1. **Startup**: Configure logging (file + stream handlers, log level from config, create log directory if absent).
2. **Startup**: The async DB engine and session factory are initialised at import time in `engine.py` — the lifespan does not explicitly start the pool, but it logs that the DB pool is ready.
3. **Shutdown**: Call `await engine.dispose()` to release all DB connections cleanly.

**Nothing else belongs in lifespan.** Do not load ML models, seed the database, start background tasks, connect to external services, or run recovery routines in this function. Those are application-specific concerns and belong in the relevant module's initialisation logic called from `_register_routers` or a dedicated startup hook added per project.

---

## 5. `application.yaml` Sections

Only five top-level sections are part of the base:

| Section | Purpose |
|---|---|
| `application` | App name, version, debug flag, environment |
| `database` | PostgreSQL async connection URL and pool settings |
| `security.jwt` | JWT secret, algorithm, token lifetimes |
| `server.cors` | CORS origins, credentials, methods, headers |
| `logging` | Log level, format string, file path |

**Pipe format rules:**

- `"${ENV_VAR:default} | type"` — optional env var with a fallback default
- `"${ENV_VAR} | type | required"` — env var must be set; startup aborts if missing
- `"literal_value | type"` — static value, never from env
- Supported types: `str`, `int`, `float`, `bool`, `list`
- `bool` coerces `"true"`, `"1"`, `"yes"`, `"on"` to `True` (case-insensitive)
- `list` splits on commas and strips whitespace from each item

---

## 6. `factory.py` Rules

`_register_routers` must remain an empty placeholder in the base scaffold:

```python
def _register_routers(app: FastAPI) -> None:
    # Register your domain routers here
    pass
```

No imports from `src.modules` belong in `factory.py` at the base level. Each project populates this function with its own router registrations after scaffolding.

---

## 7. Key Patterns to Preserve Exactly

### Config pipe format with type casting and required validation

Values in `application.yaml` use a `"${VAR:default} | type"` pipe syntax. The loader parses this in `loader.py:_parse_pipe`, resolves env vars in `_resolve_value`, casts with `_cast`, and collects all errors before raising a single `ConfigError`. Never short-circuit on the first error — always collect all errors and report them together.

### `__init__.pyi` stub generation for IDE autocomplete

On every boot, `generate.py:generate_stub` reads `application.yaml` and writes `src/configs/__init__.pyi`. This gives IDEs full attribute-level autocomplete for config sections (e.g. `from src.configs import database; database.url`). The `.pyi` file is auto-generated and must be gitignored (`*.pyi` in `.gitignore`).

### `BaseModel` with UUID primary key, `created_at`, `updated_at`

```python
class BaseModel(Base):
    __abstract__ = True
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), server_onupdate=func.now())
```

The `id` uses PostgreSQL's `gen_random_uuid()` as a server default — the application never generates UUIDs itself.

### `BaseRepository[T]` generic with full CRUD, paginate, count, ordering

- `get_by_id(id)` — uses `session.get` (identity map aware)
- `get_one(**filters)` — `filter_by` returning first match
- `exists(**filters)` — `COUNT` query returning bool
- `get_all(skip, limit, order_by, descending, **filters)` — offset/limit with optional ordering
- `paginate(page, page_size, order_by, descending, **filters)` — returns `(records, total_count)` tuple; uses a subquery count
- `count(**filters)` — standalone count
- `create(entity)` — `add` + `flush` + `refresh`
- `create_many(entities)` — `add_all` + `flush` + `refresh` each
- `update(entity, data)` — `setattr` loop with `AttributeError` guard + `flush` + `refresh`
- `delete(entity)` — `delete` + `flush`

All writes use `flush` (not `commit`) — the session transaction is owned by the dependency (`get_db`).

### `ApiResponse[T]` with `ok`/`failure` static methods

```python
ApiResponse.ok(value=data, message="optional")
ApiResponse.failure(error=error_detail, message="optional")
```

`value` and `error` are mutually exclusive — a `model_validator` enforces this. Responses are serialised with `model_dump(exclude_none=True, by_alias=True)`.

### `ErrorDetail` with Builder pattern

```python
error = (
    ErrorDetail.builder("Validation Failed", "VALIDATION_ERROR", 400)
    .add_field_error("email", "Invalid email format")
    .add_detail("Fix the highlighted fields")
    .build()
)
```

`field_errors` is serialised as `fieldErrors` (camelCase alias). Always use `by_alias=True` when dumping.

### `PaginatedResponse[T]` with `PaginationInfo`

```python
PaginatedResponse.ok(value=items, page=1, total=42, page_size=20)
```

`PaginationInfo` auto-computes `total_pages` via `model_validator(mode="before")`. Fields `page_size` and `total_pages` are serialised as `pageSize` and `totalPages`.

### `get_db` (transactional) and `get_db_readonly` (no transaction) dependencies

```python
# Transactional — use for any write or read-then-write operation
async def endpoint(db: AsyncSession = Depends(get_db)): ...

# Read-only — no transaction overhead, safe for pure reads
async def endpoint(db: AsyncSession = Depends(get_db_readonly)): ...
```

`get_db` opens a `session.begin()` context — SQLAlchemy auto-commits on clean exit and rolls back on exception. `get_db_readonly` opens a bare session with no explicit transaction.

### `PaginationParams` dataclass with `skip` and `limit` properties

```python
async def list_items(
    pagination: PaginationParams = Depends(get_pagination),
    db: AsyncSession = Depends(get_db_readonly),
):
    items, total = await repo.paginate(
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return PaginatedResponse.ok(value=items, page=pagination.page, total=total, page_size=pagination.page_size)
```

Query parameters are `page` (default 1) and `pageSize` (default 20, max 100).

### Raw ASGI `RequestLoggingMiddleware`

**Must NOT use `BaseHTTPMiddleware`**. The raw ASGI implementation in `middleware.py` intercepts `send` to capture the status code without buffering the response body. `BaseHTTPMiddleware` buffers the entire response, which breaks Server-Sent Events (SSE) streaming. Always use the raw ASGI pattern for any middleware that should be SSE-compatible.

### Global error handlers

Five handlers registered in `error_handlers.py`:

| Handler | Catches | Status |
|---|---|---|
| `AppException` | All domain exceptions inheriting from `AppException` | From `error_detail.status` |
| `RequestValidationError` | FastAPI request body/query/path validation failures | 400 |
| `ValidationError` | Pydantic model validation errors raised in business logic | 400 |
| `StarletteHTTPException` | FastAPI/Starlette HTTP errors (404, 405, etc.) | From `exc.status_code` |
| `Exception` | All unhandled exceptions (catch-all) | 500 |

All handlers return `ApiResponse.failure(...)` serialised as JSON with `exclude_none=True, by_alias=True`.

### Exception hierarchy

All custom exceptions inherit from `AppException`:

```
AppException (500)
├── NotFoundException (404)
├── ValidationException (400)
├── AuthenticationException (401)
├── AuthorizationException (403)
├── ConflictException (409)
├── BadRequestException (400)
├── InternalServerException (500)
└── ServiceUnavailableException (503)
```

Each subclass sets its own default `title`, `code`, `status`, and `details` on `ErrorDetail`. Any can be overridden by passing a custom `error_detail` argument.

---

## 8. Alembic Setup

### `alembic/env.py` key points

- Uses `async_engine_from_config` + `asyncio.run` for async migrations
- Database URL is pulled from the config system (`from src.configs import database`) — not hardcoded in `alembic.ini`
- `target_metadata = Base.metadata` — Alembic inspects all models that have been imported by the time this line runs
- The model import block is a **placeholder** — add your model imports there before running `alembic revision --autogenerate`

### Initialise Alembic

Run once in the project root to create `alembic/` and `alembic.ini`:

```bash
alembic init alembic
```

Then replace the generated `alembic/env.py` with the file shown in section 3.

### `alembic.ini` — only change needed

The `sqlalchemy.url` line in `alembic.ini` is overridden at runtime by `env.py`, so it can be left as a placeholder:

```ini
sqlalchemy.url = driver://user:pass@localhost/dbname
```

### Running migrations

```bash
# Generate a new migration after adding/changing models
alembic revision --autogenerate -m "describe the change"

# Apply all pending migrations
alembic upgrade head

# Roll back one migration
alembic downgrade -1
```

**Before running `--autogenerate`**, ensure your model classes are imported in the `# Import your models here` block in `alembic/env.py`. Alembic cannot detect tables it has never seen.

---

## 9. `.env.example`

```dotenv
# ──────────────────────────────────────────────
# Application
# ──────────────────────────────────────────────
APP_NAME=MyApp
APP_VERSION=0.1.0
# Set to true to enable FastAPI debug mode and auto-reload
DEBUG=false
# One of: development, staging, production
ENVIRONMENT=development

# ──────────────────────────────────────────────
# Database
# ──────────────────────────────────────────────
# Async PostgreSQL URL — must use asyncpg driver
# Format: postgresql+asyncpg://user:password@host:port/dbname
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/myapp

# Connection pool settings
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
# Set to true to echo all SQL statements (useful for debugging)
DB_ECHO=false

# ──────────────────────────────────────────────
# Security — JWT
# ──────────────────────────────────────────────
# Generate a strong random key: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=replace-this-with-a-secure-random-string
JWT_ALGORITHM=HS256
# Access token lifetime in minutes
ACCESS_TOKEN_EXPIRE_MINUTES=30
# Refresh token lifetime in days
REFRESH_TOKEN_EXPIRE_DAYS=7

# ──────────────────────────────────────────────
# Server — CORS
# ──────────────────────────────────────────────
# Comma-separated list of allowed origins, or * for all
CORS_ORIGINS=http://localhost:3000,http://localhost:5173
CORS_ALLOW_CREDENTIALS=true
# Comma-separated list of allowed HTTP methods, or * for all
CORS_ALLOW_METHODS=*
# Comma-separated list of allowed headers, or * for all
CORS_ALLOW_HEADERS=*

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
# One of: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO
# Path to the log file (directory will be created if it does not exist)
LOG_FILE_PATH=logs/app.log
```

---

## 10. Setup Instructions

### Step 1 — Create and activate a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows
```

### Step 2 — Install packages

```bash
pip install fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" asyncpg alembic \
    pydantic pydantic-settings python-dotenv pyyaml
```

### Step 3 — Copy `.env.example` and fill in values

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

- `DATABASE_URL` — your PostgreSQL connection string
- `JWT_SECRET_KEY` — a random 32-byte hex string (`python -c "import secrets; print(secrets.token_hex(32))"`)

### Step 4 — Initialise Alembic

If starting from scratch (no `alembic/` directory yet):

```bash
alembic init alembic
```

Replace the generated `alembic/env.py` with the file in section 3. Then add your model imports to the placeholder block.

### Step 5 — Create the initial migration and apply it

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

### Step 6 — Run the project

```bash
python main.py
```

Or directly with uvicorn:

```bash
uvicorn "src.core.factory:create_app" --host 127.0.0.1 --port 8000 --reload --factory
```

The API will be available at `http://127.0.0.1:8000`. Interactive docs are at `http://127.0.0.1:8000/docs`.
