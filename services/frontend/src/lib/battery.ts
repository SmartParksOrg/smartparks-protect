import { t } from "@/lib/i18nMark";

type Translate = (key: string, options?: Record<string, unknown>) => string;

/** The battery chemistries the server knows (decision D248), in short words for a value's
 * explanation; the full labels and the thresholds come from the device's battery read. The
 * marker collects them for the extractor; the caller's own `t` translates them where they
 * render. */
const LABELS: Record<string, string> = {
  primary_lithium: t("a primary lithium cell"),
  lithium_ion: t("a lithium-ion cell"),
  lifepo4: t("a LiFePO4 cell"),
  alkaline_2s: t("two alkaline cells"),
};

const SOURCES: Record<string, string> = {
  device: t("set for this device"),
  device_type: t("the default of this device type"),
  driver: t("what this device family usually carries"),
};

export function batteryTypeLabel(key: string, translate: Translate): string {
  const label = LABELS[key];
  return label ? translate(label) : key;
}

/** Where the battery type in force came from, for the device page's card. */
export function batterySourceLabel(
  source: string,
  translate: Translate,
): string {
  const label = SOURCES[source];
  return label ? translate(label) : translate(t("not known"));
}
