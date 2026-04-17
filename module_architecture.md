# Module Architecture Guide

This document is the single source of truth for building any new module in this project. Every section is derived from the live codebase — specifically the `auth` module as the canonical reference. When building a new module, reproduce this structure adapted to the new domain. Never copy auth-specific logic.

---

## 1. Module Folder Structure

```
src/modules/{module_name}/
├── domain/
│   ├── models/
│   │   ├── __init__.py          # Re-exports all models and enums from this folder
│   │   ├── enums.py             # All enums for this module (one file for all enums)
│   │   └── {entity}.py          # One file per ORM model class
│   ├── repositories/
│   │   ├── __init__.py          # Re-exports all repository classes
│   │   └── {entity}_repository.py  # One file per repository class
│   ├── services/
│   │   ├── __init__.py          # Re-exports all service classes
│   │   └── {entity}_service.py  # One file per service class
│   └── __init__.py              # Re-exports everything: models, enums, repos, services
├── internal/
│   ├── __init__.py              # Exposes what the module's own code imports from here
│   └── {helper}.py              # Seeders, background loops, private utilities
├── presentation/
│   ├── controllers/
│   │   ├── __init__.py          # Empty
│   │   └── {entity}_controller.py  # One file per router
│   ├── dtos/
│   │   ├── __init__.py          # Empty
│   │   ├── requests.py          # All request DTO classes for this module
│   │   └── responses.py         # All response DTO classes for this module
│   ├── __init__.py              # Re-exports routers by aliased name
│   └── dependencies.py          # Service factory functions and role guard aliases
└── __init__.py                  # Re-exports routers for factory.py to consume
```

**Folder responsibilities in one line each:**

| Folder | Responsibility |
|--------|----------------|
| `domain/models/` | SQLAlchemy ORM models and their enums |
| `domain/repositories/` | Data access — query and persist domain models |
| `domain/services/` | Business logic, validation, and orchestration |
| `internal/` | Module-private helpers, background tasks, and startup seeders |
| `presentation/controllers/` | FastAPI routers and HTTP endpoint handlers |
| `presentation/dtos/` | Pydantic request and response shapes |
| `presentation/` | FastAPI wiring: service factories, auth guards |

If a module has no background tasks or seeders, `internal/` still exists with an empty or minimal `__init__.py`.

---

## 2. How the Domain Layer Works

### Models

**Base class:** Every model inherits from `src.shared.database.BaseModel`.

`BaseModel` is an abstract SQLAlchemy class that auto-provides three columns on every table:

```python
# src/shared/database/base_model.py (for reference — do not copy)
class BaseModel(Base):
    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), server_onupdate=func.now()
    )
```

Never redeclare `id`, `created_at`, or `updated_at` in a model.

**Column declaration — always use `Mapped[type]` + `mapped_column()`:**

```python
import uuid
from sqlalchemy import String, Boolean, Integer, Float, Text, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.shared.database import BaseModel
from src.modules.mymodule.domain.models.enums import MyStatus

class MyModel(BaseModel):
    __tablename__ = "my_table"

    # String column — always specify max length
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # Optional column — use `str | None` and nullable=True
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Foreign key
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Enum column — always name the enum with pattern {field}_enum
    status: Mapped[MyStatus] = mapped_column(
        SAEnum(MyStatus, name="my_status_enum"), nullable=False, default=MyStatus.PENDING
    )

    # JSON column (PostgreSQL JSONB for structured data)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Relationship — lazy loading strategy depends on access pattern
    items = relationship("MyItem", back_populates="my_model", cascade="all, delete-orphan", lazy="selectin")
```

**Enums — always in `enums.py`, always inherit `(str, enum.Enum)`:**

```python
import enum

class MyStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
```

Inheriting `str` ensures enum values serialize to strings in JSON responses and work with SQLAlchemy's `SAEnum` without additional configuration.

**Model-level properties and methods** — add when the logic only reads the model's own fields:

```python
@property
def is_valid(self) -> bool:
    return not self.is_revoked and self.expires_at > datetime.now(timezone.utc)

def revoke(self) -> None:
    self.is_revoked = True
```

Do not add methods that call the database, other services, or external dependencies. Those belong in services.

---

### Repositories

**Base class:** All repositories extend `BaseRepository[T]` from `src.shared.database`.

`BaseRepository` is `Generic[T]` where `T` is bound to `BaseModel`. It provides the full set of standard data-access operations.

**Available base methods:**

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_by_id` | `(id: UUID) -> T \| None` | Fetch by primary key |
| `get_one` | `(**filters) -> T \| None` | Fetch first match by keyword filters |
| `exists` | `(**filters) -> bool` | True if any record matches |
| `get_all` | `(skip, limit, order_by, descending, **filters) -> Sequence[T]` | Offset/limit list |
| `paginate` | `(page, page_size, order_by, descending, **filters) -> Tuple[Sequence[T], int]` | Returns `(records, total_count)` |
| `count` | `(**filters) -> int` | Count matching records |
| `create` | `(entity: T) -> T` | Insert and return refreshed entity |
| `create_many` | `(entities: Sequence[T]) -> Sequence[T]` | Bulk insert |
| `update` | `(entity: T, data: Dict[str, Any]) -> T` | Apply dict of field updates |
| `delete` | `(entity: T) -> None` | Delete entity |

**`__init__` is always declared with model class + session injection — no exceptions:**

```python
from sqlalchemy.ext.asyncio import AsyncSession
from src.shared.database import BaseRepository
from src.modules.orders.domain.models.order import Order

class OrderRepository(BaseRepository[Order]):
    def __init__(self, session: AsyncSession):
        super().__init__(Order, session)
```

**Custom query methods** — write raw SQLAlchemy `select()` statements for anything beyond simple `filter_by` key-value matching:

```python
from sqlalchemy import select, update

async def get_by_customer_email(self, email: str) -> Order | None:
    stmt = select(Order).where(Order.customer_email == email)
    result = await self.session.execute(stmt)
    return result.scalars().first()

async def get_active_for_customer(self, customer_id: UUID) -> Sequence[Order]:
    stmt = (
        select(Order)
        .where(Order.customer_id == customer_id, Order.status == OrderStatus.ACTIVE)
        .order_by(Order.created_at.desc())
    )
    result = await self.session.execute(stmt)
    return result.scalars().all()

async def cancel_all_for_customer(self, customer_id: UUID) -> None:
    stmt = (
        update(Order)
        .where(Order.customer_id == customer_id, Order.status == OrderStatus.ACTIVE)
        .values(status=OrderStatus.CANCELLED)
    )
    await self.session.execute(stmt)
```

**When to use base methods vs writing custom statements:**

- Use `exists(**filters)`, `paginate(...)`, `get_by_id(...)`, `create(...)`, `update(...)`, `delete(...)` for any operation expressible as simple equality filters.
- Write a custom `select()` for: multi-condition `where` clauses, `ilike` (case-insensitive search), `OR` conditions, joins, bulk `update()` statements, complex ordering, or returning aggregate values.

---

### Services

**Constructor injection — FastAPI `Depends` never appears in a service:**

```python
class OrderService:
    def __init__(self, order_repo: OrderRepository, item_repo: OrderItemRepository):
        self.order_repo = order_repo
        self.item_repo = item_repo
```

Repositories are fully instantiated before they reach the service. The service never creates its own session or repository.

**All business logic lives in the service.** Validation, uniqueness checks, state machine transitions, existence guards, conflict detection — none of this belongs in repositories or controllers.

**Services return plain models, tuples for paginated results, or `None` — never HTTP responses:**

```python
async def get_order(self, order_id: UUID) -> Order:                          # single entity
async def get_orders(self, page: int, page_size: int) -> Tuple[Sequence[Order], int]:  # paginated
async def create_order(self, ...) -> Order:                                   # created entity
async def delete_order(self, order_id: UUID) -> None:                        # void
```

**Exception pattern — two forms:**

**Form 1: `ErrorDetail.builder()` — use when attaching per-field errors**

```python
from src.shared.exceptions import ConflictException
from src.shared.responses import ErrorDetail

error = ErrorDetail.builder("Creation Failed", "EMAIL_EXISTS", 409)
error.add_field_error("email", "Email already registered")
raise ConflictException(
    message="This email is already registered",
    error_detail=error.build(),
)
```

The builder API:
- `.add_detail(str)` — appends to the top-level `details` list
- `.add_field_error(field: str, error: str)` — appends to `fieldErrors[field]`
- `.add_field_errors(field: str, errors: List[str])` — appends multiple errors for one field
- `.build()` — returns a complete `ErrorDetail` instance

**Form 2: Direct `ErrorDetail(...)` — use when there are no per-field errors**

```python
from src.shared.exceptions import NotFoundException
from src.shared.responses import ErrorDetail

raise NotFoundException(
    message="Order not found",
    error_detail=ErrorDetail(
        title="Not Found",
        code="ORDER_NOT_FOUND",
        status=404,
        details=[f"No order found with id {order_id}"],
    ),
)
```

Use `.builder()` when the error needs to surface which specific fields failed. Use direct `ErrorDetail(...)` for all other errors — resource not found, wrong state, authentication failure, etc.

---

## 3. How the Internal Layer Works

**What belongs in `internal/`:**

- Background tasks that loop forever (cleanup jobs, polling loops, periodic sweeps)
- Startup seeders that populate default data on first run
- Module-private crypto/hashing utilities (password hasher, JWT encoder)
- Module-private ML or algorithmic helpers (feature engineering, inference wrappers)
- One-off helpers that are only ever needed inside this module

**What does NOT belong in `internal/`:**

- Anything that another module imports — move that to `src/shared/`
- Repository classes — those go in `domain/repositories/`
- Business logic — that goes in `domain/services/`
- Configuration — that goes in `src/configs/`

**`internal/__init__.py`** exposes exactly what the module's own code needs to import from here. Sub-modules are imported as modules (not their contents) when they are utility namespaces:

```python
# Expose as module namespaces (for util modules called as password_hasher.hash_password(...))
from src.modules.auth.internal import password_hasher, token_provider

# Expose as callable functions (for startup registration in lifespan.py)
from src.modules.auth.internal.admin_seeder import seed_admin
from src.modules.auth.internal.token_cleanup import start_token_cleanup

__all__ = ["password_hasher", "token_provider", "seed_admin", "start_token_cleanup"]
```

**Startup registration rule:** If something must run at application startup (seeder, background loop, data recovery), it lives in `internal/` and is wired into `src/core/lifespan.py` inside the `@asynccontextmanager async def lifespan(app)` function.

Background tasks are created with `asyncio.create_task()` and must be cancelled in the shutdown block:

```python
# In src/core/lifespan.py

from src.modules.mymodule.internal.my_seeder import seed_defaults
from src.modules.mymodule.internal.my_cleanup import start_cleanup

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    await seed_defaults()

    cleanup_task = asyncio.create_task(start_cleanup())

    yield

    # ── Shutdown ──
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
```

A background loop must handle `asyncio.CancelledError` to shut down cleanly:

```python
async def start_cleanup() -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            async with async_session() as session:
                async with session.begin():
                    repo = MyRepository(session)
                    await repo.cleanup_stale()
        except Exception as e:
            logger.error("Cleanup failed: %s", e)
```

---

## 4. How the Presentation Layer Works

### Dependencies (`presentation/dependencies.py`)

**Service factory functions — always inject via `Depends(get_db)`:**

```python
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from src.shared.database import get_db
from src.modules.orders.domain.repositories.order_repository import OrderRepository
from src.modules.orders.domain.services.order_service import OrderService

def get_order_service(session: AsyncSession = Depends(get_db)) -> OrderService:
    return OrderService(
        order_repo=OrderRepository(session),
    )
```

Each factory:
1. Receives a session from `get_db` (which provides a transactional session — auto-commit on success, rollback on error)
2. Instantiates all needed repositories with that session
3. Constructs and returns the service

Never pass a raw `session` or `repository` to a controller. The controller only receives the service.

**`get_current_user`** is defined in `src.modules.auth.presentation.dependencies` and imported directly:

```python
from src.modules.auth.presentation.dependencies import get_current_user, require_role
from src.modules.auth.domain.models.enums import Role
from src.modules.auth.domain.models.user import User
```

**`require_role(*roles)` guard — defined in auth, used everywhere:**

```python
# Definition in auth/presentation/dependencies.py
def require_role(*allowed_roles: Role):
    async def _guard(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            role_names = ", ".join(r.value for r in allowed_roles)
            raise AuthorizationException(
                message="You don't have permission to perform this action",
                error_detail=ErrorDetail(
                    title="Access Denied",
                    code="INSUFFICIENT_ROLE",
                    status=403,
                    details=[f"Required role(s): {role_names}"],
                ),
            )
        return current_user
    return _guard

# Convenience alias — define in the module's own dependencies.py
require_admin = require_role(Role.ADMIN)
```

If the module only ever needs one specific guard, create the alias at the top of `dependencies.py` so controllers import the alias, not the raw `require_role(...)` call.

---

### DTOs

**Request DTOs — `pydantic BaseModel` with `Field` validation:**

```python
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

class CreateOrderRequest(BaseModel):
    customer_name: str = Field(min_length=1, max_length=100)
    amount: float = Field(gt=0, le=1_000_000)
    notes: Optional[str] = Field(None, max_length=1000)
    status: Optional[str] = Field(None, pattern="^(PENDING|ACTIVE)$")
```

- Use `Field(...)` for all constraints: `min_length`, `max_length`, `ge`, `le`, `gt`, `lt`, `pattern`
- Optional fields are typed `Optional[X]` and default to `None`
- Use `pattern=` for enum-like string fields when the enum lives only in the request (no DB enum); use actual `Enum` type for anything with a DB-backed enum

**Response DTOs — camelCase aliases, static factory, `Config` block:**

```python
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional
from src.modules.orders.domain.models.order import Order

class OrderResponse(BaseModel):
    id: UUID
    customer_name: str = Field(alias="customerName")
    amount: float
    status: str
    notes: Optional[str] = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    class Config:
        populate_by_name = True
        from_attributes = True

    @staticmethod
    def from_order(order: Order) -> "OrderResponse":
        return OrderResponse(
            id=order.id,
            customerName=order.customer_name,
            amount=order.amount,
            status=order.status.value,       # always .value for enums
            notes=order.notes,
            createdAt=order.created_at,
            updatedAt=order.updated_at,
        )
```

Rules for response DTOs:
- Every multi-word `snake_case` field gets a camelCase `alias`
- `Config` always has `populate_by_name = True` and `from_attributes = True`
- Always add a static `from_{entity}(entity) -> "XxxResponse"` factory method
- The factory passes values using the **alias** names as keyword arguments (e.g., `customerName=`, `createdAt=`), not the field names
- Enum values are always serialized as `.value` (the string) in the factory

When a response composes nested responses, the nested factory is called inline inside the parent factory:

```python
class OrderDetailResponse(BaseModel):
    ...
    items: List[OrderItemResponse] = Field(alias="items")

    @staticmethod
    def from_order(order: Order) -> "OrderDetailResponse":
        return OrderDetailResponse(
            ...
            items=[OrderItemResponse.from_item(i) for i in order.items],
        )
```

---

### Controllers

**Router declaration — declare dependencies at router level for uniform guards:**

```python
from fastapi import APIRouter, Depends
from src.modules.orders.presentation.dependencies import require_admin, get_order_service

# All routes in this router require admin
router = APIRouter(dependencies=[Depends(require_admin)])
```

Use router-level `dependencies=[...]` when every endpoint needs the same guard. Use individual endpoint-level `Depends` when routes have different role requirements, or when you need the resolved `User` object as a variable inside the handler.

**Standard endpoint patterns:**

```python
from src.shared.responses import ApiResponse, PaginatedResponse
from src.shared.database.pagination import PaginationParams, get_pagination

# List with pagination
@router.get("")
async def list_orders(
    pagination: PaginationParams = Depends(get_pagination),
    service: OrderService = Depends(get_order_service),
):
    orders, total = await service.get_orders(page=pagination.page, page_size=pagination.page_size)
    return PaginatedResponse.ok(
        value=[OrderResponse.from_order(o) for o in orders],
        page=pagination.page,
        total=total,
        page_size=pagination.page_size,
    )

# Single record
@router.get("/{order_id}")
async def get_order(
    order_id: UUID,
    service: OrderService = Depends(get_order_service),
):
    order = await service.get_order(order_id)
    return ApiResponse.ok(value=OrderResponse.from_order(order))

# Create
@router.post("", status_code=201)
async def create_order(
    body: CreateOrderRequest,
    service: OrderService = Depends(get_order_service),
):
    order = await service.create_order(
        customer_name=body.customer_name,
        amount=body.amount,
        notes=body.notes,
    )
    return ApiResponse.ok(value=OrderResponse.from_order(order), message="Order created")

# Partial update
@router.patch("/{order_id}")
async def update_order(
    order_id: UUID,
    body: UpdateOrderRequest,
    service: OrderService = Depends(get_order_service),
):
    order = await service.update_order(
        order_id=order_id,
        customer_name=body.customer_name,
        amount=body.amount,
    )
    return ApiResponse.ok(value=OrderResponse.from_order(order), message="Order updated")

# Delete
@router.delete("/{order_id}", status_code=200)
async def delete_order(
    order_id: UUID,
    service: OrderService = Depends(get_order_service),
):
    await service.delete_order(order_id)
    return ApiResponse.ok(value=None, message="Order deleted")
```

Every endpoint returns either `ApiResponse.ok(value=..., message=...)` or `PaginatedResponse.ok(value=..., page=..., total=..., page_size=...)`. The `message` argument is optional on read endpoints but required on mutating endpoints.

**`presentation/__init__.py`** re-exports all routers from this module with explicit names:

```python
from src.modules.orders.presentation.controllers.order_controller import router as order_router

__all__ = ["order_router"]
```

If the module has multiple controllers, re-export all of them here.

---

## 5. Module Root `__init__.py`

The module root `__init__.py` re-exports routers for `factory.py` to consume. It does not export domain models, repositories, or services — those are imported by absolute path when genuinely needed.

```python
from src.modules.orders.presentation.controllers.order_controller import router as order_router

__all__ = ["order_router"]
```

If the module has multiple controllers:

```python
from src.modules.orders.presentation.controllers.order_controller import router as order_router
from src.modules.orders.presentation.controllers.item_controller import router as order_item_router

__all__ = ["order_router", "order_item_router"]
```

---

## 6. New Module Registration Checklist

Every time a module is completed, do ALL of the following steps without being asked.

- [ ] **`presentation/__init__.py`** — export all routers by name:
  ```python
  from src.modules.{name}.presentation.controllers.{name}_controller import router as {name}_router
  __all__ = ["{name}_router"]
  ```

- [ ] **Module root `__init__.py`** — mirror the same exports:
  ```python
  from src.modules.{name}.presentation.controllers.{name}_controller import router as {name}_router
  __all__ = ["{name}_router"]
  ```

- [ ] **`src/core/factory.py` `_register_routers()`** — add import and `include_router`:
  ```python
  from src.modules.{name} import {name}_router
  app.include_router({name}_router, prefix="/api/v1/{name}s", tags=["{Name}s"])
  ```

- [ ] **`alembic/env.py`** — add imports for all new SQLAlchemy models so Alembic detects table changes. Place them in the models import section alongside existing model imports.

- [ ] **`src/core/lifespan.py`** — if the module has startup tasks (seeders, background loops, recovery routines): import them and wire them into the `lifespan` function. Create background tasks with `asyncio.create_task()` before `yield`; cancel them after `yield`.

- [ ] **Generate and apply the migration:**
  ```bash
  alembic revision --autogenerate -m "add {module_name} tables"
  alembic upgrade head
  ```

---

## 7. Loose Coupling Rules

**The general rule:** A module must never import from another module's `domain/` or `internal/` layer.

**The two permitted exceptions:**

**Exception 1 — Auth cross-cutting concerns.** Every module's `presentation/` layer may import from `src.modules.auth.presentation.dependencies` (`get_current_user`, `require_role`) and `src.modules.auth.domain.models` (`Role`, `User`). Auth provides application-wide authentication and authorization — it is the one module all others are allowed to depend on.

```python
# Allowed in any module's presentation layer
from src.modules.auth.presentation.dependencies import get_current_user, require_role
from src.modules.auth.domain.models.enums import Role
from src.modules.auth.domain.models.user import User
```

**Exception 2 — Cross-module repository access for data composition.** When a service must verify or fetch data that belongs to another domain as part of its own operation (e.g., `PredictionService` must validate that a `MedicalRecord` exists before running inference), that service may import the foreign repository class directly and use it locally within the same database session. Do not create service-to-service calls; do not wrap the foreign repo in your own service. Import the repository and query it directly.

```python
# Allowed: predictions service importing a patients repository
from src.modules.patients.domain.repositories.medical_record_repository import MedicalRecordRepository

class PredictionService:
    def __init__(self, prediction_repo: PredictionRepository, medical_record_repo: MedicalRecordRepository):
        ...
```

The corresponding factory in `dependencies.py` instantiates the foreign repository with the same session:

```python
def get_prediction_service(session: AsyncSession = Depends(get_db)) -> PredictionService:
    return PredictionService(
        prediction_repo=PredictionRepository(session),
        medical_record_repo=MedicalRecordRepository(session),  # foreign repo, same session
    )
```

**What every module only imports from:**
- `src/shared/` — database, exceptions, responses, pagination
- `src/configs/` — application configuration
- `src.modules.auth` — auth/authz infrastructure (Exception 1)
- Another module's repository — only for data composition (Exception 2, keep it rare)

Cross-module data sharing goes through the database. Never call another module's service methods.

---

## 8. Naming Conventions

| Artifact | Convention | Example |
|----------|-----------|---------|
| Module folder | `snake_case` | `patient_records/`, `lab_results/` |
| Model class | `PascalCase` | `Patient`, `MedicalRecord`, `LabResult` |
| Model file | `snake_case.py` | `patient.py`, `medical_record.py` |
| Enum class | `PascalCase` | `PatientStatus`, `RecordType`, `SimulationStatus` |
| Enum values | `UPPER_SNAKE_CASE` | `ACTIVE`, `IN_PROGRESS`, `NOT_FOUND` |
| SQLAlchemy enum name (DB) | `{field_name}_enum` | `role_enum`, `token_type_enum`, `doctor_decision_enum` |
| Repository class | `{Model}Repository` | `PatientRepository`, `MedicalRecordRepository` |
| Repository file | `{model}_repository.py` | `patient_repository.py`, `token_repository.py` |
| Service class | `{Entity}Service` | `PatientService`, `AuthService`, `UserManagementService` |
| Service file | `{entity}_service.py` | `patient_service.py`, `auth_service.py` |
| Request DTO class | `{Action}{Entity}Request` | `CreatePatientRequest`, `UpdateOrderRequest` |
| Response DTO class | `{Entity}Response`, `{Entity}DetailResponse` | `PatientResponse`, `PatientDetailResponse` |
| Response DTO field alias | `camelCase` | `firstName`, `dateOfBirth`, `createdAt`, `patientId` |
| Response DTO factory method | `from_{entity}` | `from_patient`, `from_order`, `from_prediction` |
| Controller file | `{entity}_controller.py` | `patient_controller.py`, `simulation_controller.py` |
| Router export name | `{entity}_router` | `patient_router`, `auth_router`, `simulation_router` |
| Service factory function | `get_{entity}_service` | `get_patient_service`, `get_prediction_service` |
| Role guard alias | `require_{role}` | `require_admin`, `require_doctor` |
| Internal helper file | descriptive `snake_case.py` | `admin_seeder.py`, `token_cleanup.py`, `password_hasher.py` |
| API route prefix | `/api/v1/{resource}` (plural noun) | `/api/v1/patients`, `/api/v1/orders`, `/api/v1/simulations` |
| Router tag (OpenAPI) | Title-cased words | `"Patients"`, `"Lab Results"`, `"Similar Patients"` |

---

## 9. Error Handling Pattern

### Available Exception Classes

All exceptions are in `src.shared.exceptions`. Import from there.

| Class | HTTP Status | When to Use |
|-------|-------------|-------------|
| `NotFoundException` | 404 | Resource not found by ID or lookup key |
| `ConflictException` | 409 | Unique constraint violation, duplicate resource, max concurrency reached |
| `BadRequestException` | 400 | Business rule violation — wrong state, invalid field combination, missing conditional field |
| `ValidationException` | 400 | Input failed domain-level validation (beyond Pydantic request validation) |
| `AuthenticationException` | 401 | Token invalid, expired, revoked, wrong type |
| `AuthorizationException` | 403 | Authenticated but insufficient role or permission |
| `InternalServerException` | 500 | Unrecoverable error within the application |
| `ServiceUnavailableException` | 503 | External dependency (DB, ML service, third-party API) unreachable |

All of these inherit from `AppException`, which is caught globally by `register_error_handlers` and converted to `ApiResponse.failure(error=exc.error_detail)` with the correct HTTP status code.

### Raising Exceptions — Two Patterns

**Pattern 1: `ErrorDetail.builder()` — when attaching per-field errors**

Use this when the error needs to surface which specific request fields caused the failure. The `fieldErrors` key in the response will contain a map of field names to error lists.

```python
from src.shared.exceptions import ConflictException
from src.shared.responses import ErrorDetail

# Single field error
error = ErrorDetail.builder("Registration Failed", "EMAIL_EXISTS", 409)
error.add_field_error("email", "Email already registered")
raise ConflictException(
    message="This email is already registered",
    error_detail=error.build(),
)

# Multiple field errors in the same raise
error = ErrorDetail.builder("Update Failed", "VALIDATION_FAILED", 400)
error.add_field_error("start_date", "Start date must be before end date")
error.add_field_error("end_date", "End date must be after start date")
raise BadRequestException(
    message="Invalid date range",
    error_detail=error.build(),
)
```

Builder methods:
- `.add_detail(detail: str)` — appends a string to the top-level `details` list
- `.add_field_error(field: str, error: str)` — appends one error string to `fieldErrors[field]`
- `.add_field_errors(field: str, errors: List[str])` — appends multiple errors to `fieldErrors[field]`
- `.build()` — returns a `ErrorDetail` instance ready to pass to an exception

**Pattern 2: Direct `ErrorDetail(...)` — for all other errors**

Use this when there are no per-field errors — just a top-level status with a message and optional detail strings.

```python
from src.shared.exceptions import NotFoundException
from src.shared.responses import ErrorDetail

raise NotFoundException(
    message="Order not found",
    error_detail=ErrorDetail(
        title="Not Found",
        code="ORDER_NOT_FOUND",
        status=404,
        details=[f"No order found with id {order_id}"],
    ),
)
```

**Error code conventions:**
- Format: `UPPER_SNAKE_CASE`
- Be specific to the failure, not generic: `USER_NOT_FOUND`, `EMAIL_EXISTS`, `SIMULATION_NOT_RUNNING`, `MAX_SIMULATIONS_REACHED`, `RECORD_PATIENT_MISMATCH`
- The `message` field is user-facing prose. The `code` is machine-readable. The `title` is a short UI label. The `details` list contains developer-facing elaborations.

---

## 10. Complete Auth Module File Contents

The following are the verbatim contents of every file in `src/modules/auth/`. This is the canonical reference. When building a new module, produce the same structure and patterns adapted to the new domain — never copy auth-specific logic.

---

### `src/modules/auth/__init__.py`

```python
from src.modules.auth.presentation.controllers.auth_controller import router as auth_router
from src.modules.auth.presentation.controllers.user_controller import router as user_router

__all__ = ["auth_router", "user_router"]
```

---

### `src/modules/auth/domain/__init__.py`

```python
# ── domain/__init__.py ──
from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.models.token import Token
from src.modules.auth.domain.models.enums import Role, TokenType
from src.modules.auth.domain.repositories.user_repository import UserRepository
from src.modules.auth.domain.repositories.token_repository import TokenRepository

__all__ = ["User", "Token", "Role", "TokenType", "UserRepository", "TokenRepository"]


# ── domain/models/__init__.py ──
from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.models.token import Token
from src.modules.auth.domain.models.enums import Role, TokenType

__all__ = ["User", "Token", "Role", "TokenType"]


# ── domain/repositories/__init__.py ──
from src.modules.auth.domain.repositories.user_repository import UserRepository
from src.modules.auth.domain.repositories.token_repository import TokenRepository

__all__ = ["UserRepository", "TokenRepository"]
```

---

### `src/modules/auth/domain/models/enums.py`

```python
import enum


class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    DOCTOR = "DOCTOR"


class TokenType(str, enum.Enum):
    ACCESS = "ACCESS"
    REFRESH = "REFRESH"
```

---

### `src/modules/auth/domain/models/user.py`

```python
from sqlalchemy import String, Boolean, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from src.modules.auth.domain.models.enums import Role
from src.shared.database import BaseModel


class User(BaseModel):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(
        SAEnum(Role, name="role_enum"), nullable=False, default=Role.DOCTOR
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
```

---

### `src/modules/auth/domain/models/token.py`

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.database import BaseModel
from src.modules.auth.domain.models.enums import TokenType


class Token(BaseModel):
    __tablename__ = "tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True, index=True
    )
    token_type: Mapped[TokenType] = mapped_column(
        SAEnum(TokenType, name="token_type_enum"), nullable=False
    )
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and self.expires_at > datetime.now(timezone.utc)

    def revoke(self) -> None:
        self.is_revoked = True
```

---

### `src/modules/auth/domain/repositories/user_repository.py`

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.database import BaseRepository
from src.modules.auth.domain.models.user import User


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def email_exists(self, email: str) -> bool:
        return await self.exists(email=email)

    async def username_exists(self, username: str) -> bool:
        return await self.exists(username=username)
```

---

### `src/modules/auth/domain/repositories/token_repository.py`

```python
from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.database import BaseRepository
from src.modules.auth.domain.models.token import Token
from src.modules.auth.domain.models.enums import TokenType


class TokenRepository(BaseRepository[Token]):
    def __init__(self, session: AsyncSession):
        super().__init__(Token, session)

    async def get_by_token(self, token: str) -> Token | None:
        stmt = select(Token).where(Token.token == token)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def is_token_valid(self, token: str) -> bool:
        record = await self.get_by_token(token)
        return record is not None and record.is_valid

    async def revoke_token(self, token: str) -> None:
        stmt = (
            update(Token)
            .where(Token.token == token)
            .values(is_revoked=True)
        )
        await self.session.execute(stmt)

    async def revoke_all_user_tokens(self, user_id: UUID) -> None:
        stmt = (
            update(Token)
            .where(Token.user_id == user_id, Token.is_revoked == False)
            .values(is_revoked=True)
        )
        await self.session.execute(stmt)

    async def revoke_user_tokens_by_type(self, user_id: UUID, token_type: TokenType) -> None:
        stmt = (
            update(Token)
            .where(
                Token.user_id == user_id,
                Token.token_type == token_type,
                Token.is_revoked == False,
            )
            .values(is_revoked=True)
        )
        await self.session.execute(stmt)

    async def cleanup_expired(self) -> int:
        """Delete expired tokens. Returns count of deleted rows."""
        now = datetime.now(timezone.utc)
        stmt = select(Token).where(Token.expires_at < now)
        result = await self.session.execute(stmt)
        expired = result.scalars().all()
        for t in expired:
            await self.session.delete(t)
        await self.session.flush()
        return len(expired)
```

---

### `src/modules/auth/domain/services/__init__.py`

```python
from src.modules.auth.domain.services.auth_service import AuthService
from src.modules.auth.domain.services.user_management_service import UserManagementService

__all__ = ["AuthService", "UserManagementService"]
```

---

### `src/modules/auth/domain/services/auth_service.py`

```python
from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.models.enums import Role
from src.modules.auth.domain.repositories.user_repository import UserRepository
from src.modules.auth.domain.repositories.token_repository import TokenRepository
from src.modules.auth.internal import password_hasher, token_provider
from src.shared.exceptions import (
    ConflictException,
    AuthenticationException,
    NotFoundException,
)
from src.shared.responses import ErrorDetail


class AuthService:
    def __init__(self, user_repository: UserRepository, token_repository: TokenRepository):
        self.user_repo = user_repository
        self.token_repo = token_repository

    async def register(
        self,
        email: str,
        username: str,
        first_name: str,
        last_name: str,
        password: str,
        role: str | None = None,
    ) -> tuple[User, dict]:
        if await self.user_repo.email_exists(email):
            error = ErrorDetail.builder("Registration Failed", "EMAIL_EXISTS", 409)
            error.add_field_error("email", "Email already registered")
            raise ConflictException(
                message="This email is already registered",
                error_detail=error.build(),
            )

        if await self.user_repo.username_exists(username):
            error = ErrorDetail.builder("Registration Failed", "USERNAME_EXISTS", 409)
            error.add_field_error("username", "Username already taken")
            raise ConflictException(
                message="This username is already taken",
                error_detail=error.build(),
            )

        user = User(
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            password_hash=password_hasher.hash_password(password),
            role=Role[role] if role else Role.DOCTOR,
        )

        saved_user = await self.user_repo.create(user)
        tokens = await token_provider.create_token_pair(
            saved_user.id, saved_user.role.value, self.token_repo
        )

        return saved_user, tokens

    async def login(self, email: str, password: str) -> tuple[User, dict]:
        user = await self.user_repo.get_by_email(email)

        if not user or not password_hasher.verify_password(password, user.password_hash):
            raise AuthenticationException(
                message="Invalid email or password",
                error_detail=ErrorDetail(
                    title="Login Failed",
                    code="INVALID_CREDENTIALS",
                    status=401,
                    details=["Invalid email or password"],
                ),
            )

        if not user.is_active:
            raise AuthenticationException(
                message="Your account has been deactivated",
                error_detail=ErrorDetail(
                    title="Account Inactive",
                    code="ACCOUNT_INACTIVE",
                    status=403,
                    details=["Account is deactivated"],
                ),
            )

        await self.token_repo.revoke_all_user_tokens(user.id)
        tokens = await token_provider.create_token_pair(
            user.id, user.role.value, self.token_repo
        )

        return user, tokens

    async def refresh_token(self, refresh_token: str) -> dict:
        payload = await token_provider.verify_token(
            refresh_token, self.token_repo, expected_type="refresh"
        )

        user = await self.user_repo.get_by_id(payload["sub"])
        if not user:
            raise NotFoundException(
                message="Your account could not be found",
                error_detail=ErrorDetail(
                    title="User Not Found",
                    code="USER_NOT_FOUND",
                    status=404,
                    details=["User associated with token not found"],
                ),
            )

        await self.token_repo.revoke_token(refresh_token)
        return await token_provider.create_token_pair(
            user.id, user.role.value, self.token_repo
        )

    async def logout(self, token: str) -> None:
        payload = token_provider.decode_token(token, expected_type="access")
        await self.token_repo.revoke_all_user_tokens(payload["sub"])

    async def get_current_user(self, token: str) -> User:
        payload = await token_provider.verify_token(
            token, self.token_repo, expected_type="access"
        )

        user = await self.user_repo.get_by_id(payload["sub"])
        if not user:
            raise NotFoundException(
                message="Your account could not be found",
                error_detail=ErrorDetail(
                    title="User Not Found",
                    code="USER_NOT_FOUND",
                    status=404,
                    details=["User associated with token not found"],
                ),
            )

        return user

    async def update_profile(
        self,
        user: User,
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
    ) -> User:
        data = {}

        if first_name is not None:
            data["first_name"] = first_name
        if last_name is not None:
            data["last_name"] = last_name

        if username is not None and username != user.username:
            if await self.user_repo.username_exists(username):
                error = ErrorDetail.builder("Update Failed", "USERNAME_EXISTS", 409)
                error.add_field_error("username", "Username already taken")
                raise ConflictException(
                    message="This username is already taken",
                    error_detail=error.build(),
                )
            data["username"] = username

        if not data:
            return user

        return await self.user_repo.update(user, data)
```

---

### `src/modules/auth/domain/services/user_management_service.py`

```python
from typing import Sequence, Tuple
from uuid import UUID

from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.models.enums import Role
from src.modules.auth.domain.repositories.user_repository import UserRepository
from src.modules.auth.internal import password_hasher
from src.shared.exceptions import (
    NotFoundException,
    ConflictException,
    BadRequestException,
)
from src.shared.responses import ErrorDetail


class UserManagementService:
    def __init__(self, user_repository: UserRepository):
        self.user_repo = user_repository

    async def get_users(
        self,
        page: int = 1,
        page_size: int = 20,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> Tuple[Sequence[User], int]:
        filters = {}
        if role is not None:
            filters["role"] = Role[role]
        if is_active is not None:
            filters["is_active"] = is_active

        return await self.user_repo.paginate(
            page=page,
            page_size=page_size,
            order_by="created_at",
            descending=True,
            **filters,
        )

    async def get_user(self, user_id: UUID) -> User:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundException(
                message="User not found",
                error_detail=ErrorDetail(
                    title="Not Found",
                    code="USER_NOT_FOUND",
                    status=404,
                    details=[f"No user found with id {user_id}"],
                ),
            )
        return user

    async def create_user(
        self,
        email: str,
        username: str,
        first_name: str,
        last_name: str,
        password: str,
        role: str,
    ) -> User:
        if await self.user_repo.email_exists(email):
            error = ErrorDetail.builder("Creation Failed", "EMAIL_EXISTS", 409)
            error.add_field_error("email", "Email already registered")
            raise ConflictException(
                message="This email is already registered",
                error_detail=error.build(),
            )

        if await self.user_repo.username_exists(username):
            error = ErrorDetail.builder("Creation Failed", "USERNAME_EXISTS", 409)
            error.add_field_error("username", "Username already taken")
            raise ConflictException(
                message="This username is already taken",
                error_detail=error.build(),
            )

        user = User(
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            password_hash=password_hasher.hash_password(password),
            role=Role[role],
        )

        return await self.user_repo.create(user)

    async def update_user(
        self,
        user_id: UUID,
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> User:
        user = await self.get_user(user_id)
        data = {}

        if first_name is not None:
            data["first_name"] = first_name
        if last_name is not None:
            data["last_name"] = last_name
        if role is not None:
            data["role"] = Role[role]
        if is_active is not None:
            data["is_active"] = is_active

        if username is not None and username != user.username:
            if await self.user_repo.username_exists(username):
                error = ErrorDetail.builder("Update Failed", "USERNAME_EXISTS", 409)
                error.add_field_error("username", "Username already taken")
                raise ConflictException(
                    message="This username is already taken",
                    error_detail=error.build(),
                )
            data["username"] = username

        if not data:
            return user

        return await self.user_repo.update(user, data)

    async def delete_user(self, user_id: UUID) -> None:
        user = await self.get_user(user_id)
        await self.user_repo.delete(user)
```

---

### `src/modules/auth/internal/__init__.py`

```python
from src.modules.auth.internal import password_hasher, token_provider
from src.modules.auth.internal.admin_seeder import seed_admin
from src.modules.auth.internal.token_cleanup import start_token_cleanup

__all__ = ["password_hasher", "token_provider", "seed_admin", "start_token_cleanup"]
```

---

### `src/modules/auth/internal/password_hasher.py`

```python
import bcrypt


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())
```

---

### `src/modules/auth/internal/token_provider.py`

```python
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from src.configs import security
from src.modules.auth.domain.models.token import Token
from src.modules.auth.domain.models.enums import TokenType
from src.modules.auth.domain.repositories.token_repository import TokenRepository
from src.shared.exceptions import AuthenticationException
from src.shared.responses import ErrorDetail


def _encode(payload: dict) -> str:
    return jwt.encode(payload, security.jwt.secret_key, algorithm=security.jwt.algorithm)


def _build_payload(user_id: UUID, token_type: str, expires_delta: timedelta, role: str | None = None) -> dict:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if role:
        payload["role"] = role
    return payload


async def create_token_pair(user_id: UUID, role: str, token_repo: TokenRepository) -> dict:
    access_delta = timedelta(minutes=security.jwt.access_token_expire_minutes)
    refresh_delta = timedelta(days=security.jwt.refresh_token_expire_days)
    now = datetime.now(timezone.utc)

    access_payload = _build_payload(user_id, "access", access_delta, role=role)
    refresh_payload = _build_payload(user_id, "refresh", refresh_delta)

    access_token = _encode(access_payload)
    refresh_token = _encode(refresh_payload)

    await token_repo.create(Token(
        user_id=user_id,
        token=access_token,
        token_type=TokenType.ACCESS,
        expires_at=now + access_delta,
    ))
    await token_repo.create(Token(
        user_id=user_id,
        token=refresh_token,
        token_type=TokenType.REFRESH,
        expires_at=now + refresh_delta,
    ))

    return {"access_token": access_token, "refresh_token": refresh_token}


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(
            token, security.jwt.secret_key, algorithms=[security.jwt.algorithm]
        )
    except jwt.ExpiredSignatureError:
        raise AuthenticationException(
            message="Your session has expired. Please log in again",
            error_detail=ErrorDetail(
                title="Token Expired", code="TOKEN_EXPIRED", status=401,
                details=["Token has expired"],
            ),
        )
    except jwt.InvalidTokenError:
        raise AuthenticationException(
            message="Invalid authentication token",
            error_detail=ErrorDetail(
                title="Invalid Token", code="INVALID_TOKEN", status=401,
                details=["Token is invalid or malformed"],
            ),
        )

    if payload.get("type") != expected_type:
        raise AuthenticationException(
            message="Invalid token type",
            error_detail=ErrorDetail(
                title="Invalid Token Type", code="INVALID_TOKEN_TYPE", status=401,
                details=[f"Expected {expected_type} token"],
            ),
        )

    return payload


async def verify_token(token: str, token_repo: TokenRepository, expected_type: str = "access") -> dict:
    """Decode the JWT and verify it hasn't been revoked."""
    payload = decode_token(token, expected_type)

    if not await token_repo.is_token_valid(token):
        raise AuthenticationException(
            message="This token has been revoked",
            error_detail=ErrorDetail(
                title="Token Revoked", code="TOKEN_REVOKED", status=401,
                details=["Token has been revoked"],
            ),
        )

    return payload
```

---

### `src/modules/auth/internal/admin_seeder.py`

```python
import logging

from src.shared.database import async_session
from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.models.enums import Role
from src.modules.auth.domain.repositories.user_repository import UserRepository
from src.modules.auth.internal import password_hasher
from src.configs import security

logger = logging.getLogger(__name__)


async def seed_admin() -> None:
    async with async_session() as session:
        async with session.begin():
            repo = UserRepository(session)

            if await repo.exists(role=Role.ADMIN):
                logger.info("Admin user already exists — skipping seed")
                return

            admin = User(
                email=security.admin.email,
                username=security.admin.username,
                first_name="System",
                last_name="Admin",
                password_hash=password_hasher.hash_password(security.admin.password),
                role=Role.ADMIN,
            )

            await repo.create(admin)
            logger.info("Default admin user created (%s)", security.admin.email)
```

---

### `src/modules/auth/internal/token_cleanup.py`

```python
import asyncio
import logging

from src.shared.database import async_session
from src.modules.auth.domain.repositories.token_repository import TokenRepository
from src.configs import security

logger = logging.getLogger(__name__)


async def start_token_cleanup() -> None:
    """Background loop that purges expired tokens on a fixed interval."""
    while True:
        await asyncio.sleep(security.token_cleanup_interval_seconds)
        try:
            async with async_session() as session:
                async with session.begin():
                    repo = TokenRepository(session)
                    count = await repo.cleanup_expired()
                    if count:
                        logger.info("Token cleanup: removed %d expired token(s)", count)
        except Exception as e:
            logger.error("Token cleanup failed: %s", e)
```

---

### `src/modules/auth/presentation/__init__.py`

```python
# ── presentation/__init__.py ──
from src.modules.auth.presentation.controllers.auth_controller import router as auth_router
from src.modules.auth.presentation.controllers.user_controller import router as user_router

__all__ = ["auth_router", "user_router"]


# ── presentation/dtos/__init__.py ──
# empty


# ── presentation/controllers/__init__.py ──
# empty
```

---

### `src/modules/auth/presentation/dependencies.py`

```python
from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.database import get_db
from src.shared.exceptions import AuthorizationException
from src.shared.responses import ErrorDetail
from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.models.enums import Role
from src.modules.auth.domain.repositories.user_repository import UserRepository
from src.modules.auth.domain.repositories.token_repository import TokenRepository
from src.modules.auth.domain.services.auth_service import AuthService
from src.modules.auth.domain.services.user_management_service import UserManagementService

bearer_scheme = HTTPBearer()


# ── Service factories ──

def get_auth_service(session: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(session), TokenRepository(session))


def get_user_management_service(session: AsyncSession = Depends(get_db)) -> UserManagementService:
    return UserManagementService(UserRepository(session))


# ── Auth dependencies ──

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    return await auth_service.get_current_user(credentials.credentials)


def require_role(*allowed_roles: Role):
    async def _guard(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            role_names = ", ".join(r.value for r in allowed_roles)
            raise AuthorizationException(
                message="You don't have permission to perform this action",
                error_detail=ErrorDetail(
                    title="Access Denied",
                    code="INSUFFICIENT_ROLE",
                    status=403,
                    details=[f"Required role(s): {role_names}"],
                ),
            )
        return current_user
    return _guard


# Convenience alias
require_admin = require_role(Role.ADMIN)
```

---

### `src/modules/auth/presentation/dtos/requests.py`

```python
from pydantic import BaseModel, EmailStr, Field
from typing import Optional


# ── Auth DTOs ──

class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=100)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UpdateProfileRequest(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    username: Optional[str] = Field(None, min_length=3, max_length=100)


# ── Admin User Management DTOs ──

class CreateUserRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=100)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(pattern="^(ADMIN|DOCTOR)$")


class UpdateUserRequest(BaseModel):
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    role: Optional[str] = Field(None, pattern="^(ADMIN|DOCTOR)$")
    is_active: Optional[bool] = None
```

---

### `src/modules/auth/presentation/dtos/responses.py`

```python
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field

from src.modules.auth.domain.models.user import User


class UserResponse(BaseModel):
    id: UUID
    email: str
    username: str
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    role: str
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    class Config:
        populate_by_name = True
        from_attributes = True

    @staticmethod
    def from_user(user: User) -> "UserResponse":
        return UserResponse(
            id=user.id,
            email=user.email,
            username=user.username,
            firstName=user.first_name,
            lastName=user.last_name,
            role=user.role.value,
            isActive=user.is_active,
            createdAt=user.created_at,
            updatedAt=user.updated_at,
        )


class TokenResponse(BaseModel):
    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")

    class Config:
        populate_by_name = True


class AuthResponse(BaseModel):
    user: UserResponse
    tokens: TokenResponse
```

---

### `src/modules/auth/presentation/controllers/auth_controller.py`

```python
from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials

from src.shared.responses import ApiResponse
from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.services.auth_service import AuthService
from src.modules.auth.presentation.dependencies import (
    bearer_scheme,
    get_auth_service,
    get_current_user,
)
from src.modules.auth.presentation.dtos.requests import (
    RegisterRequest,
    LoginRequest,
    RefreshTokenRequest,
    UpdateProfileRequest,
)
from src.modules.auth.presentation.dtos.responses import (
    UserResponse,
    TokenResponse,
    AuthResponse,
)

router = APIRouter()


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    user, tokens = await auth_service.register(
        email=body.email,
        username=body.username,
        first_name=body.first_name,
        last_name=body.last_name,
        password=body.password,
    )
    return ApiResponse.ok(
        value=AuthResponse(
            user=UserResponse.from_user(user),
            tokens=TokenResponse(accessToken=tokens["access_token"], refreshToken=tokens["refresh_token"]),
        ),
        message="Registration successful",
    )


@router.post("/login")
async def login(
    body: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    user, tokens = await auth_service.login(email=body.email, password=body.password)
    return ApiResponse.ok(
        value=AuthResponse(
            user=UserResponse.from_user(user),
            tokens=TokenResponse(accessToken=tokens["access_token"], refreshToken=tokens["refresh_token"]),
        ),
        message="Login successful",
    )


@router.post("/refresh")
async def refresh_token(
    body: RefreshTokenRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    tokens = await auth_service.refresh_token(body.refresh_token)
    return ApiResponse.ok(
        value=TokenResponse(accessToken=tokens["access_token"], refreshToken=tokens["refresh_token"]),
        message="Tokens refreshed",
    )


@router.post("/logout", status_code=200)
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
):
    await auth_service.logout(credentials.credentials)
    return ApiResponse.ok(value=None, message="Logged out successfully")


@router.get("/me")
async def get_profile(current_user: User = Depends(get_current_user)):
    return ApiResponse.ok(value=UserResponse.from_user(current_user))


@router.patch("/me")
async def update_profile(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    updated = await auth_service.update_profile(
        user=current_user,
        first_name=body.first_name,
        last_name=body.last_name,
        username=body.username,
    )
    return ApiResponse.ok(value=UserResponse.from_user(updated), message="Profile updated")
```

---

### `src/modules/auth/presentation/controllers/user_controller.py`

```python
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, Query

from src.shared.responses import ApiResponse, PaginatedResponse
from src.shared.database.pagination import PaginationParams, get_pagination
from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.services.user_management_service import UserManagementService
from src.modules.auth.presentation.dependencies import (
    get_user_management_service,
    require_admin,
)
from src.modules.auth.presentation.dtos.requests import CreateUserRequest, UpdateUserRequest
from src.modules.auth.presentation.dtos.responses import UserResponse

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("")
async def get_users(
    pagination: PaginationParams = Depends(get_pagination),
    role: Optional[str] = Query(None, pattern="^(ADMIN|DOCTOR)$"),
    is_active: Optional[bool] = None,
    service: UserManagementService = Depends(get_user_management_service),
):
    users, total = await service.get_users(
        page=pagination.page, page_size=pagination.page_size, role=role, is_active=is_active
    )
    return PaginatedResponse.ok(
        value=[UserResponse.from_user(u) for u in users],
        page=pagination.page,
        total=total,
        page_size=pagination.page_size,
    )


@router.get("/{user_id}")
async def get_user(
    user_id: UUID,
    _admin: User = Depends(require_admin),
    service: UserManagementService = Depends(get_user_management_service),
):
    user = await service.get_user(user_id)
    return ApiResponse.ok(value=UserResponse.from_user(user))


@router.post("", status_code=201)
async def create_user(
    body: CreateUserRequest,
    _admin: User = Depends(require_admin),
    service: UserManagementService = Depends(get_user_management_service),
):
    user = await service.create_user(
        email=body.email,
        username=body.username,
        first_name=body.first_name,
        last_name=body.last_name,
        password=body.password,
        role=body.role,
    )
    return ApiResponse.ok(value=UserResponse.from_user(user), message="User created")


@router.patch("/{user_id}")
async def update_user(
    user_id: UUID,
    body: UpdateUserRequest,
    service: UserManagementService = Depends(get_user_management_service),
):
    user = await service.update_user(
        user_id=user_id,
        first_name=body.first_name,
        last_name=body.last_name,
        username=body.username,
        role=body.role,
        is_active=body.is_active,
    )
    return ApiResponse.ok(value=UserResponse.from_user(user), message="User updated")


@router.delete("/{user_id}", status_code=200)
async def delete_user(
    user_id: UUID,
    service: UserManagementService = Depends(get_user_management_service),
):
    await service.delete_user(user_id)
    return ApiResponse.ok(value=None, message="User deleted")
```
