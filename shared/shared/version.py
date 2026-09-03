"""Version of the running code.

The `VERSION` file at the repository root is written and committed before each release tag, so
`git show vX.Y.Z:VERSION` matches the tag. Docker images copy it to `/app/VERSION`. Without the
file (development checkout before the first release) the version is `v0.0.0-dev`.
"""

from pathlib import Path

DEV_VERSION = "v0.0.0-dev"

_CANDIDATES = (
    Path("/app/VERSION"),
    Path(__file__).resolve().parents[2] / "VERSION",
)


def read_version() -> str:
    for path in _CANDIDATES:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    return DEV_VERSION


__version__ = read_version()
