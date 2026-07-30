import { isDeepStrictEqual } from "node:util";

function requireLocaleTag(value, label) {
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`${label} must be a non-empty BCP47 tag`);
  }
  try {
    return new Intl.Locale(value);
  } catch {
    throw new Error(`${label} is not a valid BCP47 tag`);
  }
}

export function compareObservedLocale(observed, declared) {
  const observedLocale = requireLocaleTag(observed, "observed locale");
  const declaredLocale = requireLocaleTag(declared, "declared locale");
  const declaredIsBaseLanguage =
    declaredLocale.baseName === declaredLocale.language;
  const matches = declaredIsBaseLanguage
    ? observedLocale.language === declaredLocale.language
    : observedLocale.toString() === declaredLocale.toString();
  if (!matches) {
    throw new Error(
      `observed locale ${observedLocale.toString()} does not satisfy declared locale ${declaredLocale.toString()}`,
    );
  }
  return Object.freeze({
    raw_locale: observed,
    comparison_locale: declaredLocale.toString(),
  });
}

function requireRenderingSample(value, label) {
  if (
    typeof value !== 'object' ||
    value === null ||
    Array.isArray(value) ||
    typeof value.date_sample !== 'string' ||
    value.date_sample.length === 0 ||
    typeof value.number_sample !== 'string' ||
    value.number_sample.length === 0
  ) {
    throw new Error(`${label} must contain date_sample and number_sample`);
  }
  return Object.freeze({
    date_sample: value.date_sample,
    number_sample: value.number_sample,
  });
}

export function requireLocaleRenderingMatch(webValue, desktopValue) {
  const web = requireRenderingSample(webValue, "web locale rendering");
  const desktop = requireRenderingSample(
    desktopValue,
    "desktop locale rendering",
  );
  if (!isDeepStrictEqual(web, desktop)) {
    throw new Error("locale-sensitive rendering differs across paired runtimes");
  }
  return web;
}
