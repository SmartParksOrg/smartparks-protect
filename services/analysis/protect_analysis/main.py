"""Analysis service: consumes `analysis.requested`, runs one analysis at a time in a process of
its own, and removes expired runs hourly (docs/ANALYTICS_PHASE1_PLAN.md, section 7). Nothing in
the core waits for it: a stopped worker leaves runs queued and the rest of Protect as it is."""

import asyncio
import uuid

import shared.analysis.modules  # noqa: F401  (registers the modules)
from shared.analysis.runner import expire_analyses, run_analysis
from shared.bus import Message, Topic
from shared.config import get_settings
from shared.database import session_scope
from shared.enums import AnalysisStatus
from shared.logger import get_logger
from shared.models import AnalysisRun
from shared.worker import Worker

log = get_logger("analysis")
CLEANUP_INTERVAL_SECONDS = 3600


def build_worker() -> Worker:
    worker = Worker("analysis")
    # one run at a time per worker, whatever the bus lanes allow (plan, section 14)
    slot = asyncio.Semaphore(get_settings().analysis_concurrency)

    async def handle(message: Message) -> None:
        run_id = uuid.UUID(str(message.payload["run_id"]))
        async with slot, session_scope() as session:
            run = await session.get(AnalysisRun, run_id)
            if run is None:
                log.warning("analysis run vanished before it ran", run_id=str(run_id))
                return
            if run.status != AnalysisStatus.QUEUED:
                # a redelivery after a crash, or a cancel that beat the worker: nothing to do
                log.info("analysis run not queued, skipped", run_id=str(run_id), status=run.status)
                return
            await run_analysis(session, run)
        log.info("analysis finished", run_id=str(run_id))

    async def cleanup_loop() -> None:
        """Every hour: remove runs past their expiry (kept runs have none)."""
        while not worker.bus._stop.is_set():
            try:
                async with session_scope() as session:
                    expired = await expire_analyses(session)
                if expired:
                    log.info("expired analysis runs removed", count=expired)
            except Exception as exc:
                log.warning("analysis cleanup failed", error=str(exc))
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

    worker.subscribe(Topic.ANALYSIS_REQUESTED, handle)
    worker.background(cleanup_loop)
    return worker


def main() -> None:
    asyncio.run(build_worker().run())


if __name__ == "__main__":
    main()
