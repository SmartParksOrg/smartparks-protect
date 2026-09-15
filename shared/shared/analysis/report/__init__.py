"""PDF reports of analysis runs (decision D211): a report engine of our own on the server.

The export service renders a run's result document to A4 through a Jinja template and
WeasyPrint, draws the charts with matplotlib in the brand palette and the map as a static
image (MapTiler behind the tracks and polygons when the server has a key, a plain drawing
otherwise), and keeps the PDF in the exports bucket beside the run. `job.py` is the queue and
the handler, `render.py` the document, `charts.py` and `mapimage.py` the pictures.
"""

from shared.analysis.report.job import (
    publish_report,
    queue_report,
    remove_report,
    report_key,
    run_report_job,
)

__all__ = ["publish_report", "queue_report", "remove_report", "report_key", "run_report_job"]
