import { existsSync, readFileSync } from 'node:fs';
import { extname, resolve } from 'node:path';

import ts from 'typescript';

import { resolveWebSourceEntry } from './web-route-source-resolver.mjs';

const CODE_EXTENSIONS = new Set(['', '.js', '.jsx', '.ts', '.tsx']);
const TRACKED_RESOURCE_EXTENSIONS = new Set([
  ...CODE_EXTENSIONS,
  '.avif',
  '.css',
  '.gif',
  '.jpeg',
  '.jpg',
  '.json',
  '.mp3',
  '.mp4',
  '.ogg',
  '.otf',
  '.pdf',
  '.png',
  '.svg',
  '.ttf',
  '.wav',
  '.webm',
  '.webp',
  '.woff',
  '.woff2',
]);

export const WEB_DOCUMENT_ENTRY = 'web/index.html';
export const WEB_SCRIPT_ENTRY = 'web/src/main.tsx';

const BUILD_INPUT_EDGES = Object.freeze([
  {
    from_source_entry: WEB_DOCUMENT_ENTRY,
    relationship: 'package_manifest',
    to_source_entry: 'web/package.json',
  },
  {
    from_source_entry: 'web/package.json',
    relationship: 'dependency_lockfile',
    to_source_entry: 'web/pnpm-lock.yaml',
  },
  {
    from_source_entry: 'web/package.json',
    relationship: 'build_config',
    to_source_entry: 'web/vite.config.ts',
  },
]);
const EXCLUDED_OWNERSHIP_RELATIONSHIPS = new Set([
  'build_config',
  'dependency_lockfile',
  'package_manifest',
]);

function compareText(left, right) {
  if (left < right) {
    return -1;
  }
  if (left > right) {
    return 1;
  }
  return 0;
}

function scriptKindFor(sourceEntry) {
  const extension = extname(sourceEntry);
  if (extension === '.ts') {
    return ts.ScriptKind.TS;
  }
  if (extension === '.js') {
    return ts.ScriptKind.JS;
  }
  if (extension === '.jsx') {
    return ts.ScriptKind.JSX;
  }
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
    const messages = sourceFile.parseDiagnostics.map((diagnostic) =>
      ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n')
    );
    throw new Error(
      `Cannot parse routed production dependency ${sourceEntry}:\n${messages.join('\n')}`
    );
  }
  return sourceFile;
}

function staticModuleSpecifier(expression) {
  return ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)
    ? expression.text
    : null;
}

function withoutQueryOrFragment(moduleSpecifier) {
  return moduleSpecifier.split(/[?#]/u, 1)[0];
}

function isLocalProductionSpecifier(moduleSpecifier) {
  if (
    !moduleSpecifier.startsWith('.') &&
    moduleSpecifier !== '@' &&
    !moduleSpecifier.startsWith('@/')
  ) {
    return false;
  }
  return TRACKED_RESOURCE_EXTENSIONS.has(extname(withoutQueryOrFragment(moduleSpecifier)));
}

function relationshipForResource(moduleSpecifier, codeRelationship) {
  const extension = extname(withoutQueryOrFragment(moduleSpecifier));
  if (extension === '.css') {
    return 'stylesheet_import';
  }
  if (extension === '.json') {
    return 'data_import';
  }
  if (!CODE_EXTENSIONS.has(extension)) {
    return 'asset_import';
  }
  return codeRelationship;
}

function runtimeImportDeclaration(statement) {
  const clause = statement.importClause;
  if (!clause) {
    return true;
  }
  if (clause.isTypeOnly || clause.name) {
    return !clause.isTypeOnly;
  }
  const bindings = clause.namedBindings;
  if (bindings && ts.isNamespaceImport(bindings)) {
    return true;
  }
  return Boolean(
    bindings &&
    ts.isNamedImports(bindings) &&
    bindings.elements.some((element) => !element.isTypeOnly)
  );
}

function runtimeExportDeclaration(statement) {
  if (statement.isTypeOnly) {
    return false;
  }
  const clause = statement.exportClause;
  if (!clause || ts.isNamespaceExport(clause)) {
    return true;
  }
  return clause.elements.some((element) => !element.isTypeOnly);
}

function collectRuntimeDependencies(sourceFile) {
  const dependencies = new Map();

  function add(moduleSpecifier, relationship) {
    if (!moduleSpecifier || !isLocalProductionSpecifier(moduleSpecifier)) {
      return;
    }
    const normalizedSpecifier = withoutQueryOrFragment(moduleSpecifier);
    const resourceRelationship = relationshipForResource(normalizedSpecifier, relationship);
    dependencies.set(`${resourceRelationship}\0${normalizedSpecifier}`, {
      module_specifier: normalizedSpecifier,
      relationship: resourceRelationship,
    });
  }

  for (const statement of sourceFile.statements) {
    if (
      ts.isImportDeclaration(statement) &&
      statement.moduleSpecifier &&
      runtimeImportDeclaration(statement)
    ) {
      add(staticModuleSpecifier(statement.moduleSpecifier), 'static_import');
      continue;
    }
    if (
      ts.isExportDeclaration(statement) &&
      statement.moduleSpecifier &&
      runtimeExportDeclaration(statement)
    ) {
      add(staticModuleSpecifier(statement.moduleSpecifier), 're_export');
    }
  }

  function visit(node) {
    if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      node.arguments.length === 1
    ) {
      add(staticModuleSpecifier(node.arguments[0]), 'dynamic_import');
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);

  return [...dependencies.values()].sort((left, right) => {
    const moduleOrder = compareText(left.module_specifier, right.module_specifier);
    return moduleOrder !== 0 ? moduleOrder : compareText(left.relationship, right.relationship);
  });
}

function collectHtmlDependencies(source) {
  const dependencies = new Map();
  const tagPattern = /<(script|link)\b([^>]*)>/giu;
  const attributePattern = /([:\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/gu;

  for (const match of source.matchAll(tagPattern)) {
    const tagName = match[1].toLowerCase();
    const attributes = new Map();
    for (const attribute of match[2].matchAll(attributePattern)) {
      attributes.set(attribute[1].toLowerCase(), attribute[2] ?? attribute[3] ?? '');
    }
    if (tagName === 'script') {
      const sourceReference = attributes.get('src');
      if (attributes.get('type') === 'module' && sourceReference) {
        dependencies.set(`html_module_script\0${sourceReference}`, {
          module_specifier: sourceReference,
          optional: false,
          relationship: 'html_module_script',
        });
      }
      continue;
    }
    const href = attributes.get('href');
    if (!href) {
      continue;
    }
    const relationships = new Set((attributes.get('rel') ?? '').toLowerCase().split(/\s+/u));
    if (relationships.has('stylesheet')) {
      dependencies.set(`html_stylesheet\0${href}`, {
        module_specifier: href,
        optional: false,
        relationship: 'html_stylesheet',
      });
    } else if (relationships.has('icon')) {
      dependencies.set(`html_asset\0${href}`, {
        module_specifier: href,
        optional: true,
        relationship: 'html_asset',
      });
    }
  }
  return [...dependencies.values()];
}

function collectStylesheetDependencies(source) {
  const dependencies = new Map();
  const importPattern = /@import\s+(?:url\(\s*)?(?:"([^"]+)"|'([^']+)')\s*\)?/gu;
  const urlPattern = /url\(\s*(?:"([^"]+)"|'([^']+)'|([^)'"\s]+))\s*\)/gu;

  function add(moduleSpecifier, relationship) {
    if (!moduleSpecifier || !isLocalProductionSpecifier(moduleSpecifier)) {
      return;
    }
    const normalizedSpecifier = withoutQueryOrFragment(moduleSpecifier);
    dependencies.set(`${relationship}\0${normalizedSpecifier}`, {
      module_specifier: normalizedSpecifier,
      optional: false,
      relationship,
    });
  }
  for (const match of source.matchAll(importPattern)) {
    add(match[1] ?? match[2], 'css_import');
  }
  for (const match of source.matchAll(urlPattern)) {
    add(match[1] ?? match[2] ?? match[3], 'css_url');
  }
  return [...dependencies.values()];
}

function collectSourceDependencies(sourceEntry, source) {
  const extension = extname(sourceEntry);
  if (extension === '.html') {
    return collectHtmlDependencies(source);
  }
  if (extension === '.css') {
    return collectStylesheetDependencies(source);
  }
  if (CODE_EXTENSIONS.has(extension)) {
    return collectRuntimeDependencies(parseSource(sourceEntry, source));
  }
  return [];
}

function htmlModuleSpecifier(moduleSpecifier) {
  if (/^(?:[a-z]+:|\/\/|#)/iu.test(moduleSpecifier)) {
    return null;
  }
  if (moduleSpecifier.startsWith('/src/')) {
    return `./src/${moduleSpecifier.slice('/src/'.length)}`;
  }
  if (moduleSpecifier.startsWith('/')) {
    return `./public/${moduleSpecifier.slice(1)}`;
  }
  return moduleSpecifier;
}

function resolveDependencySourceEntry({ dependency, repositoryRoot, sourceEntry }) {
  const moduleSpecifier =
    extname(sourceEntry) === '.html'
      ? htmlModuleSpecifier(dependency.module_specifier)
      : dependency.module_specifier;
  if (!moduleSpecifier) {
    return null;
  }
  try {
    return resolveWebSourceEntry({
      moduleSpecifier,
      repositoryRoot,
      entryKind: 'production dependency',
      importerRelativePath: sourceEntry,
    });
  } catch (error) {
    if (dependency.optional) {
      return null;
    }
    throw error;
  }
}

function compareEdges(left, right) {
  const sourceOrder = compareText(left.from_source_entry, right.from_source_entry);
  if (sourceOrder !== 0) {
    return sourceOrder;
  }
  const targetOrder = compareText(left.to_source_entry, right.to_source_entry);
  return targetOrder !== 0 ? targetOrder : compareText(left.relationship, right.relationship);
}

export function discoverRoutedProductionDependencies({ repositoryRoot, routedSourceEntries }) {
  if (!repositoryRoot) {
    return {
      dependency_edges: [],
      dependency_ownership: [],
      dependency_sources: [],
      entry_sources: [],
      production_entry_sources: [],
    };
  }

  const routedRootEntries = [
    ...new Set(routedSourceEntries.map((entry) => entry.source_entry)),
  ].sort(compareText);
  const hasDocumentEntry = existsSync(resolve(repositoryRoot, WEB_DOCUMENT_ENTRY));
  const hasScriptEntry = existsSync(resolve(repositoryRoot, WEB_SCRIPT_ENTRY));
  if (hasDocumentEntry !== hasScriptEntry) {
    throw new Error('Web production document and script entries must exist together');
  }
  const productionEntrySources = hasDocumentEntry ? [WEB_DOCUMENT_ENTRY, WEB_SCRIPT_ENTRY] : [];
  const rootEntries = hasDocumentEntry ? [WEB_DOCUMENT_ENTRY] : routedRootEntries;
  const modules = new Map();
  const dependencyTargets = new Set();
  const edgeByKey = new Map();
  const pending = [...rootEntries];

  function addEdge(edge) {
    edgeByKey.set(`${edge.from_source_entry}\0${edge.to_source_entry}\0${edge.relationship}`, edge);
    dependencyTargets.add(edge.to_source_entry);
    if (!modules.has(edge.to_source_entry)) {
      pending.push(edge.to_source_entry);
    }
  }

  if (hasDocumentEntry) {
    for (const edge of BUILD_INPUT_EDGES) {
      if (!existsSync(resolve(repositoryRoot, edge.to_source_entry))) {
        throw new Error(`Web production build input is missing: ${edge.to_source_entry}`);
      }
      addEdge(edge);
    }
  }

  while (pending.length > 0) {
    const sourceEntry = pending.shift();
    if (!sourceEntry || modules.has(sourceEntry)) {
      continue;
    }
    const source = readFileSync(resolve(repositoryRoot, sourceEntry), 'utf8');
    modules.set(sourceEntry, source);
    for (const dependency of collectSourceDependencies(sourceEntry, source)) {
      const dependencySourceEntry = resolveDependencySourceEntry({
        dependency,
        repositoryRoot,
        sourceEntry,
      });
      if (!dependencySourceEntry) {
        continue;
      }
      const edge = {
        from_source_entry: sourceEntry,
        relationship: dependency.relationship,
        to_source_entry: dependencySourceEntry,
      };
      addEdge(edge);
    }
  }

  const dependencyEdges = [...edgeByKey.values()].sort(compareEdges);
  const dependencySources = [...dependencyTargets].sort(compareText).map((sourceEntry) => ({
    source: modules.get(sourceEntry),
    source_entry: sourceEntry,
  }));

  return {
    dependency_edges: dependencyEdges,
    dependency_ownership: classifyProductionDependencyOwnership({
      dependencyEdges,
      dependencySources,
      productionRootEntries: rootEntries,
      routedRootEntries,
    }),
    dependency_sources: dependencySources,
    entry_sources: rootEntries.map((sourceEntry) => ({
      source: modules.get(sourceEntry),
      source_entry: sourceEntry,
    })),
    production_entry_sources: productionEntrySources,
  };
}

function indexDependencyEdges(dependencyEdges) {
  const adjacency = new Map();
  for (const edge of dependencyEdges) {
    const targets = adjacency.get(edge.from_source_entry) ?? [];
    targets.push(edge.to_source_entry);
    adjacency.set(edge.from_source_entry, targets);
  }
  return adjacency;
}

function reachableSourceEntries(adjacency, rootEntry) {
  const reachable = new Set([rootEntry]);
  const pending = [rootEntry];
  while (pending.length > 0) {
    const sourceEntry = pending.shift();
    for (const targetEntry of adjacency.get(sourceEntry) ?? []) {
      if (!reachable.has(targetEntry)) {
        reachable.add(targetEntry);
        pending.push(targetEntry);
      }
    }
  }
  return reachable;
}

function classifyProductionDependencyOwnership({
  dependencyEdges,
  dependencySources,
  productionRootEntries,
  routedRootEntries,
}) {
  const adjacency = indexDependencyEdges(dependencyEdges);
  const excludedEntries = new Set(
    dependencyEdges
      .filter((edge) => EXCLUDED_OWNERSHIP_RELATIONSHIPS.has(edge.relationship))
      .map((edge) => edge.to_source_entry)
  );
  const routedOwnersByEntry = new Map();
  for (const rootEntry of routedRootEntries) {
    for (const sourceEntry of reachableSourceEntries(adjacency, rootEntry)) {
      const owners = routedOwnersByEntry.get(sourceEntry) ?? new Set();
      owners.add(rootEntry);
      routedOwnersByEntry.set(sourceEntry, owners);
    }
  }
  const productionOwnersByEntry = new Map();
  for (const rootEntry of productionRootEntries) {
    for (const sourceEntry of reachableSourceEntries(adjacency, rootEntry)) {
      const owners = productionOwnersByEntry.get(sourceEntry) ?? new Set();
      owners.add(rootEntry);
      productionOwnersByEntry.set(sourceEntry, owners);
    }
  }

  return dependencySources.map(({ source_entry: sourceEntry }) => {
    if (excludedEntries.has(sourceEntry)) {
      return {
        classification: 'excluded',
        owner_source_entries: [],
        reason_code: 'production_build_input',
        source_entry: sourceEntry,
      };
    }
    const routedOwners = [...(routedOwnersByEntry.get(sourceEntry) ?? [])].sort(compareText);
    if (routedOwners.length === 1) {
      return {
        classification: 'owned',
        owner_source_entries: routedOwners,
        reason_code: 'single_routed_source_reachability',
        source_entry: sourceEntry,
      };
    }
    if (routedOwners.length > 1) {
      return {
        classification: 'shared',
        owner_source_entries: routedOwners,
        reason_code: 'multiple_routed_source_reachability',
        source_entry: sourceEntry,
      };
    }
    const productionOwners = [...(productionOwnersByEntry.get(sourceEntry) ?? [])].sort(
      compareText
    );
    if (productionOwners.length > 0) {
      return {
        classification: 'shared',
        owner_source_entries: productionOwners,
        reason_code: 'production_entry_shared_runtime',
        source_entry: sourceEntry,
      };
    }
    throw new Error(`Unclassified production dependency: ${sourceEntry}`);
  });
}
