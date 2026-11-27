#!/usr/bin/env python3
"""Copy the settings metadata and the guided panels of the Smart Parks ble-settings-app into
the frontend, at the commit the clone stands on (decision D431).

    uv run scripts/sync_settings_panels.py [path to the ble-settings-app clone]

Protect's device settings page shows settings by topic with the app's own names, panels and
rules, so the two read the same. Three files are taken, the ones the app releases under MIT as
well (its `LICENSE-MIT-panels.md`, copied along): `settings-meta.json`,
`panels/panel-definitions.js` and `panels/panel-engine.js`. They are copied byte for byte and
never edited here: a change is made in the app and synced. `pin.json` records the commit and a
checksum per file, and a frontend test fails when a copy differs from its checksum. The app's
renderer and its device icons are GPL-3.0 alone and stay out.

After a sync: run the frontend tests, read the diff of the definitions for a control or a
condition form the React renderer does not know yet (`lib/settingsPanels.ts` lists them), and
check `shared/device_drivers/opencollar/settings_file.py` against the app's export code.
"""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "services" / "frontend" / "src" / "vendor" / "ble-settings-app"
REPOSITORY = "https://github.com/SmartParksOrg/ble-settings-app"
#: Source path in the app, name in the copy.
FILES = {
    "settings-meta.json": "settings-meta.json",
    "panels/panel-definitions.js": "panel-definitions.js",
    "panels/panel-engine.js": "panel-engine.js",
    "LICENSE-MIT-panels.md": "LICENSE-MIT-panels.md",
}


def _git(clone: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(clone), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def main() -> None:
    clone = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "ble-settings-app"
    if not (clone / "LICENSE-MIT-panels.md").exists():
        raise SystemExit(f"{clone}: no ble-settings-app clone with LICENSE-MIT-panels.md")
    dirty = _git(clone, "status", "--porcelain", "--", *FILES)
    if dirty:
        raise SystemExit(f"Uncommitted changes in the app, commit them first:\n{dirty}")
    TARGET.mkdir(parents=True, exist_ok=True)
    checksums = {}
    for source, name in FILES.items():
        shutil.copyfile(clone / source, TARGET / name)
        checksums[name] = hashlib.sha256((TARGET / name).read_bytes()).hexdigest()
    pin = {
        "repository": REPOSITORY,
        "commit": _git(clone, "rev-parse", "HEAD"),
        "committed": _git(clone, "log", "-1", "--format=%cI"),
        "files": checksums,
    }
    (TARGET / "pin.json").write_text(json.dumps(pin, indent=2) + "\n")
    print(f"{TARGET.relative_to(ROOT)}: {len(FILES)} files at {pin['commit'][:7]}")


if __name__ == "__main__":
    main()
