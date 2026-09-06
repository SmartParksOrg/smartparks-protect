#!/usr/bin/env python3
"""Run every recorded OpenCollar frame through the firmware's reference decoders and write the
golden file the driver test checks against (decision D100).

    uv run scripts/opencollar_golden.py

Frames come from `tests/fixtures/payloads/opencollar/uplinks.jsonl` (wiki examples) and the
recorded uplinks of live collars under `tests/fixtures/payloads/<provider>/`. Needs node.
"""

import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "payloads"
DECODERS = FIXTURES / "opencollar" / "decoders"
VERSIONS = ("7.2.0", "6.15.1", "6.11.2")

SHIM = """
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const frames = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const holder = {};
new Function("holder", src + "\\n; holder.Decoder = Decoder;")(holder);
const out = frames.map((f) => {
  try { return holder.Decoder(Buffer.from(f.data_hex, "hex"), f.port); } catch (e) { return { error: String(e) }; }
});
process.stdout.write(JSON.stringify(out));
"""


def frames() -> list[dict]:
    """The wiki examples plus every recorded live uplink of a collar under the provider
    fixture directories: files named `*live_uplink*.json` with a ThingPark document, and
    `*opencollar*.json` with a base64 `data` and `fPort`."""
    rows: list[dict] = []
    for line in (FIXTURES / "opencollar" / "uplinks.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            rows.append(
                {"port": row["f_port"], "data_hex": row["data_hex"], "source": "wiki uplinks.jsonl"}
            )
    for path in sorted(FIXTURES.glob("*/*live_uplink*.json")):
        document = json.loads(path.read_text())
        data = document.get("DevEUI_uplink") if isinstance(document, dict) else None
        if isinstance(data, dict) and data.get("payload_hex") and data.get("FPort") is not None:
            rows.append(
                {
                    "port": int(data["FPort"]),
                    "data_hex": data["payload_hex"],
                    "source": f"{path.parent.name}/{path.name}",
                }
            )
    for path in sorted(FIXTURES.glob("*/*opencollar*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("data"), str) and data.get("fPort"):
            try:
                raw = base64.b64decode(data["data"], validate=True)
            except ValueError:
                continue
            rows.append(
                {
                    "port": int(data["fPort"]),
                    "data_hex": raw.hex(),
                    "source": f"{path.parent.name}/{path.name}",
                }
            )
    return rows


def main() -> int:
    rows = frames()
    frames_path = Path("/tmp") / "opencollar_frames.json"
    frames_path.write_text(json.dumps(rows))
    shim = Path("/tmp") / "opencollar_shim.cjs"  # .cjs: node must read it as CommonJS
    shim.write_text(SHIM)
    golden = []
    outputs: dict[str, list] = {}
    for version in VERSIONS:
        result = subprocess.run(
            ["node", str(shim), str(DECODERS / f"ttn_decoder-v{version}.js"), str(frames_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        outputs[version] = json.loads(result.stdout)
    for index, row in enumerate(rows):
        golden.append({**row, "decoders": {v: outputs[v][index] for v in VERSIONS}})
    target = FIXTURES / "opencollar" / "golden.json"
    target.write_text(json.dumps(golden, indent=1, sort_keys=True) + "\n")
    print(f"{len(golden)} frames through {len(VERSIONS)} decoders into {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
