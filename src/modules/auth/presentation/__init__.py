from src.modules.auth.presentation.controllers.auth_controller import router as auth_router
from src.modules.auth.presentation.controllers.user_controller import router as user_router

__all__ = ["auth_router", "user_router"]
