import ts from 'typescript';

const OBJECT_ROUTE_APIS = new Set(['createBrowserRouter', 'useRoutes']);
const ROUTE_ELEMENT_FACTORY = 'createRoutesFromElements';

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

function reactRouterBindings(sourceFile) {
  const named = new Map();
  const namespaces = new Set();
  for (const statement of sourceFile.statements) {
    if (
      !ts.isImportDeclaration(statement) ||
      !ts.isStringLiteral(statement.moduleSpecifier) ||
      statement.moduleSpecifier.text !== 'react-router-dom' ||
      !statement.importClause ||
      statement.importClause.isTypeOnly
    ) {
      continue;
    }
    const bindings = statement.importClause.namedBindings;
    if (bindings && ts.isNamespaceImport(bindings)) {
      namespaces.add(bindings.name.text);
      continue;
    }
    if (!bindings || !ts.isNamedImports(bindings)) {
      continue;
    }
    for (const element of bindings.elements) {
      if (!element.isTypeOnly) {
        named.set(element.name.text, element.propertyName?.text ?? element.name.text);
      }
    }
  }
  return { named, namespaces };
}

function routerApiName(expression, bindings) {
  const candidate = unwrapExpression(expression);
  if (ts.isIdentifier(candidate)) {
    return bindings.named.get(candidate.text) ?? null;
  }
  if (
    ts.isPropertyAccessExpression(candidate) &&
    ts.isIdentifier(candidate.expression) &&
    bindings.namespaces.has(candidate.expression.text)
  ) {
    return candidate.name.text;
  }
  return null;
}

function variableInitializers(sourceFile) {
  const initializers = new Map();
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement)) {
      continue;
    }
    for (const declaration of statement.declarationList.declarations) {
      if (ts.isIdentifier(declaration.name) && declaration.initializer) {
        initializers.set(declaration.name.text, declaration.initializer);
      }
    }
  }
  return initializers;
}

function staticRouteArray(
  expression,
  sourceFile,
  bindings,
  initializers,
  seenIdentifiers = new Set()
) {
  const candidate = unwrapExpression(expression);
  if (ts.isArrayLiteralExpression(candidate)) {
    return candidate;
  }
  if (ts.isIdentifier(candidate)) {
    if (seenIdentifiers.has(candidate.text)) {
      throw new Error(`Route object array contains a cycle in ${sourceFile.fileName}`);
    }
    const initializer = initializers.get(candidate.text);
    if (!initializer) {
      throw new Error(
        `Route object registration ${candidate.text} must resolve to a local static array in ` +
          sourceFile.fileName
      );
    }
    return staticRouteArray(
      initializer,
      sourceFile,
      bindings,
      initializers,
      new Set(seenIdentifiers).add(candidate.text)
    );
  }
  if (
    ts.isCallExpression(candidate) &&
    routerApiName(candidate.expression, bindings) === ROUTE_ELEMENT_FACTORY
  ) {
    return null;
  }
  throw new Error(
    `Route object registration must use a static array or ${ROUTE_ELEMENT_FACTORY} in ` +
      sourceFile.fileName
  );
}

function registeredRouteArrays(sourceFile) {
  const bindings = reactRouterBindings(sourceFile);
  const initializers = variableInitializers(sourceFile);
  const registrations = [];
  const seenArrays = new Set();

  function visit(node) {
    if (
      ts.isCallExpression(node) &&
      OBJECT_ROUTE_APIS.has(routerApiName(node.expression, bindings))
    ) {
      if (node.arguments.length === 0) {
        throw new Error(`Route object registration requires an argument in ${sourceFile.fileName}`);
      }
      const routeArray = staticRouteArray(node.arguments[0], sourceFile, bindings, initializers);
      if (routeArray && !seenArrays.has(routeArray.pos)) {
        seenArrays.add(routeArray.pos);
        registrations.push(routeArray);
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
  return registrations;
}

function routeProperties(routeObject, sourceFile) {
  const properties = new Map();
  for (const property of routeObject.properties) {
    if (ts.isPropertyAssignment(property)) {
      if (!ts.isIdentifier(property.name) && !ts.isStringLiteral(property.name)) {
        throw new Error(`Route object properties must be static in ${sourceFile.fileName}`);
      }
      properties.set(property.name.text, property.initializer);
      continue;
    }
    if (ts.isShorthandPropertyAssignment(property)) {
      properties.set(property.name.text, property.name);
      continue;
    }
    throw new Error(`Route object cannot contain spreads or methods in ${sourceFile.fileName}`);
  }
  return properties;
}

function staticString(expression, sourceFile, propertyName) {
  const candidate = unwrapExpression(expression);
  if (!ts.isStringLiteral(candidate) && !ts.isNoSubstitutionTemplateLiteral(candidate)) {
    throw new Error(`Route ${propertyName} must be a static string in ${sourceFile.fileName}`);
  }
  return candidate.text;
}

function staticBoolean(expression, sourceFile, propertyName) {
  const candidate = unwrapExpression(expression);
  if (candidate.kind === ts.SyntaxKind.TrueKeyword) {
    return true;
  }
  if (candidate.kind === ts.SyntaxKind.FalseKeyword) {
    return false;
  }
  throw new Error(`Route ${propertyName} must be a static boolean in ${sourceFile.fileName}`);
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

function jsxTagName(node) {
  if (ts.isJsxElement(node)) {
    return node.openingElement.tagName.getText(node.getSourceFile());
  }
  if (!ts.isJsxOpeningElement(node) && !ts.isJsxSelfClosingElement(node)) {
    return null;
  }
  return node.tagName.getText(node.getSourceFile());
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
  visit(unwrapExpression(expression));
  return components;
}

function componentPropertyName(expression, sourceFile) {
  const candidate = unwrapExpression(expression);
  if (ts.isIdentifier(candidate) || ts.isPropertyAccessExpression(candidate)) {
    return candidate.getText(sourceFile);
  }
  throw new Error(`Route Component must be a static component reference in ${sourceFile.fileName}`);
}

function routeEntryForComponent(routeEntriesBySymbol, component) {
  const directEntry = routeEntriesBySymbol.get(component);
  if (directEntry) {
    return directEntry;
  }
  const namespaceSymbol = component.split('.')[0];
  const namespaceEntry = routeEntriesBySymbol.get(namespaceSymbol);
  return namespaceEntry?.export_name === '*' ? namespaceEntry : undefined;
}

export function extractObjectProductionRoutes(
  sourceFile,
  routeSourceEntries,
  { sourceEntry = sourceFile.fileName, parentRoutePath = '' } = {}
) {
  const routeEntriesBySymbol = new Map();
  for (const entry of routeSourceEntries) {
    if (routeEntriesBySymbol.has(entry.symbol)) {
      throw new Error(`Duplicate route source symbol ${entry.symbol} in ${sourceFile.fileName}`);
    }
    routeEntriesBySymbol.set(entry.symbol, entry);
  }
  const initializers = variableInitializers(sourceFile);
  const bindings = reactRouterBindings(sourceFile);
  const routes = [];

  function visitArray(routeArray, parentPath) {
    for (const element of routeArray.elements) {
      const candidate = unwrapExpression(element);
      if (!ts.isObjectLiteralExpression(candidate)) {
        throw new Error(`Route arrays must contain static objects in ${sourceFile.fileName}`);
      }
      const properties = routeProperties(candidate, sourceFile);
      const pathExpression = properties.get('path');
      const indexExpression = properties.get('index');
      const isIndex = indexExpression ? staticBoolean(indexExpression, sourceFile, 'index') : false;
      if (!pathExpression && !isIndex) {
        throw new Error(`Route object must declare path or index in ${sourceFile.fileName}`);
      }
      if (pathExpression && isIndex) {
        throw new Error(`Index route object must not declare path in ${sourceFile.fileName}`);
      }
      const pathPattern = isIndex
        ? parentPath || '/'
        : joinRoutePath(parentPath, staticString(pathExpression, sourceFile, 'path'));
      const elementComponents = properties.has('element')
        ? collectElementComponents(properties.get('element'))
        : [];
      if (properties.has('Component')) {
        const component = componentPropertyName(properties.get('Component'), sourceFile);
        if (!elementComponents.includes(component)) {
          elementComponents.push(component);
        }
      }
      const sourceEntries = elementComponents
        .map((component) => routeEntryForComponent(routeEntriesBySymbol, component))
        .filter(Boolean);
      routes.push({
        path_pattern: pathPattern,
        index: isIndex,
        element_components: elementComponents,
        registration_source: sourceEntry,
        source_entries: sourceEntries,
      });

      const children = properties.get('children');
      if (children) {
        const childArray = staticRouteArray(children, sourceFile, bindings, initializers);
        if (!childArray) {
          throw new Error(
            `Route object children must use a static route array in ${sourceFile.fileName}`
          );
        }
        visitArray(childArray, pathPattern);
      }
    }
  }

  for (const routeArray of registeredRouteArrays(sourceFile)) {
    visitArray(routeArray, parentRoutePath);
  }
  return routes;
}

export function hasObjectRouteRegistrations(sourceFile) {
  return registeredRouteArrays(sourceFile).length > 0;
}

export function collectObjectRoutedComponentSymbols(sourceFile) {
  const routes = extractObjectProductionRoutes(sourceFile, []);
  return new Set(routes.flatMap((route) => route.element_components));
}

export function collectObjectRouteComponentMounts(sourceFile, parentRoutePath = '') {
  const routes = extractObjectProductionRoutes(sourceFile, [], {
    parentRoutePath,
  });
  return routes.flatMap((route) =>
    route.element_components.map((component) => ({
      component,
      parent_path: route.path_pattern,
    }))
  );
}
