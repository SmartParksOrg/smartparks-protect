"""Finding an entity by what its fields say (decision D406): the licence plate, the ear tag,
the call sign. One condition for the site-wide search and the Entities list."""

from sqlalchemy import ColumnElement, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.catalog.entity_fields import STANDARD_FIELDS, own_fields
from shared.models import Entity, EntityType


async def searchable_keys(session: AsyncSession) -> list[str]:
    """The keys of the fields marked for the search: the standard ones and those an admin
    added to a type. The keys of every type together, so a value kept from another type is
    found as well."""
    keys = {f.key for fields in STANDARD_FIELDS.values() for f in fields if f.search}
    schemas = await session.scalars(
        select(EntityType.attribute_schema).where(
            EntityType.attribute_schema != text("'{}'::jsonb")
        )
    )
    for schema in schemas:
        keys |= {f.key for f in own_fields(schema) if f.search}
    return sorted(keys)


async def name_or_field_contains(session: AsyncSession, q: str) -> ColumnElement[bool]:
    """The entity's name or one of its searchable fields contains `q`, case-insensitive. A
    field is also tried without the spaces of `q`, since a code such as an ear tag is stored
    without them."""
    term = q.strip()
    patterns = {f"%{term}%", f"%{''.join(term.split())}%"}
    return or_(
        Entity.name.ilike(f"%{term}%"),
        *(
            Entity.attributes[key].astext.ilike(pattern)
            for key in await searchable_keys(session)
            for pattern in sorted(patterns)
        ),
    )
