/** Translation layer (decision D93): every UI string goes through `t()` with the English
 * text as its key, so a missing translation falls back to English. Catalogues live in
 * `src/locales/<language>/translation.json`; `npm run i18n:extract` regenerates the English
 * one from the code. English and Dutch ship (Tim, 2026-09-17); a language is added by dropping
 * in its catalogue, importing it here and listing it in `LANGUAGES`. `npm run i18n:check`
 * reports the strings a catalogue lacks; they fall back to English until translated. */
import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import en from "@/locales/en/translation.json";
import nl from "@/locales/nl/translation.json";

export const LANGUAGES: Record<string, string> = {
  en: "English",
  nl: "Nederlands",
};

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { en: { translation: en }, nl: { translation: nl } },
    fallbackLng: "en",
    supportedLngs: Object.keys(LANGUAGES),
    keySeparator: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
    detection: {
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
      lookupLocalStorage: "protect.language",
    },
    returnEmptyString: false,
  });

export default i18n;
