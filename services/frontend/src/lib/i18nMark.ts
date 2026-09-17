/** Marks a string in a plain data module (the navigation, the range presets, the record
 * columns) for the translation extractor, which collects every `t("...")` call, and gives it
 * back untouched: i18next is not initialised when these modules load, so the component that
 * renders the label translates it with its own `t`. */
export const t = (text: string): string => text;
