"""Export service: consumes `export.requested`, runs the job, stores the result in MinIO. It is
also the batch worker for curation jobs (`curation.job_requested`, architecture 28.5), for
attribution jobs (`attribution.requested`, decision D206) and for the PDF reports of analysis
runs (`analysis_report.requested`, decision D211)."""

import asyncio
import uuid

from shared.analysis.report import run_report_job
from shared.bus import Message, Topic
from shared.curation.jobs import run_job
from shared.database import session_scope
from shared.domain.attribution import run_attribution_job
from shared.exports.cleanup import expire_exports
from shared.exports.runner import run_export
from shared.logger import get_logger
from shared.models import ExportJob
from shared.worker import Worker

log = get_logger("export")
CLEANUP_INTERVAL_SECONDS = 3600


def build_worker() -> Worker:
    worker = Worker("export")

    async def handle(message: Message) -> None:
        job_id = uuid.UUID(str(message.payload["job_id"]))
        async with session_scope() as session:
            job = await session.get(ExportJob, job_id)
            if job is None:
                log.warning("export job vanished before it ran", job_id=str(job_id))
                return
            await run_export(session, job)
        log.info("export finished", job_id=str(job_id))

    async def on_curation(message: Message) -> None:
        await run_job(worker.bus, message.payload)

    async def on_attribution(message: Message) -> None:
        await run_attribution_job(message.payload)

    async def on_report(message: Message) -> None:
        await run_report_job(message.payload)

    async def cleanup_loop() -> None:
        """Every hour: remove the files of exports past their retention (architecture 14)."""
        while not worker.bus._stop.is_set():
            try:
                async with session_scope() as session:
                    expired = await expire_exports(session)
                if expired:
                    log.info("expired export files removed", count=expired)
            except Exception as exc:
                log.warning("export cleanup failed", error=str(exc))
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)

    worker.subscribe(Topic.EXPORT_REQUESTED, handle)
    worker.subscribe(Topic.CURATION_JOB_REQUESTED, on_curation)
    worker.subscribe(Topic.ATTRIBUTION_REQUESTED, on_attribution)
    worker.subscribe(Topic.ANALYSIS_REPORT_REQUESTED, on_report)
    worker.background(cleanup_loop)
    return worker


def main() -> None:
    asyncio.run(build_worker().run())


if __name__ == "__main__":
    main()
