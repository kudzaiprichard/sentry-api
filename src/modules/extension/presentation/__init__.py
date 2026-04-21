from src.modules.extension.presentation.controllers.admin_controller import (
    router as extension_admin_router,
)
from src.modules.extension.presentation.controllers.auth_controller import (
    router as extension_auth_router,
)
from src.modules.extension.presentation.controllers.emails_controller import (
    router as extension_emails_router,
)
from src.modules.extension.presentation.controllers.health_controller import (
    router as extension_health_router,
)

__all__ = [
    "extension_admin_router",
    "extension_auth_router",
    "extension_emails_router",
    "extension_health_router",
]
