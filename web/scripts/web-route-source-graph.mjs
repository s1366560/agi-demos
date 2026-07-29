import { readFileSync } from 'node:fs';
import { extname, resolve } from 'node:path';

import ts from 'typescript';

import {
  collectObjectRoutedComponentSymbols,
  hasObjectRouteRegistrations,
} from './web-route-object-extractors.mjs';
import { resolveWebSourceEntry, ROUTER_RELATIVE_PATH } from './web-route-source-resolver.mjs';

const CODE_EXTENSIONS = new Set(['', '.js', '.jsx', '.ts', '.tsx']);

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
    throw new Error(`Cannot parse reachable Web source ${sourceEntry}:\n${messages.join('\n')}`);
  }
  return sourceFile;
}

function staticModuleSpecifier(expression) {
  return ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)
    ? expression.text
    : null;
}

function isLocalSourceSpecifier(moduleSpecifier) {
  if (
    !moduleSpecifier.startsWith('.') &&
    moduleSpecifier !== '@' &&
    !moduleSpecifier.startsWith('@/')
  ) {
    return false;
  }
  return CODE_EXTENSIONS.has(extname(moduleSpecifier));
}

function collectReachableModuleSpecifiers(sourceFile) {
  const componentBindings = new Set();
  const importedModulesByBinding = new Map();
  const reexportedModules = new Set();
  const moduleSpecifiers = new Set();

  function moduleSpecifierValue(expression) {
    const moduleSpecifier = staticModuleSpecifier(expression);
    return moduleSpecifier && isLocalSourceSpecifier(moduleSpecifier) ? moduleSpecifier : null;
  }

  function visit(node) {
    const tagName = jsxTagName(node);
    if (tagName) {
      componentBindings.add(tagName.split('.')[0]);
    }
    if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      node.arguments.length === 1
    ) {
      let current = node.parent;
      while (current && !ts.isVariableDeclaration(current)) {
        current = current.parent;
      }
      if (current && ts.isIdentifier(current.name)) {
        let initializer = current.initializer;
        while (initializer && ts.isParenthesizedExpression(initializer)) {
          initializer = initializer.expression;
        }
        if (
          initializer &&
          ts.isCallExpression(initializer) &&
          ts.isIdentifier(initializer.expression) &&
          initializer.expression.text === 'lazy'
        ) {
          const moduleSpecifier = moduleSpecifierValue(node.arguments[0]);
          if (moduleSpecifier) {
            importedModulesByBinding.set(current.name.text, moduleSpecifier);
          }
        }
      }
    }
    ts.forEachChild(node, visit);
  }

  for (const statement of sourceFile.statements) {
    if (ts.isExportDeclaration(statement) && statement.moduleSpecifier) {
      const moduleSpecifier = moduleSpecifierValue(statement.moduleSpecifier);
      if (moduleSpecifier) {
        reexportedModules.add(moduleSpecifier);
      }
      continue;
    }
    if (
      !ts.isImportDeclaration(statement) ||
      !statement.moduleSpecifier ||
      !statement.importClause
    ) {
      continue;
    }
    const moduleSpecifier = moduleSpecifierValue(statement.moduleSpecifier);
    if (!moduleSpecifier) {
      continue;
    }
    if (statement.importClause.name) {
      importedModulesByBinding.set(statement.importClause.name.text, moduleSpecifier);
    }
    const namedBindings = statement.importClause.namedBindings;
    if (namedBindings && ts.isNamespaceImport(namedBindings)) {
      importedModulesByBinding.set(namedBindings.name.text, moduleSpecifier);
    } else if (namedBindings && ts.isNamedImports(namedBindings)) {
      for (const element of namedBindings.elements) {
        importedModulesByBinding.set(element.name.text, moduleSpecifier);
      }
    }
  }
  visit(sourceFile);
  for (const binding of collectObjectRoutedComponentSymbols(sourceFile)) {
    componentBindings.add(binding.split('.')[0]);
  }
  for (const binding of componentBindings) {
    const moduleSpecifier = importedModulesByBinding.get(binding);
    if (moduleSpecifier) {
      moduleSpecifiers.add(moduleSpecifier);
    }
  }
  for (const moduleSpecifier of reexportedModules) {
    moduleSpecifiers.add(moduleSpecifier);
  }
  return [...moduleSpecifiers].sort();
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

function reactRouterRouteBindings(sourceFile) {
  const bindings = new Set();
  for (const statement of sourceFile.statements) {
    if (
      !ts.isImportDeclaration(statement) ||
      !ts.isStringLiteral(statement.moduleSpecifier) ||
      statement.moduleSpecifier.text !== 'react-router-dom' ||
      !statement.importClause
    ) {
      continue;
    }

    const namedBindings = statement.importClause.namedBindings;
    if (namedBindings && ts.isNamespaceImport(namedBindings)) {
      bindings.add(`${namedBindings.name.text}.Route`);
      continue;
    }
    if (!namedBindings || !ts.isNamedImports(namedBindings)) {
      continue;
    }
    for (const element of namedBindings.elements) {
      if ((element.propertyName?.text ?? element.name.text) === 'Route') {
        bindings.add(element.name.text);
      }
    }
  }
  return bindings;
}

function registersProductionRoutes(sourceFile) {
  const routeBindings = reactRouterRouteBindings(sourceFile);
  if (hasObjectRouteRegistrations(sourceFile)) {
    return true;
  }

  let found = false;
  function visit(node) {
    if (found) {
      return;
    }
    const tagName = jsxTagName(node);
    if (tagName && routeBindings.has(tagName)) {
      found = true;
      return;
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  return found;
}

export function discoverReachableWebRouteSources({ routerSource, repositoryRoot }) {
  const modules = new Map();
  const pending = [
    {
      source_entry: ROUTER_RELATIVE_PATH,
      source: routerSource,
    },
  ];

  while (pending.length > 0) {
    const current = pending.shift();
    if (!current || modules.has(current.source_entry)) {
      continue;
    }

    const sourceFile = parseSource(current.source_entry, current.source);
    modules.set(current.source_entry, {
      ...current,
      registers_routes: registersProductionRoutes(sourceFile),
    });
    if (!repositoryRoot) {
      continue;
    }

    for (const moduleSpecifier of collectReachableModuleSpecifiers(sourceFile)) {
      const sourceEntry = resolveWebSourceEntry({
        moduleSpecifier,
        repositoryRoot,
        entryKind: 'reachable Web module',
        importerRelativePath: current.source_entry,
      });
      if (!modules.has(sourceEntry)) {
        pending.push({
          source_entry: sourceEntry,
          source: readFileSync(resolve(repositoryRoot, sourceEntry), 'utf8'),
        });
      }
    }
  }

  const reachableSources = [...modules.values()].sort((left, right) =>
    left.source_entry.localeCompare(right.source_entry)
  );
  const routeRegistrationSources = reachableSources.filter((source) => source.registers_routes);
  if (!routeRegistrationSources.some((source) => source.source_entry === ROUTER_RELATIVE_PATH)) {
    throw new Error(`${ROUTER_RELATIVE_PATH} must register at least one production Route`);
  }
  return {
    reachable_sources: reachableSources,
    route_registration_sources: routeRegistrationSources,
  };
}
