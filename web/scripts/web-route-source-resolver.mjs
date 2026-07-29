import { lstatSync, realpathSync, statSync } from 'node:fs';
import { dirname, extname, isAbsolute, relative, resolve, sep } from 'node:path';

export const ROUTER_RELATIVE_PATH = 'web/src/App.tsx';

function toRepositoryPath(path) {
  return path.split(sep).join('/');
}

export function resolveWebSourceEntry({
  moduleSpecifier,
  repositoryRoot,
  entryKind,
  importerRelativePath,
}) {
  if (
    !moduleSpecifier.startsWith('.') &&
    moduleSpecifier !== '@' &&
    !moduleSpecifier.startsWith('@/')
  ) {
    throw new Error(
      `${entryKind} source entry must use a local module specifier: ${moduleSpecifier}`
    );
  }
  const importerDirectory = dirname(importerRelativePath);
  const repositoryModule =
    moduleSpecifier === '@'
      ? 'web/src'
      : moduleSpecifier.startsWith('@/')
        ? `web/src/${moduleSpecifier.slice(2)}`
        : resolve('/', importerDirectory, moduleSpecifier).slice(1);
  if (!repositoryRoot) {
    const unresolved = resolve('/', repositoryModule);
    const extension = extname(unresolved) ? '' : '.tsx';
    return toRepositoryPath(`${relative('/', unresolved)}${extension}`);
  }

  const absoluteRepositoryRoot = resolve(repositoryRoot);
  const unresolved =
    moduleSpecifier === '@' || moduleSpecifier.startsWith('@/')
      ? resolve(absoluteRepositoryRoot, repositoryModule)
      : resolve(absoluteRepositoryRoot, importerDirectory, moduleSpecifier);
  const extensions = ['.tsx', '.ts', '.jsx', '.js'];
  const candidates = extname(unresolved)
    ? [unresolved]
    : [
        ...extensions.map((extension) => `${unresolved}${extension}`),
        ...extensions.map((extension) => resolve(unresolved, `index${extension}`)),
      ];
  const sourceEntry = candidates.find((candidate) => {
    try {
      return statSync(candidate).isFile();
    } catch {
      return false;
    }
  });

  if (!sourceEntry) {
    throw new Error(
      `Cannot resolve ${entryKind} source entry ${moduleSpecifier} from ${importerRelativePath}`
    );
  }

  const sourceMetadata = lstatSync(sourceEntry);
  const realRepositoryRoot = realpathSync(absoluteRepositoryRoot);
  const realSourceEntry = realpathSync(sourceEntry);
  const repositoryPath = relative(realRepositoryRoot, realSourceEntry);
  if (
    sourceMetadata.isSymbolicLink() ||
    repositoryPath.startsWith('..') ||
    isAbsolute(repositoryPath) ||
    realSourceEntry === realRepositoryRoot
  ) {
    throw new Error(`${entryKind} source entry escapes repository: ${moduleSpecifier}`);
  }
  return toRepositoryPath(repositoryPath);
}

export function resolveRouteSourceEntry(moduleSpecifier, repositoryRoot, entryKind) {
  return resolveWebSourceEntry({
    moduleSpecifier,
    repositoryRoot,
    entryKind,
    importerRelativePath: ROUTER_RELATIVE_PATH,
  });
}
