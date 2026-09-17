/** Fails when the English catalogue is out of date: runs the extractor and compares the
 *  result with the committed file (decision D93, used by CI). */
import { execSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";

const file = "src/locales/en/translation.json";
const before = readFileSync(file, "utf8");
execSync("npx i18next", { stdio: "pipe" });
const after = readFileSync(file, "utf8");
if (before !== after) {
  writeFileSync(file, before);
  const a = JSON.parse(before),
    b = JSON.parse(after);
  const added = Object.keys(b).filter((k) => !(k in a));
  const removed = Object.keys(a).filter((k) => !(k in b));
  console.error(
    `English catalogue is stale: ${added.length} new, ${removed.length} removed strings. Run npm run i18n:extract and commit ${file}.`,
  );
  for (const k of added.slice(0, 10)) console.error("  +", JSON.stringify(k));
  for (const k of removed.slice(0, 10)) console.error("  -", JSON.stringify(k));
  process.exit(1);
}
console.log("English catalogue is current");
// the other catalogues: report what they lack or no longer need; English stands in for a
// missing string, so this warns and never fails (Tim, 2026-09-17: Dutch added)
import { readdirSync, existsSync } from "node:fs";
const english = JSON.parse(before);
for (const code of readdirSync("src/locales").filter((c) => c !== "en")) {
  const path = `src/locales/${code}/translation.json`;
  if (!existsSync(path)) continue;
  const catalogue = JSON.parse(readFileSync(path, "utf8"));
  const lacking = Object.keys(english).filter((k) => !(k in catalogue));
  const stale = Object.keys(catalogue).filter((k) => !(k in english));
  if (lacking.length || stale.length) {
    console.warn(
      `${code}: ${lacking.length} strings not translated (English shows), ${stale.length} no longer in the code`,
    );
    for (const k of lacking.slice(0, 10))
      console.warn("  ?", JSON.stringify(k));
  } else console.log(`${code} catalogue is complete`);
}
