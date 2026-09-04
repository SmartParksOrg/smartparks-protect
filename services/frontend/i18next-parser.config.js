/** `npm run i18n:extract`: collects every `t("...")` and `<Trans>` into the English catalogue
 * with the text itself as key and value (decision D93). */
export default {
  locales: ["en"],
  output: "src/locales/$LOCALE/$NAMESPACE.json",
  input: ["src/**/*.{ts,tsx}"],
  defaultNamespace: "translation",
  keySeparator: false,
  namespaceSeparator: false,
  keepRemoved: false,
  sort: true,
  defaultValue: (locale, namespace, key) => key,
  lexers: { ts: ["JavascriptLexer"], tsx: ["JsxLexer"] },
};
