import { t } from "@/lib/i18nMark";

type Translate = (key: string, options?: Record<string, unknown>) => string;

/** What a position actually is, in a few words, for every kind that is not a device's own fix.
 *
 * A fix needs no label: it is what a reader assumes. Everything else does, because it looks
 * exactly like a fix on a map and is not one, and a reader who takes an estimate for a fix
 * draws the wrong conclusion from it (Tim, 2026-09-18). A device's own fix returns null and
 * the row stays plain.
 */
const LABELS: Record<string, string> = {
  network: t("network estimate"),
  static: t("fixed place"),
  proximity: t("heard by a reader"),
};

/** The short form for a phone, where the row has no room for the long one. */
const SHORT: Record<string, string> = {
  network: t("estimate"),
  static: t("fixed"),
  proximity: t("heard"),
};

const EXPLANATIONS: Record<string, string> = {
  network: t(
    "The network worked out roughly where the device was; it is not a fix the device made itself.",
  ),
  static: t(
    "A place set by a person for hardware that does not move and does not report where it is. Nothing the device sends moves it.",
  ),
  proximity: t(
    "Another device heard this one over Bluetooth and reported it, so this is the place of that device, not of this one.",
  ),
};

export function positionKindLabel(
  kind: string | null | undefined,
  translate: Translate,
  short = false,
): string | null {
  if (!kind) return null;
  const label = (short ? SHORT : LABELS)[kind];
  return label ? translate(label) : null;
}

export function positionKindExplanation(
  kind: string | null | undefined,
  translate: Translate,
): string | undefined {
  const text = kind ? EXPLANATIONS[kind] : undefined;
  return text ? translate(text) : undefined;
}

/** Whether a position is the device's own fix. Everything else is somebody else's word for it. */
export function isDeviceFix(kind: string | null | undefined): boolean {
  return !kind || !(kind in LABELS);
}
