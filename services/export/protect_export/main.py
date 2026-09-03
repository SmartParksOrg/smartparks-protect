"""Export service: consumes `export.requested`, runs the job, stores the result in MinIO."""

import asyncio
import uuid

from shared.bus import Message, Topic
from shared.database import session_scope
from shared.exports.runner import run_export
from shared.logger import get_logger
from shared.models import ExportJob
from shared.worker import Worker

log = get_logger("export")


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

    worker.subscribe(Topic.EXPORT_REQUESTED, handle)
    return worker


def main() -> None:
    asyncio.run(build_worker().run())


if __name__ == "__main__":
    main()
