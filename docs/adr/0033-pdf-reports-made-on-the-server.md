# 0033. PDF reports of analyses made on the server

Date: 2026-09-15

Status: accepted

## Context

A movement or grazing analysis is read on screen, but ecologists and managers pass results on as documents. The first answer (decision D208, the same morning) was a print view: a clean page in the browser and "Save as PDF" through the browser's print dialog. Tim judged the result on the development server: a screen dump on paper. The settings and the limitations printed folded shut, the fifteen-column summary table ran off the page, the charts sat small with large empty areas, the page breaks fell where they fell, the map kept its screen chips, and nothing said which page of how many a reader held. Browser printing has no page counters or running headers, and every browser and every print setting gives a different sheet.

## Decision

The server makes the PDF. A Jinja template with print CSS is rendered by WeasyPrint (page size and margins, a running title and footer, "Page n of m", tables that break across pages with their header repeated), the charts are drawn by matplotlib in the brand palette as SVG, and the map is a picture: the tracks and result polygons drawn in Web Mercator over a MapTiler static image when the server has a key, over a plain background with a scale bar and a north arrow when it has none. A wide table with a handful of rows is turned on its side so it fits A4 portrait.

The report is a job. "Make PDF report" under Export on a run marks the run's report queued and publishes `analysis_report.requested`; the export service, already the batch worker for exports, curation and attribution jobs, gathers the run's document, geometries and tracks, renders the PDF and keeps it in the exports bucket beside the run. The run row carries the report's status, its key and its error; the page polls while it is being made and offers "Download PDF report" when it is ready. The PDF lives as long as the run: deleting or expiring the run removes it. Asking for it needs `exports:create`, like the other exports; reading it needs the run to be visible.

## Alternatives considered

- Improve the print view: page breaks and sizes can be tuned with CSS, but the browser has no page numbers or running headers, and the output depends on each browser's print settings; it stays a screen dump in spirit.
- Headless Chromium in the export worker: the charts and the map would come out exactly as on screen, with headers and footers; but the image grows by some 400 MB, the worker needs a browser and a token to reach the frontend, and the layout problems still need a print-tuned page.
- ReportLab: pure Python, no system libraries; but the layout is programmatic where HTML and CSS keep the design readable, and the page-flow features WeasyPrint gives for free would be built by hand.

## Consequences

Two Python dependencies (WeasyPrint, matplotlib) and four small system packages in the image (Pango, HarfBuzz, DejaVu fonts). Every PDF looks the same wherever it is made, and a scheduled report (the monthly utilisation report noted for later) becomes a matter of queueing the job on a timer. The report is English only; the words are the interface's English labels, kept in the report module. The MapTiler key is referrer-restricted, so the server sends its public address as the referrer; a refused or missing base map falls back to the drawing and the report says so.
