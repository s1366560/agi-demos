import { readFileSync } from 'node:fs';
import { extname, resolve } from 'node:path';

import ts from 'typescript';

import { extractLazyPageEntries } from './web-route-extractors.mjs';
import { resolveWebSourceEntry } from './web-route-source-resolver.mjs';

const ROUTE_IMPLEMENTATION_PREFIX = 'web/src/routes/v2/';
const NON_CONTENT_ROUTE_MODULES = new Set(['web/src/routes/v2/WebRoutePageLoaderV2.tsx']);

function scriptKindFor(sourceEntry) {
  const extension = extname(sourceEntry);
  if (extension === '.ts') return ts.ScriptKind.TS;
  if (extension === '.js') return ts.ScriptKind.JS;
  if (extension === '.jsx') return ts.ScriptKind.JSX;
  return ts.ScriptKind.TSX;
}

function parseSource(sourceEntry, source) {
  const sourceFile = ts.createSourceFile(
    sourceEntry,
    source,
    ts.ScriptTarget.Latest,
    true,
    scriptKindFor(sourceEntry)
  );
  if (sourceFile.parseDiagnostics.length > 0) {
    throw new Error(`Cannot parse routed component source ${sourceEntry}`);
  }
  return sourceFile;
}

function localImports(sourceFile, repositoryRoot, sourceEntry) {
  const imports = new Map();
  for (const statement of sourceFile.statements) {
    if (
      !ts.isImportDeclaration(statement) ||
      !ts.isStringLiteral(statement.moduleSpecifier) ||
      !statement.importClause ||
      statement.importClause.isTypeOnly
    ) {
      continue;
    }
    const moduleSpecifier = statement.moduleSpecifier.text;
    if (
      !moduleSpecifier.startsWith('.') &&
      moduleSpecifier !== '@' &&
      !moduleSpecifier.startsWith('@/')
    ) {
      continue;
    }
    const target = resolveWebSourceEntry({
      moduleSpecifier,
      repositoryRoot,
      entryKind: 'routed component',
      importerRelativePath: sourceEntry,
    });
    if (statement.importClause.name) {
      imports.set(statement.importClause.name.text, {
        export_name: 'default',
        module: moduleSpecifier,
        source_entry: target,
      });
    }
    const named = statement.importClause.namedBindings;
    if (named && ts.isNamedImports(named)) {
      for (const element of named.elements) {
        if (element.isTypeOnly) continue;
        imports.set(element.name.text, {
          export_name: element.propertyName?.text ?? element.name.text,
          module: moduleSpecifier,
          source_entry: target,
        });
      }
    }
  }
  return imports;
}

function jsxTagName(node) {
  if (ts.isJsxElement(node)) {
    return node.openingElement.tagName.getText(node.getSourceFile());
  }
  if (!ts.isJsxOpeningElement(node) && !ts.isJsxSelfClosingElement(node)) {
    return null;
  }
  return node.tagName.getText(node.getSourceFile());
}

function declarationBody(sourceFile, exportName) {
  for (const statement of sourceFile.statements) {
    if (ts.isFunctionDeclaration(statement) && statement.name?.text === exportName) {
      return statement.body;
    }
    if (!ts.isVariableStatement(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (
        ts.isIdentifier(declaration.name) &&
        declaration.name.text === exportName &&
        declaration.initializer &&
        (ts.isArrowFunction(declaration.initializer) ||
          ts.isFunctionExpression(declaration.initializer))
      ) {
        return declaration.initializer.body;
      }
    }
  }
  return null;
}

function renderedComponentSymbols(sourceFile, exportName) {
  const body = declarationBody(sourceFile, exportName);
  if (!body) return [];
  const symbols = new Set();

  function visit(node) {
    if (ts.isJsxAttribute(node) && node.name.getText(sourceFile) === 'fallback') {
      return;
    }
    const tagName = jsxTagName(node);
    if (tagName) symbols.add(tagName.split('.')[0]);
    ts.forEachChild(node, visit);
  }

  visit(body);
  return [...symbols].sort();
}

function compareEntries(left, right) {
  const sourceOrder = left.entry.source_entry.localeCompare(right.entry.source_entry);
  return sourceOrder !== 0 ? sourceOrder : left.entry.symbol.localeCompare(right.entry.symbol);
}

export function createRouteComponentProjection({ repositoryRoot, sourceGraph }) {
  const sourceByEntry = new Map(
    sourceGraph.reachable_sources.map((source) => [source.source_entry, source.source])
  );
  const moduleInfo = new Map();
  const resolutionCache = new Map();
  const usedEntries = new Map();

  function readSource(sourceEntry) {
    return (
      sourceByEntry.get(sourceEntry) ?? readFileSync(resolve(repositoryRoot, sourceEntry), 'utf8')
    );
  }

  function info(sourceEntry) {
    const cached = moduleInfo.get(sourceEntry);
    if (cached) return cached;
    const source = readSource(sourceEntry);
    const sourceFile = parseSource(sourceEntry, source);
    const lazyEntries = extractLazyPageEntries(source, {
      repositoryRoot,
      sourceEntry,
    });
    const value = {
      imports: localImports(sourceFile, repositoryRoot, sourceEntry),
      lazy_by_symbol: new Map(lazyEntries.map((entry) => [entry.symbol, entry])),
      source_file: sourceFile,
    };
    moduleInfo.set(sourceEntry, value);
    return value;
  }

  function resolveComponent(sourceEntry, component, ancestry = new Set()) {
    const cacheKey = `${sourceEntry}\u0000${component}`;
    const cached = resolutionCache.get(cacheKey);
    if (cached) return cached;
    if (ancestry.has(cacheKey)) {
      throw new Error(`Routed component cycle detected at ${sourceEntry}#${component}`);
    }
    const nextAncestry = new Set(ancestry).add(cacheKey);
    const sourceInfo = info(sourceEntry);
    const localLazy = sourceInfo.lazy_by_symbol.get(component);
    if (localLazy) {
      const resolved = [{ entry: localLazy, kind: 'lazy' }];
      resolutionCache.set(cacheKey, resolved);
      return resolved;
    }

    const imported = sourceInfo.imports.get(component);
    if (imported) {
      const targetInfo = info(imported.source_entry);
      const importedLazy = targetInfo.lazy_by_symbol.get(imported.export_name);
      if (importedLazy) {
        const resolved = [{ entry: importedLazy, kind: 'lazy' }];
        resolutionCache.set(cacheKey, resolved);
        return resolved;
      }
      if (!imported.source_entry.startsWith(ROUTE_IMPLEMENTATION_PREFIX)) {
        const resolved = [
          {
            entry: {
              export_name: imported.export_name,
              module: imported.module,
              source_entry: imported.source_entry,
              symbol: component,
            },
            kind: 'eager',
          },
        ];
        resolutionCache.set(cacheKey, resolved);
        return resolved;
      }
      if (NON_CONTENT_ROUTE_MODULES.has(imported.source_entry)) {
        resolutionCache.set(cacheKey, []);
        return [];
      }
      const resolved = renderedComponentSymbols(
        targetInfo.source_file,
        imported.export_name
      ).flatMap((symbol) => resolveComponent(imported.source_entry, symbol, nextAncestry));
      resolutionCache.set(cacheKey, resolved);
      return resolved;
    }

    if (sourceEntry.startsWith(ROUTE_IMPLEMENTATION_PREFIX)) {
      const resolved = renderedComponentSymbols(sourceInfo.source_file, component).flatMap(
        (symbol) => resolveComponent(sourceEntry, symbol, nextAncestry)
      );
      resolutionCache.set(cacheKey, resolved);
      return resolved;
    }
    resolutionCache.set(cacheKey, []);
    return [];
  }

  function resolveForRoute(sourceEntry, component) {
    const resolved = resolveComponent(sourceEntry, component);
    for (const item of resolved) {
      const existing = usedEntries.get(item.entry.symbol);
      if (existing && JSON.stringify(existing.entry) !== JSON.stringify(item.entry)) {
        throw new Error(`Routed component symbol ${item.entry.symbol} resolves ambiguously.`);
      }
      usedEntries.set(item.entry.symbol, item);
    }
    return resolved.map((item) => item.entry);
  }

  function entries() {
    const resolved = [...usedEntries.values()].sort(compareEntries);
    return {
      eager: resolved.filter((item) => item.kind === 'eager').map((item) => item.entry),
      lazy: resolved.filter((item) => item.kind === 'lazy').map((item) => item.entry),
    };
  }

  return { entries, resolveForRoute };
}
