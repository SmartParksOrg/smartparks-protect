/** Translation layer (decision D93): every UI string goes through `t()` with the English
 * text as its key, so a missing translation falls back to English. Catalogues live in
 * `src/locales/<language>/translation.json`; `npm run i18n:extract` regenerates the English
 * one from the code. Only English ships; a language is added by dropping in its catalogue and
 * listing it in `LANGUAGES`. */
import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import en from "@/locales/en/translation.json";

export const LANGUAGES: Record<string, string> = { en: "English" };

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { en: { translation: en } },
    fallbackLng: "en",
    supportedLngs: Object.keys(LANGUAGES),
    keySeparator: false,
    nsSeparator: false,
    interpolation: { escapeValue: false },
    detection: { order: ["localStorage", "navigator"], caches: ["localStorage"], lookupLocalStorage: "protect.language" },
    returnEmptyString: false,
  });

export default i18n;
