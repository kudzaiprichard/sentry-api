"""Background-pipeline hand-off for the extension analyse flow.

After the Chrome extension's ``POST /api/v1/emails/analyze`` returns its
synchronous Stage-1 verdict, the same email is submitted to the full
inference pipeline (Stages 2-4) so the dashboard eventually shows link
resolution, page analysis, and the final aggregation.

The extension must not import from ``src/modules/inference/*`` directly —
that would cross the module boundary. Instead this module declares a
narrow Protocol and the concrete adapter lives in ``src/core/`` (the
composition layer). The controller builds the adapter and injects it
into ``EmailAnalyseService``; if no submitter is wired (tests, legacy
runs) the service simply skips the hand-off.

Failure isolation: the adapter uses its own DB session and its own
task, so a pipeline-spawn failure must never roll back the extension's
Stage-1 response write or surface as a 5xx to the extension.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class PipelineSubmitter(Protocol):
    async def submit(
        self,
        *,
        sender: str,
        subject: str,
        body: str,
        install_id: UUID,
    ) -> None: ...
