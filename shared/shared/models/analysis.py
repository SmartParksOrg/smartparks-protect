"""Analysis runs and their result geometries (docs/ANALYTICS_PHASE1_PLAN.md, section 6): the
derived data of the analysis subsystem, apart from the core's tables. Both are regenerable from
the core data and the run's parameters; deleting them loses nothing the core holds."""

import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.enums import AnalysisModuleKey, AnalysisStatus
from shared.models.base import Base, UuidPrimaryKeyMixin, enum_check


class AnalysisRun(UuidPrimaryKeyMixin, Base):
    """One analysis: the module, the validated parameters, the life of the run and, once
    completed, the result document. A kept run (one with a name) is the saved analysis and
    does not expire; a re-run points back through `source_run_id`."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        Index("ix_analysis_runs_project_created", "project_id", "created_at"),
        Index("ix_analysis_runs_project_module_status", "project_id", "module", "status"),
        Index(
            "ix_analysis_runs_expires",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
        enum_check("status", AnalysisStatus, "ck_analysis_runs_status"),
        enum_check("module", AnalysisModuleKey, "ck_analysis_runs_module"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    name: Mapped[str | None] = mapped_column(String(200), comment="Set when the run is kept")
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, comment="The module's parameters as validated, subjects resolved"
    )
    method_version: Mapped[str] = mapped_column(String(32), nullable=False)
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    input_count: Mapped[int | None] = mapped_column(Integer)
    excluded_count: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, comment="The result document once completed (base.ResultDocument)"
    )
    result_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Null while the run is kept by name"
    )
    source_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("analysis_runs.id", ondelete="SET NULL"), comment="Re-run from"
    )
    trace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class AnalysisGeometry(Base):
    """A polygon or point a run produced (a home range, a hotspot cell, a cluster, an area's
    use), served to the map by run and kind; the document counts them."""

    __tablename__ = "analysis_geometries"
    __table_args__ = (Index("ix_analysis_geometries_run_kind", "run_id", "kind"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, comment="The entity, or null")
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    level: Mapped[float | None] = mapped_column(Float, comment="0.5 or 0.95 for an isopleth")
    area_m2: Mapped[float | None] = mapped_column(Float)
    geom: Mapped[Any] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=True), nullable=False
    )
    properties: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
