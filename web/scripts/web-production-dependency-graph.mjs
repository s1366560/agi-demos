import { readFileSync } from 'node:fs';
import { extname, resolve } from 'node:path';

import ts from 'typescript';

import { resolveWebSourceEntry } from './web-route-source-resolver.mjs';

const CODE_EXTENSIONS = new Set(['', '.js', '.jsx', '.ts', '.tsx']);

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

function isLocalCodeSpecifier(moduleSpecifier) {
  if (
    !moduleSpecifier.startsWith('.') &&
    moduleSpecifier !== '@' &&
    !moduleSpecifier.startsWith('@/')
  ) {
    return false;
  }
  return CODE_EXTENSIONS.has(extname(moduleSpecifier));
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
    if (!moduleSpecifier || !isLocalCodeSpecifier(moduleSpecifier)) {
      return;
    }
    dependencies.set(`${relationship}\0${moduleSpecifier}`, {
      module_specifier: moduleSpecifier,
      relationship,
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
    return moduleOrder !== 0
      ? moduleOrder
      : compareText(left.relationship, right.relationship);
  });
}

function compareEdges(left, right) {
  const sourceOrder = compareText(left.from_source_entry, right.from_source_entry);
  if (sourceOrder !== 0) {
    return sourceOrder;
  }
  const targetOrder = compareText(left.to_source_entry, right.to_source_entry);
  return targetOrder !== 0
    ? targetOrder
    : compareText(left.relationship, right.relationship);
}

export function discoverRoutedProductionDependencies({
  repositoryRoot,
  routedSourceEntries,
}) {
  if (!repositoryRoot) {
    return {
      dependency_edges: [],
      dependency_sources: [],
    };
  }

  const rootEntries = [
    ...new Set(routedSourceEntries.map((entry) => entry.source_entry)),
  ].sort(compareText);
  const modules = new Map();
  const dependencyTargets = new Set();
  const edgeByKey = new Map();
  const pending = [...rootEntries];

  while (pending.length > 0) {
    const sourceEntry = pending.shift();
    if (!sourceEntry || modules.has(sourceEntry)) {
      continue;
    }
    const source = readFileSync(resolve(repositoryRoot, sourceEntry), 'utf8');
    modules.set(sourceEntry, source);
    const sourceFile = parseSource(sourceEntry, source);

    for (const dependency of collectRuntimeDependencies(sourceFile)) {
      const dependencySourceEntry = resolveWebSourceEntry({
        moduleSpecifier: dependency.module_specifier,
        repositoryRoot,
        entryKind: 'routed production dependency',
        importerRelativePath: sourceEntry,
      });
      const edge = {
        from_source_entry: sourceEntry,
        relationship: dependency.relationship,
        to_source_entry: dependencySourceEntry,
      };
      edgeByKey.set(
        `${edge.from_source_entry}\0${edge.to_source_entry}\0${edge.relationship}`,
        edge
      );
      dependencyTargets.add(dependencySourceEntry);
      if (!modules.has(dependencySourceEntry)) {
        pending.push(dependencySourceEntry);
      }
    }
  }

  return {
    dependency_edges: [...edgeByKey.values()].sort(compareEdges),
    dependency_sources: [...dependencyTargets]
      .sort(compareText)
      .map((sourceEntry) => ({
        source: modules.get(sourceEntry),
        source_entry: sourceEntry,
      })),
  };
}
