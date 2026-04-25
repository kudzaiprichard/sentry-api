from src.modules.inference.presentation.controllers.email_controller import (
    router as inference_email_router,
)
from src.modules.inference.presentation.controllers.stats_controller import (
    router as inference_stats_router,
)

__all__ = ["inference_email_router", "inference_stats_router"]
