import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const desktopRoot = fileURLToPath(new URL('..', import.meta.url));
const sourceRoot = join(desktopRoot, 'src');

function productionSources(directory = sourceRoot) {
  const sources = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      if (path === join(sourceRoot, 'qa')) continue;
      sources.push(...productionSources(path));
    } else if (entry.isFile() && /\.(?:ts|tsx)$/u.test(entry.name)) {
      sources.push({
        path: relative(desktopRoot, path),
        source: readFileSync(path, 'utf8'),
      });
    }
  }
  return sources;
}

const sources = productionSources();
const sourceByPath = new Map(sources.map((entry) => [entry.path, entry.source]));

test('production renderer has no DOM file picker or Blob-anchor download fallback', () => {
  const violations = [];
  for (const { path, source } of sources) {
    if (/<input\b(?:(?!\/>)[\s\S])*?\btype=["']file["']/u.test(source)) {
      violations.push(`${path}: DOM file input`);
    }
    if (/document\.createElement\(["']a["']\)|\.download\s*=/u.test(source)) {
      violations.push(`${path}: Blob anchor download`);
    }
  }
  assert.deepEqual(violations, []);
});

test('all production attachment and Skill package ingress passes through the typed native bridge', () => {
  const composerMenu = sourceByPath.get('src/features/chat/ComposerPlusMenu.tsx');
  const composerDrop = sourceByPath.get('src/features/chat/useComposerFileDrop.ts');
  const skillDialog = sourceByPath.get('src/features/settings/SkillPackageDialogs.tsx');
  assert.match(composerMenu, /openFilesWithDesktopDialog\('attachment'\)/u);
  assert.match(skillDialog, /openFilesWithDesktopDialog\('skill_package'\)/u);
  assert.match(composerDrop, /ingestFilesWithDesktopBridge\(files\)/u);
  assert.doesNotMatch(composerDrop, /onUploadFiles\(files\)/u);
});

test('Skill package export uses the native save dialog and has no DOM fallback', () => {
  const skillPackages = sourceByPath.get(
    'src/features/settings/useSkillPackageManagement.ts',
  );
  assert.match(skillPackages, /saveBlobWithDesktopDialog/u);
  assert.match(skillPackages, /await downloadSkillPackage/u);
  assert.doesNotMatch(
    skillPackages,
    /URL\.createObjectURL|document\.createElement|\.download\s*=/u,
  );
});
