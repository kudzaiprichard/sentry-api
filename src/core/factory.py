from fastapi import FastAPI

from src.configs import application
from src.core.lifespan import lifespan
from src.core.middleware import register_middleware
from src.shared.exceptions.error_handlers import register_error_handlers
from src.modules.auth import auth_router, user_router
from src.modules.inference import inference_email_router, inference_stats_router
from src.modules.extension import (
    extension_admin_router,
    extension_auth_router,
    extension_emails_router,
    extension_health_router,
)
from src.modules.extension.internal.rate_limit import limiter


def create_app() -> FastAPI:
    app = FastAPI(
        title=application.name,
        version=application.version,
        debug=application.debug,
        lifespan=lifespan,
    )

    # slowapi looks for the limiter on app.state when the @limiter.limit
    # decorator fires — without SlowAPIMiddleware we still exercise the
    # decorator path and raise RateLimitExceeded, which the error handler
    # converts to the standard RATE_LIMITED envelope.
    app.state.limiter = limiter

    register_middleware(app)
    register_error_handlers(app)
    _register_routers(app)

    return app


def _register_routers(app: FastAPI) -> None:
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
    app.include_router(user_router, prefix="/api/v1/users", tags=["Users"])
    app.include_router(
        inference_email_router, prefix="/api/v1/inference", tags=["Inference"]
    )
    app.include_router(
        inference_stats_router,
        prefix="/api/v1/inference/stats",
        tags=["Inference Stats"],
    )
    # Extension surface — five endpoints the Chrome extension calls plus the
    # dashboard-only admin install management surface.
    app.include_router(
        extension_health_router, prefix="/api/v1", tags=["Extension"]
    )
    app.include_router(
        extension_auth_router,
        prefix="/api/v1/auth/extension",
        tags=["Extension Auth"],
    )
    app.include_router(
        extension_emails_router, prefix="/api/v1/emails", tags=["Extension"]
    )
    app.include_router(
        extension_admin_router,
        prefix="/api/v1/extension/installs",
        tags=["Extension Admin"],
    )
