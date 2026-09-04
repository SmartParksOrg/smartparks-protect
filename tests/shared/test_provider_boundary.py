"""Provider-specific code lives only under `shared/connectivity/adapters/` (architecture 2,
definition of done). Nothing else in the backend or the frontend may name a provider; the
frontend learns adapters from `GET /data-sources/adapters`."""

import ast
import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = re.compile(
    r"(chirpstack|loriot|kpn|thingpark|actility|netmore|akenza|traccar|cloudloop)", re.I
)

# Places that may name providers: the adapters, their registry, provider docs and fixtures,
# development tooling for the local ChirpStack, the compose profile, the driver for OpenCollar
# satellite ports (Iridium is a channel name there), enumerations that name channels.
ALLOWED_BACKEND = (
    "shared/shared/connectivity/adapters/",
    "shared/shared/connectivity/registry.py",
    "shared/shared/enums.py",
    "shared/shared/device_drivers/opencollar/",
    "scripts/chirpstack_bootstrap.py",
    "scripts/simulate_opencollar.py",
    "services/api/alembic/",
)
BACKEND_ROOTS = (
    "shared/shared",
    "services/api/protect_api",
    "services/ingest",
    "services/decoder",
    "services/export",
    "services/rules",
    "services/automation",
    "scripts",
)


def _backend_files():
    for root in BACKEND_ROOTS:
        for path in (ROOT / root).rglob("*.py"):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith(ALLOWED_BACKEND):
                continue
            yield rel, path


def _docstring_lines(source: str) -> set[int]:
    lines: set[int] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                lines.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
    return lines


def _code_hits(source: str) -> list[tuple[int, str]]:
    """Provider names in code: names, attributes and string literals, not comments or
    docstrings (prose may explain what a provider is)."""
    skip = _docstring_lines(source)
    hits = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT or token.start[0] in skip:
            continue
        if token.type in (tokenize.NAME, tokenize.STRING) and PROVIDERS.search(token.string):
            hits.append((token.start[0], token.line.strip()[:80]))
    return hits


def test_backend_names_no_provider_outside_adapters():
    offenders = []
    for rel, path in _backend_files():
        for number, line in _code_hits(path.read_text()):
            offenders.append(f"{rel}:{number}: {line}")
    assert offenders == [], "provider names outside the adapters:\n" + "\n".join(offenders)


def test_frontend_names_no_provider():
    src = ROOT / "services/frontend/src"
    offenders = []
    for path in src.rglob("*"):
        if path.suffix not in (".ts", ".tsx") or path.name == "schema.d.ts":
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if PROVIDERS.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:80]}")
    assert offenders == [], "provider names in the frontend:\n" + "\n".join(offenders)
