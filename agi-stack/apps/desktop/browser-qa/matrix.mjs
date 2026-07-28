import { readdirSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const browserQaRoot = dirname(fileURLToPath(import.meta.url));
const desktopRoot = resolve(browserQaRoot, '..');
const qaRoot = resolve(desktopRoot, 'qa');
const manifestPath = resolve(browserQaRoot, 'matrix.v1.json');

export const browserQaManifest = Object.freeze(
  JSON.parse(readFileSync(manifestPath, 'utf8')),
);

export function discoverBrowserQaScenarios() {
  return readdirSync(qaRoot, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith('.html'))
    .map((entry) =>
      Object.freeze({
        id: entry.name.slice(0, -'.html'.length),
        file: entry.name,
        path: `/qa/${encodeURIComponent(entry.name)}`,
      }),
    )
    .sort((left, right) => left.id.localeCompare(right.id));
}

export function buildBrowserQaMatrix() {
  const scenarios = discoverBrowserQaScenarios();
  return scenarios.flatMap((scenario) =>
    scenarioVariants(scenario).flatMap((scenarioVariant) =>
      browserQaManifest.locales.flatMap((locale) =>
        browserQaManifest.viewports.flatMap((viewport) =>
          browserQaManifest.themes.map((theme) =>
            Object.freeze({
              id: `${scenario.id}:${scenarioVariant.id}::${locale.id}::${viewport.id}::${theme}`,
              scenario: Object.freeze({
                ...scenario,
                variantId: scenarioVariant.id,
                query: Object.freeze({ ...scenarioVariant.query }),
              }),
              locale,
              viewport,
              theme,
            }),
          ),
        ),
      ),
    ),
  );
}

function scenarioVariants(scenario) {
  const configured = browserQaManifest.scenarioVariants?.[scenario.id];
  if (!Array.isArray(configured) || configured.length === 0) {
    return [Object.freeze({ id: 'default', query: Object.freeze({}) })];
  }
  return configured.map((variant) =>
    Object.freeze({
      id: variant.id,
      query: Object.freeze({ ...variant.query }),
    }),
  );
}
