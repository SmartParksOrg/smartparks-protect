"""A device's place set by a person (decision D261), for hardware that does not move and does not
report where it is: a Bluetooth scanner on a post, a fence monitor. A sighting by such a device
can then say where the seen device was (decision D258).

Revision ID: 0043
Revises: 0042
"""

from __future__ import annotations

import geoalchemy2
import sqlalchemy as sa

from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "static_geom",
            geoalchemy2.types.Geometry(
                geometry_type="POINT", srid=4326, spatial_index=True, from_text="ST_GeomFromEWKT"
            ),
            nullable=True,
            comment="Where this device is, set by a person, for hardware that does not move and "
            "does not report its place (decision D261): a scanner on a post, a fence monitor",
        ),
    )
    op.add_column(
        "devices",
        sa.Column(
            "static_position_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the static place was last set",
        ),
    )
    # `location_source` carries no check constraint in the database; the API validates it, so
    # the new `static` value needs no migration of its own


def downgrade() -> None:
    op.execute("UPDATE devices SET location_source = 'device' WHERE location_source = 'static'")
    op.drop_column("devices", "static_position_at")
    op.drop_geospatial_column("devices", "static_geom")
