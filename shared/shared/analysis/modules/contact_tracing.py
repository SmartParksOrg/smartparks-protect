"""Who met whom (docs/ANALYTICS_CONTACT_TRACING_PLAN.md, section 4).

Two kinds of evidence in one module and never two modules (decision D255): the sightings a device
reported, and the proximity two subjects' fixes show. They answer the same question differently
and they fail differently, so a reader wants them side by side — a pair found by both is solid,
a pair found only by fixes rests on how often the animals report, and a pair found only by
Bluetooth was heard but never fixed together.

What this module does not do is infer transmission, and it says so where a reader will see it. A
contact is evidence that two animals were near each other. Everything past that is a question for
somebody who knows the disease.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.analysis.base import (
    Chart,
    Geometry,
    Period,
    Provenance,
    ResultDocument,
    RunContext,
    RunResult,
    Subject,
    Table,
    Warning,
)
from shared.analysis.limits import MAX_FIXES_PER_SUBJECT, MAX_SUBJECTS_CONTACT
from shared.analysis.parameters import CommonParameters
from shared.analysis.primitives.contacts import (
    PairContacts,
    Sighting,
    by_pair,
    pair_key,
)
from shared.analysis.primitives.proximity import (
    PairProximity,
    distance_is_within_accuracy,
    pair_proximity,
    sampling_is_coarser_than,
)
from shared.analysis.primitives.trajectory import Trajectory, load_trajectory
from shared.enums import ContactResolution
from shared.models import (
    Device,
    DeviceContact,
    DeviceEntityAssignment,
    Entity,
    EntityType,
    Project,
)
from shared.timeutil import utc_now

METHOD_VERSION = "contact_tracing/1"

#: The columns of the pair table, worst first (design 4.3).
PAIR_COLUMNS = [
    "pair",
    "period",
    "contacts",
    "hours",
    "evidence",
    "sightings",
    "signal",
    "closest_m",
    "first",
    "last",
]


class ContactParameters(CommonParameters):
    """The options of design section 4.1.

    `max_distance_m` and `max_time_s` are the two Tim asked to be configurable, with defaults
    that say what they mean: a hundred metres is beyond GNSS error but within sight, ten minutes
    is tighter than the usual fix interval."""

    bluetooth: bool = Field(default=True, description="Use the sightings devices reported")
    proximity: bool = Field(default=True, description="Use the fixes the subjects made")
    max_distance_m: float = Field(default=100, ge=5, le=10_000)
    max_time_s: float = Field(default=600, ge=30, le=86_400)
    min_rssi_dbm: int | None = Field(default=None, ge=-128, le=0)
    min_contact_s: float = Field(default=0, ge=0, le=86_400)


@dataclass(slots=True)
class Pair:
    """Everything known about two subjects over one period, from both kinds of evidence."""

    a: uuid.UUID
    b: uuid.UUID
    period: str
    sightings: PairContacts | None = None
    fixes: PairProximity | None = None
    places: list[tuple[float, float]] = field(default_factory=list)

    @property
    def contacts(self) -> int:
        return (self.sightings.contacts if self.sightings else 0) + (
            self.fixes.contacts if self.fixes else 0
        )

    @property
    def seconds(self) -> float:
        return (self.sightings.seconds if self.sightings else 0.0) + (
            self.fixes.seconds if self.fixes else 0.0
        )

    @property
    def evidence(self) -> str:
        """Which kinds saw this pair. The most useful column in the table: a pair both kinds
        found is solid, and one only proximity found rests on sampling."""
        kinds = []
        if self.sightings and self.sightings.contacts:
            kinds.append("bluetooth")
        if self.fixes and self.fixes.contacts:
            kinds.append("proximity")
        return " + ".join(kinds) if kinds else "none"

    @property
    def first_at(self) -> datetime | None:
        times = [
            t
            for t in (
                self.sightings.first_at if self.sightings else None,
                self.fixes.first_at if self.fixes else None,
            )
            if t is not None
        ]
        return min(times) if times else None

    @property
    def last_at(self) -> datetime | None:
        times = [
            t
            for t in (
                self.sightings.last_at if self.sightings else None,
                self.fixes.last_at if self.fixes else None,
            )
            if t is not None
        ]
        return max(times) if times else None


async def load_sightings(
    session: AsyncSession,
    entity_ids: list[uuid.UUID],
    period: Period,
) -> tuple[list[Sighting], int, int]:
    """The resolved sightings between the chosen subjects, and what was left out.

    Only sightings whose counterpart resolved to a device carrying one of the subjects: an
    unknown neighbour is a real finding (decision D253) but it is not a pair, and an ambiguous
    one is deliberately in no pair figure at all (D254). Both are counted so the run can say how
    many it set aside rather than quietly narrowing the answer."""
    chosen = set(entity_ids)
    rows = (
        await session.execute(
            select(
                DeviceContact.time,
                DeviceContact.entity_id,
                DeviceContact.contact_entity_id,
                DeviceContact.rssi_dbm,
                DeviceContact.sightings,
                DeviceContact.resolution,
            ).where(
                DeviceContact.time >= period.time_from,
                DeviceContact.time < period.time_to,
                DeviceContact.entity_id.in_(chosen),
            )
        )
    ).all()
    sightings: list[Sighting] = []
    unknown = ambiguous = 0
    for row in rows:
        if row.resolution == ContactResolution.AMBIGUOUS:
            ambiguous += 1
            continue
        if row.resolution != ContactResolution.RESOLVED or row.contact_entity_id is None:
            unknown += 1
            continue
        if row.contact_entity_id not in chosen or row.contact_entity_id == row.entity_id:
            continue
        sightings.append(
            Sighting(
                time=row.time,
                observer=row.entity_id,
                seen=row.contact_entity_id,
                rssi_dbm=row.rssi_dbm,
                sightings=int(row.sightings or 1),
            )
        )
    return sightings, unknown, ambiguous


async def standing_places(
    session: AsyncSession, subjects: list[Subject]
) -> dict[uuid.UUID, tuple[float, float]]:
    """Where a subject is, for the subjects carried by a device that does not move (D261).

    A reader on a post is the commonest observer there is, and its place is known exactly. That
    is the whole answer to "where did this contact happen" for a deployment of fixed readers,
    and without it the map of such a study is empty while the place sits in a column."""
    if not subjects:
        return {}
    rows = (
        await session.execute(
            select(
                DeviceEntityAssignment.entity_id,
                func.ST_Y(Device.static_geom),
                func.ST_X(Device.static_geom),
            )
            .join(Device, Device.id == DeviceEntityAssignment.device_id)
            .where(
                DeviceEntityAssignment.entity_id.in_([s.id for s in subjects]),
                DeviceEntityAssignment.validity.op("@>")(utc_now()),
                Device.static_geom.is_not(None),
            )
        )
    ).all()
    return {row[0]: (float(row[1]), float(row[2])) for row in rows}


def sighting_places(
    pair: Pair,
    standing: dict[uuid.UUID, tuple[float, float]],
    tracks: dict[uuid.UUID, Trajectory],
) -> list[tuple[float, float]]:
    """Where the sightings of a pair happened: the observer's own place at the time.

    A sighting says one device heard another, so the place of the meeting is the place of the
    one that did the hearing — exactly, when that one stands on a post, and from its nearest fix
    when it was walking about. The device that was heard has no say: it is the one whose position
    the sighting was meant to establish."""
    out: list[tuple[float, float]] = []
    for meeting in pair.sightings.meetings if pair.sightings else []:
        for observer in sorted(meeting.observers, key=str):
            if observer in standing:
                out.append(standing[observer])
                break
            track = tracks.get(observer)
            if track is not None and len(track):
                i = int(np.argmin(np.abs(track.times - meeting.start.timestamp())))
                out.append((float(track.lat[i]), float(track.lon[i])))
                break
    return out


def median_interval_s(track: Trajectory) -> float | None:
    """How often a subject actually reported, from its own fixes.

    What it did, not what its settings declare: a collar set to five minutes that manages an
    hour because the sky is poor would pass a check against the setting and fail reality, and it
    is reality that decides whether a proximity means anything."""
    if len(track) < 3:
        return None
    gaps = np.diff(track.times)
    gaps = gaps[gaps > 0]
    return float(np.median(gaps)) if gaps.size else None


def median_accuracy_m(track: Trajectory) -> float | None:
    """The typical accuracy the subject's fixes claim, ignoring the ones that claim none."""
    known = track.accuracy_m[~np.isnan(track.accuracy_m)]
    return float(np.median(known)) if known.size else None


def sampling_warnings(
    subjects: list[Subject],
    tracks: dict[uuid.UUID, Trajectory],
    params: ContactParameters,
) -> list[Warning]:
    """The three warnings without which the figures mislead (design 4.2).

    They are warnings and not notices for the first two, because a reader who misses them draws
    a conclusion the data does not support."""
    out: list[Warning] = []
    for subject in subjects:
        track = tracks.get(subject.id)
        if track is None or len(track) == 0:
            continue
        interval = median_interval_s(track)
        if sampling_is_coarser_than(interval, params.max_time_s):
            out.append(
                Warning(
                    code="sampling_coarser_than_window",
                    subject_id=subject.id,
                    text=(
                        f"{subject.name} reports about every {_minutes(interval)}, which is "
                        f"longer than the {_minutes(params.max_time_s)} a proximity is judged "
                        "in. Two animals an hour apart in the record may have been a kilometre "
                        "apart in between, so its proximities are coincidences of sampling as "
                        "much as of animals."
                    ),
                )
            )
        accuracy = median_accuracy_m(track)
        if distance_is_within_accuracy(params.max_distance_m, accuracy):
            out.append(
                Warning(
                    code="distance_within_accuracy",
                    subject_id=subject.id,
                    text=(
                        f"{subject.name}'s fixes are good to about {round(accuracy or 0)} m and "
                        f"a proximity is being called at {round(params.max_distance_m)} m. At "
                        "that distance the receiver alone could put two animals together."
                    ),
                )
            )
    if params.proximity:
        out.append(
            Warning(
                code="proximity_uses_device_fixes",
                level="notice",
                text=(
                    "Proximity reads the fixes the devices made themselves. A position the "
                    "network estimated is not a fix and takes no part, however recent it is."
                ),
            )
        )
    return out


def _minutes(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds < 90:
        return f"{round(seconds)} s"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    return f"{round(seconds / 3600, 1)} h"


def _hours(seconds: float) -> float:
    return round(seconds / 3600, 2)


def _name(subjects: list[Subject]) -> dict[uuid.UUID, str]:
    return {s.id: s.name for s in subjects}


def pair_label(names: dict[uuid.UUID, str], a: uuid.UUID, b: uuid.UUID) -> str:
    """The two names, in their own order rather than their ids'.

    A pair is stored under whichever id sorts first, which is an implementation detail and a
    random one. A reader should see the same two animals written the same way every time, and
    should be able to find them alphabetically."""
    return " · ".join(sorted((names.get(a, "?"), names.get(b, "?"))))


def pair_rows(pairs: list[Pair], subjects: list[Subject]) -> list[list[Any]]:
    """The pair table, the pairs that met most first."""
    names = _name(subjects)
    ordered = sorted(pairs, key=lambda p: (-p.seconds, -p.contacts))
    rows: list[list[Any]] = []
    for pair in ordered:
        bluetooth = pair.sightings
        rows.append(
            [
                pair_label(names, pair.a, pair.b),
                pair.period,
                pair.contacts,
                _hours(pair.seconds),
                pair.evidence,
                bluetooth.sightings if bluetooth else 0,
                bluetooth.band if bluetooth else None,
                pair.fixes.closest_m if pair.fixes else None,
                pair.first_at.isoformat() if pair.first_at else None,
                pair.last_at.isoformat() if pair.last_at else None,
            ]
        )
    return rows


def subject_rows(pairs: list[Pair], subjects: list[Subject]) -> list[list[Any]]:
    """One row per subject: how many others it met, and for how long in total."""
    met: dict[tuple[str, uuid.UUID], set[uuid.UUID]] = defaultdict(set)
    seconds: dict[tuple[str, uuid.UUID], float] = defaultdict(float)
    contacts: dict[tuple[str, uuid.UUID], int] = defaultdict(int)
    for pair in pairs:
        if not pair.contacts:
            continue
        for mine, theirs in ((pair.a, pair.b), (pair.b, pair.a)):
            met[(pair.period, mine)].add(theirs)
            seconds[(pair.period, mine)] += pair.seconds
            contacts[(pair.period, mine)] += pair.contacts
    names = _name(subjects)
    rows = [
        [
            names.get(subject_id, "?"),
            period,
            len(others),
            contacts[(period, subject_id)],
            _hours(seconds[(period, subject_id)]),
        ]
        for (period, subject_id), others in met.items()
    ]
    return sorted(rows, key=lambda r: (-int(r[2]), -float(r[4])))


def daily_series(pairs: list[Pair], zone: tzinfo = UTC) -> list[dict[str, Any]]:
    """Contacts per day, both kinds together: when the meeting happened at all.

    A day is the project's day, as the movement and grazing modules count theirs: a meeting at
    one in the morning in the Netherlands belongs to that night, not to the UTC day before."""
    per_day: dict[str, int] = defaultdict(int)
    for pair in pairs:
        for when in _moments(pair):
            per_day[when.astimezone(zone).date().isoformat()] += 1
    # `data`, as every other module's series does and as the interface reads: under any other
    # name the chart draws an empty box with a title, which is what it did
    return [{"name": "contacts", "data": [[d, n] for d, n in sorted(per_day.items())]}]


def hour_series(pairs: list[Pair], zone: tzinfo = UTC) -> list[dict[str, Any]]:
    """The hour of day a contact started, in the project's own time. When animals meet is half
    the question (design 4.3), and "at dawn" is only readable on the clock the reader keeps
    (reviewed 2026-09-19: the rose was in UTC, two hours off for the PWN project)."""
    hours = [0] * 24
    for pair in pairs:
        for when in _moments(pair):
            hours[when.astimezone(zone).hour] += 1
    return [{"name": "contacts", "data": [[h, n] for h, n in enumerate(hours)]}]


def _moments(pair: Pair) -> list[datetime]:
    out: list[datetime] = []
    if pair.sightings:
        out.extend(m.start for m in pair.sightings.meetings)
    if pair.fixes:
        out.extend(e.start for e in pair.fixes.encounters)
    return out


def network_series(pairs: list[Pair], subjects: list[Subject]) -> list[dict[str, Any]]:
    """The contact network: nodes are subjects, edges are pairs that met.

    The one picture that makes a contact study legible, and the only new visual the phase adds
    (design 4.3). The data is here; the drawing is the interface's and the report's."""
    met: dict[uuid.UUID, int] = defaultdict(int)
    edges = []
    for pair in pairs:
        if not pair.contacts:
            continue
        met[pair.a] += pair.contacts
        met[pair.b] += pair.contacts
        edges.append(
            {
                "source": str(pair.a),
                "target": str(pair.b),
                "contacts": pair.contacts,
                "hours": _hours(pair.seconds),
                "evidence": pair.evidence,
            }
        )
    nodes = [
        {"id": str(s.id), "name": s.name, "contacts": met.get(s.id, 0), "type": s.type}
        for s in subjects
    ]
    return [{"name": "network", "nodes": nodes, "edges": edges}]


def contact_geometries(pairs: list[Pair], subjects: list[Subject]) -> list[Geometry]:
    """Where the pairs met, as points sized by how often (design 4.3).

    Usually a water hole, which is the answer a map can give that a table cannot."""
    names = _name(subjects)
    out: list[Geometry] = []
    for pair in pairs:
        if not pair.places:
            continue
        lat = float(np.mean([p[0] for p in pair.places]))
        lon = float(np.mean([p[1] for p in pair.places]))
        out.append(
            Geometry(
                kind="contact",
                label=pair_label(names, pair.a, pair.b),
                geojson={"type": "Point", "coordinates": [lon, lat]},
                properties={
                    "contacts": pair.contacts,
                    "hours": _hours(pair.seconds),
                    "evidence": pair.evidence,
                    "period": pair.period,
                    # when, which is the first thing somebody clicking a point asks
                    "first": pair.first_at.isoformat() if pair.first_at else None,
                    "last": pair.last_at.isoformat() if pair.last_at else None,
                },
            )
        )
    return out


def build_document(
    subjects: list[Subject],
    periods: list[Period],
    pairs: list[Pair],
    params: ContactParameters,
    *,
    warnings: list[Warning],
    input_count: int,
    excluded_count: int,
    unknown: int,
    ambiguous: int,
    geometries: dict[str, int] | None = None,
    zone: tzinfo = UTC,
) -> ResultDocument:
    """The result document: the network, the tables, the charts and what was set aside."""
    met = [p for p in pairs if p.contacts]
    summary: dict[str, Any] = {
        "pairs_met": len(met),
        "pairs_possible": len(subjects) * (len(subjects) - 1) // 2,
        "contacts": sum(p.contacts for p in met),
        "hours": _hours(sum(p.seconds for p in met)),
        "by_evidence": {
            kind: len([p for p in met if p.evidence == kind])
            for kind in ("bluetooth", "proximity", "bluetooth + proximity")
        },
        "unknown_sightings": unknown,
        "ambiguous_sightings": ambiguous,
        "limitations": [
            "A contact is evidence that two subjects were near each other. It is not evidence "
            "that anything passed between them, and this module infers no transmission.",
            "A signal is banded, never converted to metres: that needs a calibration per device "
            "and per what stands between them which nobody has.",
        ],
    }
    tables = [
        Table(key="pairs", columns=PAIR_COLUMNS, rows=pair_rows(pairs, subjects)),
        Table(
            key="subjects",
            columns=["subject", "period", "others_met", "contacts", "hours"],
            rows=subject_rows(pairs, subjects),
        ),
    ]
    charts = [
        Chart(key="contacts_per_day", kind="bar", unit=None, series=daily_series(met, zone)),
        Chart(key="contacts_by_hour", kind="rose", unit=None, series=hour_series(met, zone)),
        Chart(key="network", kind="network", unit=None, series=network_series(met, subjects)),
    ]
    return ResultDocument(
        module="contact_tracing",
        method_version=METHOD_VERSION,
        subjects=subjects,
        periods=periods,
        summary=summary,
        tables=tables,
        charts=charts,
        geometries=geometries or {},
        warnings=warnings,
        provenance=Provenance(
            module="contact_tracing",
            method_version=METHOD_VERSION,
            subjects=subjects,
            periods=periods,
            parameters=params.model_dump(mode="json"),
            input_count=input_count,
            excluded_count=excluded_count,
            computed_at=datetime.now(UTC),
            sources=["device_contacts", "positions"],
        ),
    )


class ContactTracingModule:
    key = "contact_tracing"
    label = "Contact tracing"
    version = METHOD_VERSION
    parameters: type[BaseModel] = ContactParameters

    async def run(self, ctx: RunContext, params: BaseModel) -> RunResult:
        assert isinstance(params, ContactParameters)
        session = ctx.session
        rows = (
            await session.execute(
                select(Entity.id, Entity.name, EntityType.label)
                .join(EntityType, EntityType.id == Entity.entity_type_id)
                .where(Entity.id.in_(params.entity_ids), Entity.project_id == ctx.project_id)
                .order_by(Entity.name)
            )
        ).all()
        subjects = [
            Subject(id=r.id, name=r.name, type=r.label) for r in rows[:MAX_SUBJECTS_CONTACT]
        ]
        tz = await session.scalar(select(Project.timezone).where(Project.id == ctx.project_id))
        zone = ZoneInfo(tz) if tz else UTC
        periods = [Period(key="main", time_from=params.time_from, time_to=params.time_to)]
        if params.comparison:
            periods.append(
                Period(
                    key="comparison",
                    time_from=params.comparison.time_from,
                    time_to=params.comparison.time_to,
                )
            )

        warnings: list[Warning] = []
        if len(rows) > MAX_SUBJECTS_CONTACT:
            warnings.append(
                Warning(
                    code="subjects_capped",
                    text=(
                        f"{len(rows)} subjects were chosen and the first {MAX_SUBJECTS_CONTACT} "
                        "by name were used. Every pair is compared with every other, so the work "
                        "grows with the square of the subjects; a smaller selection is a better "
                        "question anyway."
                    ),
                )
            )
        if not params.bluetooth and not params.proximity:
            warnings.append(
                Warning(
                    code="no_evidence_chosen",
                    text="Both kinds of evidence are switched off, so there is nothing to find.",
                )
            )

        pairs: list[Pair] = []
        input_count = excluded_count = unknown_total = ambiguous_total = 0
        steps = max(1, len(periods) * 2)
        done = 0
        for period in periods:
            index: dict[tuple[uuid.UUID, uuid.UUID], Pair] = {}
            if params.bluetooth:
                await ctx.progress(int(done * 80 / steps), f"sightings ({period.key})")
                sightings, unknown, ambiguous = await load_sightings(
                    session, [s.id for s in subjects], period
                )
                unknown_total += unknown
                ambiguous_total += ambiguous
                input_count += len(sightings) + unknown + ambiguous
                excluded_count += unknown + ambiguous
                for key, found in by_pair(
                    sightings,
                    min_rssi_dbm=params.min_rssi_dbm,
                    min_contact_s=params.min_contact_s,
                ).items():
                    index[key] = Pair(a=key[0], b=key[1], period=period.key, sightings=found)
            done += 1

            tracks: dict[uuid.UUID, Trajectory] = {}
            if params.proximity:
                await ctx.progress(int(done * 80 / steps), f"fixes ({period.key})")
                for subject in subjects:
                    track = await load_trajectory(
                        session,
                        subject.id,
                        period.time_from,
                        period.time_to,
                        max_fixes=MAX_FIXES_PER_SUBJECT,
                    )
                    tracks[subject.id] = track
                    input_count += len(track)
                warnings.extend(sampling_warnings(subjects, tracks, params))
                for i, first in enumerate(subjects):
                    for second in subjects[i + 1 :]:
                        near = pair_proximity(
                            tracks[first.id],
                            tracks[second.id],
                            max_distance_m=params.max_distance_m,
                            max_time_s=params.max_time_s,
                            min_contact_s=params.min_contact_s,
                        )
                        if not near.contacts:
                            continue
                        key = pair_key(first.id, second.id)
                        pair = index.setdefault(key, Pair(a=key[0], b=key[1], period=period.key))
                        pair.fixes = near
                        pair.places = _midpoints(tracks[first.id], tracks[second.id], near)
            done += 1
            # a pair the fixes found already has a midpoint; one only a sighting found takes the
            # place of whichever device did the hearing (design section 4.3)
            standing = await standing_places(session, subjects)
            for pair in index.values():
                if not pair.places:
                    pair.places = sighting_places(pair, standing, tracks)
            pairs.extend(index.values())

        await ctx.progress(95, "document")
        # once each: a comparison period runs the sampling checks a second time over the same
        # subjects, and a warning shown twice reads as two problems
        seen: set[tuple[str, uuid.UUID | None, str]] = set()
        once: list[Warning] = []
        for warning in warnings:
            mark = (warning.code, warning.subject_id, warning.text)
            if mark not in seen:
                seen.add(mark)
                once.append(warning)
        warnings = once
        geometries = contact_geometries([p for p in pairs if p.contacts], subjects)
        counts: dict[str, int] = {}
        for geometry in geometries:
            counts[geometry.kind] = counts.get(geometry.kind, 0) + 1
        document = build_document(
            subjects,
            periods,
            pairs,
            params,
            warnings=warnings,
            input_count=input_count,
            excluded_count=excluded_count,
            unknown=unknown_total,
            ambiguous=ambiguous_total,
            geometries=counts,
            zone=zone,
        )
        return RunResult(document=document, geometries=geometries)


def _midpoints(a: Trajectory, b: Trajectory, found: PairProximity) -> list[tuple[float, float]]:
    """Where each encounter happened: the midpoint of the two subjects at its start.

    The midpoint and not one animal's fix, because neither of them is the place — the meeting
    is, and it was somewhere between them."""
    out: list[tuple[float, float]] = []
    for encounter in found.encounters:
        when = encounter.start.timestamp()
        i = int(np.argmin(np.abs(a.times - when)))
        j = int(np.argmin(np.abs(b.times - when)))
        out.append(((a.lat[i] + b.lat[j]) / 2, (a.lon[i] + b.lon[j]) / 2))
    return out
