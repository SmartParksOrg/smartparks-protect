"""The server's own texts in the reader's language (decision D240). The server keeps
composing and storing English; on the way out the API translates the fixed texts it knows
(event titles from the shipped rule templates and the drivers, the explanations, the
analysis warnings) by the language the request asks for. A text the catalogue does not
know stays as it is, so nothing is ever lost, and a person's own words (a rule name, a
comment) are never touched.

A catalogue entry may carry `{placeholders}`: the English key is then a template, matched
against the text as a pattern, and the Dutch template is filled with what the pattern
captured. "{entity} left {feature}" matches "Rhino 14 left North fence" and gives
"Rhino 14 heeft North fence verlaten"."""

from __future__ import annotations

import re
from functools import lru_cache

from shared.i18n.nl import NL

SUPPORTED: tuple[str, ...] = ("en", "nl")
DEFAULT = "en"
CATALOGUES: dict[str, dict[str, str]] = {"nl": NL}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def resolve_language(accept_language: str | None) -> str:
    """The most wanted supported language of an `Accept-Language` header
    ("nl-NL,nl;q=0.9,en;q=0.8" gives "nl"); English when the header names none. The quality
    values decide, not the order the parts happen to be in, so "en;q=0.5,nl" gives "nl"
    (reviewed 2026-09-18: the order alone gave "en")."""
    if not accept_language:
        return DEFAULT
    best: tuple[float, int, str] | None = None
    for position, part in enumerate(accept_language.split(",")):
        code, _, parameters = part.partition(";")
        code = code.strip().lower()
        if not code:
            continue
        base = code.split("-")[0]
        if base not in SUPPORTED:
            continue
        quality = 1.0
        for parameter in parameters.split(";"):
            name, _, value = parameter.partition("=")
            if name.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if quality <= 0:
            continue  # q=0 refuses that language
        # the highest quality wins; equal qualities keep the order of the header
        candidate = (quality, -position, base)
        if best is None or candidate > best:
            best = candidate
    return best[2] if best else DEFAULT


@lru_cache(maxsize=8)
def _patterns(language: str) -> tuple[tuple[re.Pattern[str], str], ...]:
    """The catalogue's templates as patterns: each placeholder captures a run of text."""
    out = []
    for key, value in CATALOGUES.get(language, {}).items():
        if "{" not in key:
            continue
        pieces = []
        last = 0
        for match in _PLACEHOLDER.finditer(key):
            pieces.append(re.escape(key[last : match.start()]))
            pieces.append(f"(?P<{match.group(1)}>.+?)")
            last = match.end()
        pieces.append(re.escape(key[last:]))
        out.append((re.compile("^" + "".join(pieces) + "$", re.DOTALL), value))
    return tuple(out)


def translate(text: str | None, language: str) -> str | None:
    """`text` in `language`: the catalogue's exact entry, else the first template that
    matches, else the text itself."""
    if text is None or language == DEFAULT or language not in CATALOGUES:
        return text
    exact = CATALOGUES[language].get(text)
    if exact is not None:
        return exact
    for pattern, template in _patterns(language):
        match = pattern.match(text)
        if match:
            try:
                return template.format(**match.groupdict())
            except (KeyError, IndexError):
                return text
    return text
