# Analytics

The Analyze section: the [Data Explorer](data-explorer.md) queries aggregates server side and drills down to the rows and source events behind them, and [Export](export.md) produces reproducible files, directly for small selections and through the export service for large ones.

Both are bounded by design (architecture 13.10): no request can return more than a few thousand points per series, and exports stream from the database to the file without holding rows in memory.
- [Data curation](curation.md): reversible, audited corrections on canonical records, bulk jobs, the effective value and export views.
