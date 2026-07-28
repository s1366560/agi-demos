import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { basename, join } from 'node:path';

function directoryPath(testsDirectory) {
  return testsDirectory instanceof URL ? fileURLToPath(testsDirectory) : testsDirectory;
}

export function discoverTestFiles(testsDirectory) {
  const resolvedDirectory = directoryPath(testsDirectory);
  return readdirSync(resolvedDirectory, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith('.test.mjs'))
    .map((entry) => join(resolvedDirectory, entry.name))
    .sort((left, right) => left.localeCompare(right));
}

export function assertTestInventoryComplete({ testsDirectory, testFiles }) {
  const expected = discoverTestFiles(testsDirectory).map((path) => basename(path));
  const actual = testFiles.map((path) => basename(path));
  const actualSet = new Set(actual);
  const missing = expected.filter((filename) => !actualSet.has(filename));
  const duplicates = actual.filter((filename, index) => actual.indexOf(filename) !== index);

  if (missing.length > 0 || duplicates.length > 0) {
    const details = [
      ...(missing.length > 0 ? [`omitted: ${missing.join(', ')}`] : []),
      ...(duplicates.length > 0 ? [`duplicated: ${[...new Set(duplicates)].join(', ')}`] : []),
    ];
    throw new Error(`Desktop test discovery inventory mismatch (${details.join('; ')})`);
  }
}
