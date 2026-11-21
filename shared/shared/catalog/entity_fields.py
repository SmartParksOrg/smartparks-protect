"""The fields of an entity by its type (decisions D399 to D405, ADR 0043): what a person can
say about an animal, a vehicle or a gate beside its name. The standard fields live here, the
same on every server; a server admin adds own fields to a type, kept as an ordered list in
`entity_types.attribute_schema`. A sub-type has its type's fields and then its own. The values
are the entity's `attributes` document; a key no field defines is kept as it is.
"""

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

KEY_PATTERN = "^[a-z][a-z0-9_]{0,62}$"
MAX_OWN_FIELDS = 64
MAX_CHOICES = 50
MAX_TEXT = 500
MAX_DOCUMENT_BYTES = 8192


class FieldKind(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    INTEGER = "integer"
    DATE = "date"
    CHOICE = "choice"
    BOOLEAN = "boolean"


_NUMERIC = (FieldKind.NUMBER, FieldKind.INTEGER)


class FieldChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str = Field(pattern=KEY_PATTERN)
    label: str = Field(min_length=1, max_length=100)


class FieldDefinition(BaseModel):
    """One field of a type. A list of these keeps the order of the form, which a JSON Schema
    object in JSONB would lose (decision D400)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=KEY_PATTERN)
    label: str = Field(min_length=1, max_length=100)
    kind: FieldKind
    unit: str | None = Field(default=None, min_length=1, max_length=16)
    choices: tuple[FieldChoice, ...] = Field(default=(), max_length=MAX_CHOICES)
    min: float | None = None
    max: float | None = None
    help: str | None = Field(default=None, min_length=1, max_length=300)
    panel: bool = Field(default=False, description="Shown on the live map's panel (D405)")
    search: bool = Field(default=False, description="Found by the search (D406); text only")

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if (self.kind == FieldKind.CHOICE) != bool(self.choices):
            raise ValueError(f"{self.key}: a choice field has choices and no other kind has")
        values = [c.value for c in self.choices]
        if len(values) != len(set(values)):
            raise ValueError(f"{self.key}: a choice value appears twice")
        if self.kind not in _NUMERIC and (
            self.unit is not None or self.min is not None or self.max is not None
        ):
            raise ValueError(f"{self.key}: a unit, a minimum and a maximum belong to a number")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"{self.key}: the minimum is above the maximum")
        if self.search and self.kind != FieldKind.TEXT:
            raise ValueError(f"{self.key}: the search reads text fields only")
        return self


class OwnFields(BaseModel):
    """The shape of `entity_types.attribute_schema`: the fields an admin added to the type.
    An empty object, which every seeded row holds, is no own fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fields: tuple[FieldDefinition, ...] = Field(default=(), max_length=MAX_OWN_FIELDS)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        keys = [f.key for f in self.fields]
        twice = sorted({k for k in keys if keys.count(k) > 1})
        if twice:
            raise ValueError(f"A field key appears twice: {', '.join(twice)}")
        return self


class EffectiveField(FieldDefinition):
    """A field as a type has it: where it comes from beside what it is."""

    origin: Literal["standard", "own"]
    inherited: bool = Field(description="Defined on the type this sub-type sits under")


F = FieldDefinition
_ASSET_NUMBER = F(key="asset_number", label="Asset number", kind=FieldKind.TEXT, search=True)

# The first standard set (decision D404), by the key of the type that defines them.
STANDARD_FIELDS: Mapping[str, tuple[FieldDefinition, ...]] = {
    "wildlife": (
        F(
            key="individual_id",
            label="ID number",
            kind=FieldKind.TEXT,
            search=True,
            help="The number or code this animal has in your own records",
        ),
        F(
            key="sex",
            label="Sex",
            kind=FieldKind.CHOICE,
            choices=(
                FieldChoice(value="female", label="Female"),
                FieldChoice(value="male", label="Male"),
                FieldChoice(value="unknown", label="Unknown"),
            ),
        ),
        F(key="birth_year", label="Birth year", kind=FieldKind.INTEGER, min=1900, max=2100),
        F(
            key="age_class",
            label="Age class",
            kind=FieldKind.CHOICE,
            choices=(
                FieldChoice(value="juvenile", label="Juvenile"),
                FieldChoice(value="subadult", label="Subadult"),
                FieldChoice(value="adult", label="Adult"),
            ),
        ),
        F(
            key="vhf_frequency_mhz",
            label="VHF frequency",
            kind=FieldKind.NUMBER,
            unit="MHz",
            min=30,
            max=1000,
            panel=True,
            help="The frequency of a VHF tag on the animal",
        ),
        F(
            key="ear_tag",
            label="Ear tag number",
            kind=FieldKind.TEXT,
            panel=True,
            search=True,
            help="The official number, 4 to 20 letters and digits, such as NL 123456789012",
        ),
        F(key="breed", label="Breed", kind=FieldKind.TEXT),
        F(key="weight_kg", label="Weight", kind=FieldKind.NUMBER, unit="kg", min=0, max=200000),
    ),
    "vehicle": (
        F(
            key="licence_plate",
            label="Licence plate",
            kind=FieldKind.TEXT,
            panel=True,
            search=True,
        ),
        F(key="make", label="Brand", kind=FieldKind.TEXT),
        F(key="model", label="Model", kind=FieldKind.TEXT),
        F(key="fleet_number", label="Fleet number", kind=FieldKind.TEXT, search=True),
    ),
    "person": (
        F(key="call_sign", label="Call sign", kind=FieldKind.TEXT, panel=True, search=True),
        F(key="team", label="Team", kind=FieldKind.TEXT),
    ),
    "infrastructure": (_ASSET_NUMBER,),
    "equipment": (_ASSET_NUMBER,),
    "environmental_sensor": (_ASSET_NUMBER,),
}


class FieldError(ValueError):
    """A definition or a value that cannot stand; the message names the field."""


def own_fields(attribute_schema: Mapping[str, Any] | None) -> tuple[FieldDefinition, ...]:
    """The own fields a type's `attribute_schema` holds. Raises pydantic's `ValidationError`
    on a document of another shape."""
    return OwnFields.model_validate(attribute_schema or {}).fields


def fields_of(
    key: str,
    attribute_schema: Mapping[str, Any] | None,
    parent: tuple[str, Mapping[str, Any] | None] | None = None,
) -> list[EffectiveField]:
    """The fields of a type in the order of the form: its parent's standard fields, the
    parent's own, then its standard fields and its own. `parent` is the key and the
    `attribute_schema` of the type a sub-type sits under. A key counts once, the first time."""
    layers: list[tuple[Sequence[FieldDefinition], Literal["standard", "own"], bool]] = []
    if parent is not None:
        layers.append((STANDARD_FIELDS.get(parent[0], ()), "standard", True))
        layers.append((own_fields(parent[1]), "own", True))
    layers.append((STANDARD_FIELDS.get(key, ()), "standard", False))
    layers.append((own_fields(attribute_schema), "own", False))
    seen: set[str] = set()
    out: list[EffectiveField] = []
    for definitions, origin, inherited in layers:
        for definition in definitions:
            if definition.key in seen:
                continue
            seen.add(definition.key)
            out.append(
                EffectiveField(**definition.model_dump(), origin=origin, inherited=inherited)
            )
    return out


def check_own(own: Sequence[FieldDefinition], taken: set[str]) -> None:
    """Refuse an own field under a key the type has already from elsewhere: a standard field,
    its parent's, or a sub-type's."""
    clash = sorted({f.key for f in own} & taken)
    if clash:
        raise FieldError(f"A field with this key exists already: {', '.join(clash)}")


def _ear_tag(value: str) -> str:
    """Upper case without spaces, 4 to 20 letters and digits (decision D403): the EU form of
    two letters and up to twelve digits and the numbers of other countries."""
    code = re.sub(r"\s+", "", value).upper()
    if not re.fullmatch(r"[A-Z0-9]{4,20}", code):
        raise FieldError("Ear tag number (ear_tag): 4 to 20 letters and digits")
    return code


# A standard text field with a form of its own, by key.
_TEXT_FORMS: Mapping[str, Callable[[str], str]] = {"ear_tag": _ear_tag}


def _value(field: FieldDefinition, value: Any) -> Any:
    """`value` as the field stores it, or None for an empty one. A refusal names the field
    by its label, since a person reads it in the dialog, with the key behind it."""
    key = f"{field.label} ({field.key})"
    if field.kind == FieldKind.BOOLEAN:
        if not isinstance(value, bool):
            raise FieldError(f"{key}: yes or no")
        return value
    if field.kind in _NUMERIC:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise FieldError(f"{key}: a number")
        if not math.isfinite(value):
            raise FieldError(f"{key}: a number")
        if field.kind == FieldKind.INTEGER:
            if value != int(value):
                raise FieldError(f"{key}: a whole number")
            value = int(value)
        if field.min is not None and value < field.min:
            raise FieldError(f"{key}: at least {field.min:g}")
        if field.max is not None and value > field.max:
            raise FieldError(f"{key}: at most {field.max:g}")
        return value
    if not isinstance(value, str):
        raise FieldError(f"{key}: text")
    text = value.strip()
    if not text:
        return None
    if field.kind == FieldKind.DATE:
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            raise FieldError(f"{key}: a date as YYYY-MM-DD") from None
    if field.kind == FieldKind.CHOICE:
        if text not in {c.value for c in field.choices}:
            raise FieldError(f"{key}: one of {', '.join(c.value for c in field.choices)}")
        return text
    if len(text) > MAX_TEXT:
        raise FieldError(f"{key}: at most {MAX_TEXT} characters")
    form = _TEXT_FORMS.get(field.key)
    return form(text) if form else text


def validate_attributes(
    fields: Sequence[FieldDefinition], values: Mapping[str, Any]
) -> dict[str, Any]:
    """An entity's document as it is stored (decision D401): the value of a defined field
    checked by its kind, an empty one left out, a key no field defines kept untouched. Raises
    `FieldError` naming the field."""
    by_key = {f.key: f for f in fields}
    out: dict[str, Any] = {}
    for key, value in values.items():
        field = by_key.get(key)
        if field is None:
            out[key] = value
            continue
        if value is None:
            continue
        stored = _value(field, value)
        if stored is not None:
            out[key] = stored
    if len(json.dumps(out).encode()) > MAX_DOCUMENT_BYTES:
        raise FieldError(f"The fields of an entity hold at most {MAX_DOCUMENT_BYTES} bytes")
    return out
