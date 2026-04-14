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
