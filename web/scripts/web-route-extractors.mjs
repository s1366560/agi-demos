import { createHash } from 'node:crypto';

import ts from 'typescript';

import {
  collectObjectRoutedComponentSymbols,
  extractObjectProductionRoutes,
} from './web-route-object-extractors.mjs';
import { resolveWebSourceEntry, ROUTER_RELATIVE_PATH } from './web-route-source-resolver.mjs';

const NAVIGATION_RELATIVE_PATH = 'web/src/config/navigation.ts';

function parseSource(source, fileName, scriptKind) {
  const sourceFile = ts.createSourceFile(
    fileName,
    source,
    ts.ScriptTarget.Latest,
    true,
    scriptKind
  );

  if (sourceFile.parseDiagnostics.length > 0) {
    const messages = sourceFile.parseDiagnostics.map((diagnostic) =>
      ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n')
    );
    throw new Error(`Cannot parse ${fileName}:\n${messages.join('\n')}`);
  }

  return sourceFile;
}

function unwrapExpression(expression) {
  let current = expression;

  while (
    ts.isParenthesizedExpression(current) ||
    ts.isAsExpression(current) ||
    ts.isTypeAssertionExpression(current) ||
    ts.isNonNullExpression(current) ||
    ts.isSatisfiesExpression(current)
  ) {
    current = current.expression;
  }

  return current;
}

function findVariableDeclaration(sourceFile, variableName) {
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement)) {
      continue;
    }

    for (const declaration of statement.declarationList.declarations) {
      if (ts.isIdentifier(declaration.name) && declaration.name.text === variableName) {
        return declaration;
      }
    }
  }

  throw new Error(`Missing ${variableName} in ${sourceFile.fileName}`);
}

function objectProperties(objectLiteral) {
  const properties = new Map();

  for (const property of objectLiteral.properties) {
    if (!ts.isPropertyAssignment(property)) {
      throw new Error(
        `Unsupported non-property assignment in ${objectLiteral.getSourceFile().fileName}`
      );
    }

    const name = property.name;
    if (!ts.isIdentifier(name) && !ts.isStringLiteral(name)) {
      throw new Error(`Unsupported computed property in ${objectLiteral.getSourceFile().fileName}`);
    }

    properties.set(name.text, property.initializer);
  }

  return properties;
}

function requiredProperty(properties, propertyName, sourceFile) {
  const value = properties.get(propertyName);
  if (!value) {
    throw new Error(`Missing ${propertyName} in ${sourceFile.fileName}`);
  }
  return value;
}

function stringValue(expression, sourceFile, propertyName) {
  const value = unwrapExpression(expression);
  if (!ts.isStringLiteral(value) && !ts.isNoSubstitutionTemplateLiteral(value)) {
    throw new Error(`${propertyName} must be a static string in ${sourceFile.fileName}`);
  }
  return value.text;
}

function stringArrayValue(expression, sourceFile, propertyName) {
  const value = unwrapExpression(expression);
  if (!ts.isArrayLiteralExpression(value)) {
    throw new Error(`${propertyName} must be a static array in ${sourceFile.fileName}`);
  }

  return value.elements.map((element) => stringValue(element, sourceFile, propertyName));
}

function booleanValue(expression, sourceFile, propertyName) {
  const value = unwrapExpression(expression);
  if (value.kind === ts.SyntaxKind.TrueKeyword) {
    return true;
  }
  if (value.kind === ts.SyntaxKind.FalseKeyword) {
    return false;
  }
  throw new Error(`${propertyName} must be a static boolean in ${sourceFile.fileName}`);
}

function normalizedExpression(expression, sourceFile) {
  const printer = ts.createPrinter({
    newLine: ts.NewLineKind.LineFeed,
    removeComments: true,
  });
  return printer.printNode(ts.EmitHint.Expression, expression, sourceFile);
}

function normalizeRouteKeyPart(value) {
  const normalized = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/gu, '-')
    .replace(/^-+|-+$/gu, '');
  return normalized || 'root';
}

function addCanonicalRouteKeys(targets) {
  const baseKeys = targets.map((target) =>
    [target.route_family, target.contexts.join('-'), target.id].map(normalizeRouteKeyPart).join('-')
  );
  const baseKeyCounts = new Map();
  for (const baseKey of baseKeys) {
    baseKeyCounts.set(baseKey, (baseKeyCounts.get(baseKey) ?? 0) + 1);
  }

  const usedRouteKeys = new Set();
  return targets.map((target, index) => {
    const baseKey = baseKeys[index];
    const structuralKey =
      baseKeyCounts.get(baseKey) === 1
        ? baseKey
        : [baseKey, target.display_role, target.group_id, target.relative_path]
            .map(normalizeRouteKeyPart)
            .join('-');
    let routeKey = structuralKey;
    let duplicateIndex = 2;
    while (usedRouteKeys.has(routeKey)) {
      routeKey = `${structuralKey}-${duplicateIndex}`;
      duplicateIndex += 1;
    }
    usedRouteKeys.add(routeKey);
    return {
      ...target,
      route_key: routeKey,
    };
  });
}

function assertUniqueCanonicalRouteKeys(targets) {
  const routeKeys = targets.map((target) => target.route_key);
  if (new Set(routeKeys).size !== routeKeys.length) {
    throw new Error('Canonical navigation route_key values must be globally unique');
  }
}

export function extractCanonicalNavigationTargets(navigationSource) {
  const sourceFile = parseSource(navigationSource, NAVIGATION_RELATIVE_PATH, ts.ScriptKind.TS);
  const declaration = findVariableDeclaration(sourceFile, 'CANONICAL_NAVIGATION_DESTINATIONS');
  if (!declaration.initializer) {
    throw new Error(
      `CANONICAL_NAVIGATION_DESTINATIONS has no initializer in ${sourceFile.fileName}`
    );
  }

  const initializer = unwrapExpression(declaration.initializer);
  if (!ts.isArrayLiteralExpression(initializer)) {
    throw new Error(`CANONICAL_NAVIGATION_DESTINATIONS must be an array in ${sourceFile.fileName}`);
  }

  const targets = initializer.elements.map((element) => {
    const value = unwrapExpression(element);
    if (!ts.isObjectLiteralExpression(value)) {
      throw new Error(`Canonical navigation target must be an object in ${sourceFile.fileName}`);
    }

    const properties = objectProperties(value);
    const target = {
      id: stringValue(requiredProperty(properties, 'id', sourceFile), sourceFile, 'id'),
      label: stringValue(requiredProperty(properties, 'label', sourceFile), sourceFile, 'label'),
      route_family: stringValue(
        requiredProperty(properties, 'routeFamily', sourceFile),
        sourceFile,
        'routeFamily'
      ),
      contexts: stringArrayValue(
        requiredProperty(properties, 'contexts', sourceFile),
        sourceFile,
        'contexts'
      ),
      display_role: stringValue(
        requiredProperty(properties, 'displayRole', sourceFile),
        sourceFile,
        'displayRole'
      ),
      group_id: stringValue(
        requiredProperty(properties, 'groupId', sourceFile),
        sourceFile,
        'groupId'
      ),
      relative_path: stringValue(
        requiredProperty(properties, 'relativePath', sourceFile),
        sourceFile,
        'relativePath'
      ),
      build_path: normalizedExpression(
        requiredProperty(properties, 'buildPath', sourceFile),
        sourceFile
      ),
    };
    const exact = properties.get('exact');
    if (exact) {
      target.exact = booleanValue(exact, sourceFile, 'exact');
    }
    return target;
  });
  const targetsWithRouteKeys = addCanonicalRouteKeys(targets);
  assertUniqueCanonicalRouteKeys(targetsWithRouteKeys);
  return targetsWithRouteKeys;
}

function findFirstDescendant(node, predicate) {
  if (predicate(node)) {
    return node;
  }

  let match;
  ts.forEachChild(node, (child) => {
    if (!match) {
      match = findFirstDescendant(child, predicate);
    }
  });
  return match;
}

function lazyImportCall(initializer) {
  return findFirstDescendant(
    initializer,
    (node) => ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword
  );
}

function lazySelectedExport(initializer) {
  const thenCall = findFirstDescendant(
    initializer,
    (node) =>
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === 'then'
  );
  if (!thenCall) {
    return 'default';
  }

  const defaultProperty = findFirstDescendant(
    thenCall,
    (node) =>
      ts.isPropertyAssignment(node) &&
      ((ts.isIdentifier(node.name) && node.name.text === 'default') ||
        (ts.isStringLiteral(node.name) && node.name.text === 'default'))
  );
  if (!defaultProperty) {
    throw new Error('lazy(...).then(...) must assign a default export');
  }

  const selected = unwrapExpression(defaultProperty.initializer);
  if (ts.isPropertyAccessExpression(selected)) {
    return selected.name.text;
  }
  if (ts.isElementAccessExpression(selected) && selected.argumentExpression) {
    return stringValue(
      selected.argumentExpression,
      selected.getSourceFile(),
      'lazy selected export'
    );
  }

  throw new Error('lazy(...).then(...) default export must select a static module member');
}

function compareText(left, right) {
  if (left < right) {
    return -1;
  }
  if (left > right) {
    return 1;
  }
  return 0;
}

export function extractLazyPageEntries(
  routerSource,
  { repositoryRoot, sourceEntry = ROUTER_RELATIVE_PATH } = {}
) {
  const sourceFile = parseSource(routerSource, sourceEntry, ts.ScriptKind.TSX);
  const entries = [];

  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement)) {
      continue;
    }

    for (const declaration of statement.declarationList.declarations) {
      if (
        !ts.isIdentifier(declaration.name) ||
        !declaration.initializer ||
        !ts.isCallExpression(unwrapExpression(declaration.initializer))
      ) {
        continue;
      }

      const initializer = unwrapExpression(declaration.initializer);
      if (!ts.isIdentifier(initializer.expression) || initializer.expression.text !== 'lazy') {
        continue;
      }

      const importCall = lazyImportCall(initializer);
      if (!importCall || importCall.arguments.length !== 1) {
        throw new Error(`Lazy page ${declaration.name.text} must contain one static import()`);
      }

      entries.push({
        symbol: declaration.name.text,
        module: stringValue(importCall.arguments[0], sourceFile, 'lazy import'),
        export_name: lazySelectedExport(initializer),
      });
    }
  }

  return entries
    .map((entry) => ({
      ...entry,
      source_entry: resolveWebSourceEntry({
        moduleSpecifier: entry.module,
        repositoryRoot,
        entryKind: 'lazy',
        importerRelativePath: sourceEntry,
      }),
    }))
    .sort((left, right) => compareText(left.symbol, right.symbol));
}

export function extractEagerRouteEntries(
  routerSource,
  { repositoryRoot, sourceEntry = ROUTER_RELATIVE_PATH } = {}
) {
  const sourceFile = parseSource(routerSource, sourceEntry, ts.ScriptKind.TSX);
  const entries = [];

  for (const statement of sourceFile.statements) {
    if (
      !ts.isImportDeclaration(statement) ||
      !ts.isStringLiteral(statement.moduleSpecifier) ||
      (!statement.moduleSpecifier.text.startsWith('.') &&
        statement.moduleSpecifier.text !== '@' &&
        !statement.moduleSpecifier.text.startsWith('@/')) ||
      !statement.importClause ||
      statement.importClause.isTypeOnly
    ) {
      continue;
    }

    const moduleSpecifier = statement.moduleSpecifier.text;
    if (statement.importClause.name) {
      entries.push({
        symbol: statement.importClause.name.text,
        module: moduleSpecifier,
        export_name: 'default',
      });
    }

    const namedBindings = statement.importClause.namedBindings;
    if (namedBindings && ts.isNamespaceImport(namedBindings)) {
      entries.push({
        symbol: namedBindings.name.text,
        module: moduleSpecifier,
        export_name: '*',
      });
      continue;
    }

    if (namedBindings && ts.isNamedImports(namedBindings)) {
      for (const element of namedBindings.elements) {
        if (element.isTypeOnly) {
          continue;
        }
        entries.push({
          symbol: element.name.text,
          module: moduleSpecifier,
          export_name: element.propertyName?.text ?? element.name.text,
        });
      }
    }
  }

  const routedComponents = collectRoutedComponentSymbols(
    sourceFile,
    reactRouterRouteBindings(sourceFile)
  );
  for (const component of collectObjectRoutedComponentSymbols(sourceFile)) {
    routedComponents.add(component);
  }
  return entries
    .filter(
      (entry) =>
        routedComponents.has(entry.symbol) ||
        (entry.export_name === '*' &&
          [...routedComponents].some((component) => component.startsWith(`${entry.symbol}.`)))
    )
    .map((entry) => ({
      ...entry,
      source_entry: resolveWebSourceEntry({
        moduleSpecifier: entry.module,
        repositoryRoot,
        entryKind: 'eager',
        importerRelativePath: sourceEntry,
      }),
    }))
    .sort((left, right) => compareText(left.symbol, right.symbol));
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

function jsxAttributes(node) {
  if (ts.isJsxElement(node)) {
    return node.openingElement.attributes.properties;
  }
  if (ts.isJsxSelfClosingElement(node)) {
    return node.attributes.properties;
  }
  throw new Error('Expected JSX element');
}

function jsxAttribute(node, name) {
  return jsxAttributes(node).find(
    (attribute) => ts.isJsxAttribute(attribute) && attribute.name.getText() === name
  );
}

function jsxStaticStringAttribute(attribute, sourceFile, name) {
  if (!attribute?.initializer) {
    throw new Error(`Route ${name} must have a static value in ${sourceFile.fileName}`);
  }
  if (ts.isStringLiteral(attribute.initializer)) {
    return attribute.initializer.text;
  }
  if (ts.isJsxExpression(attribute.initializer) && attribute.initializer.expression) {
    return stringValue(attribute.initializer.expression, sourceFile, name);
  }
  throw new Error(`Route ${name} must be a static string in ${sourceFile.fileName}`);
}

function jsxBooleanAttribute(attribute, sourceFile, name) {
  if (!attribute) {
    return false;
  }
  if (!attribute.initializer) {
    return true;
  }
  if (ts.isJsxExpression(attribute.initializer) && attribute.initializer.expression) {
    return booleanValue(attribute.initializer.expression, sourceFile, name);
  }
  throw new Error(`Route ${name} must be a static boolean in ${sourceFile.fileName}`);
}

function joinRoutePath(parentPath, routePath) {
  if (routePath.startsWith('/')) {
    return routePath.length > 1 ? routePath.replace(/\/+$/u, '') : routePath;
  }

  const base = parentPath && parentPath !== '/' ? parentPath.replace(/\/+$/u, '') : '';
  const suffix = routePath.replace(/^\/+/u, '');
  const joined = `${base}/${suffix}`.replace(/\/+/gu, '/');
  return joined.length > 1 ? joined.replace(/\/+$/u, '') : joined;
}

function collectElementComponents(expression) {
  const components = [];
  const seen = new Set();

  function visit(node) {
    const tagName = jsxTagName(node);
    if (tagName && !seen.has(tagName)) {
      seen.add(tagName);
      components.push(tagName);
    }
    ts.forEachChild(node, visit);
  }

  visit(expression);
  return components;
}

function routeElementComponents(routeNode, sourceFile) {
  const element = jsxAttribute(routeNode, 'element');
  if (!element?.initializer || !ts.isJsxExpression(element.initializer)) {
    return [];
  }
  if (!element.initializer.expression) {
    throw new Error(`Route element cannot be empty in ${sourceFile.fileName}`);
  }
  return collectElementComponents(element.initializer.expression);
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

function collectRoutedComponentSymbols(sourceFile, routeBindings) {
  const components = new Set();

  function visit(node) {
    if (
      (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) &&
      routeBindings.has(jsxTagName(node))
    ) {
      for (const component of routeElementComponents(node, sourceFile)) {
        components.add(component);
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return components;
}

export function addProductionRouteKeys(routes) {
  const baseKeys = routes.map((route) =>
    [
      'production-route',
      route.index ? 'index' : 'path',
      normalizeRouteKeyPart(route.path_pattern),
    ].join('-')
  );
  const baseKeyCounts = new Map();
  for (const baseKey of baseKeys) {
    baseKeyCounts.set(baseKey, (baseKeyCounts.get(baseKey) ?? 0) + 1);
  }

  const usedRouteKeys = new Set();
  return routes.map((route, index) => {
    const baseKey = baseKeys[index];
    const routeKey =
      baseKeyCounts.get(baseKey) === 1
        ? baseKey
        : `${baseKey}-${createHash('sha256')
            .update(
              JSON.stringify([
                route.path_pattern,
                route.index,
                route.element_components,
                route.source_entries,
              ])
            )
            .digest('hex')
            .slice(0, 12)}`;
    if (usedRouteKeys.has(routeKey)) {
      routeKey = `${baseKey}-${createHash('sha256')
        .update(
          JSON.stringify([
            route.registration_source,
            route.path_pattern,
            route.index,
            route.element_components,
            route.source_entries,
          ])
        )
        .digest('hex')
        .slice(0, 12)}`;
      if (usedRouteKeys.has(routeKey)) {
        throw new Error(
          `Production route registrations must be structurally unique: ` +
            `${route.registration_source} ${route.path_pattern}`
        );
      }
    }
    usedRouteKeys.add(routeKey);
    return {
      ...route,
      route_key: routeKey,
    };
  });
}

export function extractProductionRoutes(
  routerSource,
  routeSourceEntries,
  { sourceEntry = ROUTER_RELATIVE_PATH, addRouteKeys = true, parentRoutePath = '' } = {}
) {
  const sourceFile = parseSource(routerSource, sourceEntry, ts.ScriptKind.TSX);
  const routeBindings = reactRouterRouteBindings(sourceFile);
  const routeEntriesBySymbol = new Map();
  for (const entry of routeSourceEntries) {
    if (routeEntriesBySymbol.has(entry.symbol)) {
      throw new Error(`Duplicate route source symbol ${entry.symbol} in ${sourceFile.fileName}`);
    }
    routeEntriesBySymbol.set(entry.symbol, entry);
  }
  const routes = [];

  function routeEntryForComponent(component) {
    const directEntry = routeEntriesBySymbol.get(component);
    if (directEntry) {
      return directEntry;
    }

    const namespaceSymbol = component.split('.')[0];
    const namespaceEntry = routeEntriesBySymbol.get(namespaceSymbol);
    return namespaceEntry?.export_name === '*' ? namespaceEntry : undefined;
  }

  function visit(node, parentRoutePath) {
    if (
      (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) &&
      routeBindings.has(jsxTagName(node))
    ) {
      const pathAttribute = jsxAttribute(node, 'path');
      const isIndex = jsxBooleanAttribute(jsxAttribute(node, 'index'), sourceFile, 'index');
      if (!pathAttribute && !isIndex) {
        throw new Error(`Route must declare path or index in ${sourceFile.fileName}`);
      }

      const routePath = pathAttribute
        ? jsxStaticStringAttribute(pathAttribute, sourceFile, 'path')
        : '';
      const pathPattern = isIndex
        ? parentRoutePath || '/'
        : joinRoutePath(parentRoutePath, routePath);
      const elementComponents = routeElementComponents(node, sourceFile);
      const sourceEntries = elementComponents
        .map((component) => routeEntryForComponent(component))
        .filter(Boolean);

      routes.push({
        path_pattern: pathPattern,
        index: isIndex,
        element_components: elementComponents,
        registration_source: sourceEntry,
        source_entries: sourceEntries,
      });

      if (ts.isJsxElement(node)) {
        for (const child of node.children) {
          visit(child, pathPattern);
        }
      }
      return;
    }

    ts.forEachChild(node, (child) => visit(child, parentRoutePath));
  }

  visit(sourceFile, parentRoutePath);
  routes.push(
    ...extractObjectProductionRoutes(sourceFile, routeSourceEntries, {
      sourceEntry,
      parentRoutePath,
    })
  );
  return addRouteKeys ? addProductionRouteKeys(routes) : routes;
}
