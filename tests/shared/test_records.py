"""The records reading (phase 20, decision D142) as SQL: the statements it builds, checked by
compiling them, because a filter that drags a second table into a select turns a page read into
a cross join of two hypertables (found on the dev server, where the first read timed out)."""

import re
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from shared.enums import ExportDataset, ExportFormat
from shared.exports import ExportParameters
from shared.records import RecordSelection, keys_statement


def compiled(statement) -> str:  # type: ignore[no-untyped-def]
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


def selection(**overrides) -> RecordSelection:  # type: ignore[no-untyped-def]
    project = uuid.uuid4()
    values = dict(
        project=lambda column: column == project,
        entity_ids=[uuid.uuid4()],
        device_ids=[],
        since=datetime(2026, 8, 1, tzinfo=UTC),
        until=datetime(2026, 9, 1, tzinfo=UTC),
    )
    values.update(overrides)
    return RecordSelection(**values)


def test_each_half_of_the_union_reads_one_table():
    sql = compiled(keys_statement(selection()))
    froms = re.findall(r"FROM ([a-z_, ]+?)\s*WHERE", sql)
    assert froms == ["positions", "measurements"]
    assert "measurements.project_id =" in sql
    assert "positions.project_id =" in sql


def test_the_count_wraps_the_union():
    keys = keys_statement(selection(device_ids=[uuid.uuid4()])).subquery("k")
    sql = compiled(select(func.count()).select_from(keys))
    assert sql.startswith("SELECT count(*)")
    assert sql.count("UNION") == 1
    assert "measurements.device_id IN" in sql
    assert "positions.entity_id IN" in sql


def test_a_records_export_needs_a_selection():
    """Without an owner the union has no owner filter at all and walks the whole project: the
    job started that way on the dev server scanned 220 million rows for nothing."""
    values = dict(
        dataset=ExportDataset.RECORDS,
        format=ExportFormat.CSV,
        time_from=datetime(2026, 8, 1, tzinfo=UTC),
        time_to=datetime(2026, 9, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="at least one entity or device"):
        ExportParameters(**values)
    assert ExportParameters(**values, device_ids=[uuid.uuid4()]).records_layout == "wide"
