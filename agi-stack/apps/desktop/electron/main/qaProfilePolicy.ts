import {
  chmodSync,
  existsSync,
  lstatSync,
  mkdirSync,
  realpathSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, isAbsolute, relative, resolve } from 'node:path';

const QA_PROFILE_PREFIX = 'agistack-desktop-qa-';

type QaProfileApp = Readonly<{
  isPackaged: boolean;
  setPath(name: string, value: string): void;
}>;

type ResolveQaProfileDirectoryInput = Readonly<{
  isPackaged: boolean;
  requestedPath: string | undefined;
  temporaryRoot?: string;
}>;

type ConfigureQaProfileInput = Readonly<{
  app: QaProfileApp;
  requestedPath: string | undefined;
  temporaryRoot?: string;
  prepareDirectory?: (path: string, temporaryRoot: string) => void;
}>;

type ResolveSidecarLegacyDataDirectoriesInput = Readonly<{
  qaProfileDirectory: string | null;
  resolveNormalCandidates: () => readonly string[];
}>;

export function resolveQaProfileDirectory({
  isPackaged,
  requestedPath,
  temporaryRoot = tmpdir(),
}: ResolveQaProfileDirectoryInput): string | null {
  if (requestedPath === undefined || requestedPath === '') return null;
  if (isPackaged) {
    throw new Error('QA profile isolation is disabled in packaged builds');
  }
  if (!isAbsolute(requestedPath) || requestedPath.trim() !== requestedPath) {
    throw new Error('QA profile path must be an absolute temporary directory');
  }

  const resolvedRoot = resolve(temporaryRoot);
  const resolvedProfile = resolve(requestedPath);
  const relativeProfile = relative(resolvedRoot, resolvedProfile);
  if (
    relativeProfile === '' ||
    relativeProfile.startsWith('..') ||
    isAbsolute(relativeProfile) ||
    dirname(resolvedProfile) !== resolvedRoot
  ) {
    throw new Error(
      'QA profile path must be a direct child of the temporary directory',
    );
  }
  if (!basename(resolvedProfile).startsWith(QA_PROFILE_PREFIX)) {
    throw new Error(`QA profile directory must start with ${QA_PROFILE_PREFIX}`);
  }
  return resolvedProfile;
}

export function configureQaProfile({
  app,
  requestedPath,
  temporaryRoot = tmpdir(),
  prepareDirectory = prepareQaProfileDirectory,
}: ConfigureQaProfileInput): string | null {
  const profileDirectory = resolveQaProfileDirectory({
    isPackaged: app.isPackaged,
    requestedPath,
    temporaryRoot,
  });
  if (profileDirectory === null) return null;
  prepareDirectory(profileDirectory, temporaryRoot);
  app.setPath('userData', profileDirectory);
  return profileDirectory;
}

export function resolveSidecarLegacyDataDirectories({
  qaProfileDirectory,
  resolveNormalCandidates,
}: ResolveSidecarLegacyDataDirectoriesInput): readonly string[] {
  if (qaProfileDirectory !== null) return Object.freeze([]);
  return Object.freeze([...resolveNormalCandidates()]);
}

function prepareQaProfileDirectory(path: string, temporaryRoot: string): void {
  if (!existsSync(path)) mkdirSync(path, { mode: 0o700 });
  const metadata = lstatSync(path);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new Error('QA profile path must resolve to a private directory');
  }
  const canonicalRoot = realpathSync(temporaryRoot);
  const canonicalProfile = realpathSync(path);
  const canonicalRelative = relative(canonicalRoot, canonicalProfile);
  if (
    canonicalRelative === '' ||
    canonicalRelative.startsWith('..') ||
    isAbsolute(canonicalRelative) ||
    dirname(canonicalProfile) !== canonicalRoot
  ) {
    throw new Error('QA profile path must not traverse symbolic links');
  }
  if (process.platform !== 'win32') chmodSync(path, 0o700);
}
