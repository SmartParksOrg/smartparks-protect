"""The frontend's tests of the settings topics read the OpenCollar catalogues from a fixture
inside the frontend, since its image is built from its own folder alone. This keeps the fixture
the driver's catalogues: run this file as a script to write it again after a catalogue change.

    uv run python tests/shared/test_frontend_catalogue_fixture.py
"""

import json
from pathlib import Path
from typing import Any

from shared.device_drivers.opencollar import OpenCollarDriver

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "services/frontend/src/test/fixtures/opencollar-catalogues.json"
)


def _cut(firmware: str) -> dict[str, Any]:
    document = OpenCollarDriver.catalog(firmware)
    return {
        "firmware": document["firmware"],
        "families": bool(document.get("families")),
        "ports": document["ports"],
        "settings": [
            {
                "name": s["name"],
                "type": s["type"],
                "default": s["default"],
                "since_firmware": s.get("since_firmware"),
            }
            for s in document["settings"]
        ],
    }


def expected() -> dict[str, Any]:
    return {"v7": _cut("7.3"), "v8": _cut("8.2")}


def test_the_frontend_fixture_is_the_drivers_catalogues() -> None:
    assert json.loads(FIXTURE.read_text()) == expected(), (
        "run `uv run python tests/shared/test_frontend_catalogue_fixture.py`"
    )


if __name__ == "__main__":
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(expected(), indent=1) + "\n")
    print(FIXTURE)
