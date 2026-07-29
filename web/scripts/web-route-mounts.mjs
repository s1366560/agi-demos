import { extname } from 'node:path';

import ts from 'typescript';

import { collectObjectRouteComponentMounts } from './web-route-object-extractors.mjs';
import { resolveWebSourceEntry, ROUTER_RELATIVE_PATH } from './web-route-source-resolver.mjs';

const CODE_EXTENSIONS = new Set(['', '.js', '.jsx', '.ts', '.tsx']);

function parseSource(sourceEntry, source) {
  const extension = extname(sourceEntry);
  const scriptKind =
    extension === '.ts'
      ? ts.ScriptKind.TS
      : extension === '.js'
        ? ts.ScriptKind.JS
        : extension === '.jsx'
          ? ts.ScriptKind.JSX
          : ts.ScriptKind.TSX;
  const sourceFile = ts.createSourceFile(
    sourceEntry,
    source,
    ts.ScriptTarget.Latest,
    true,
    scriptKind
  );
  if (sourceFile.parseDiagnostics.length > 0) {
    throw new Error(`Cannot parse route mount source ${sourceEntry}`);
  }
  return sourceFile;
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
  return ts.isJsxElement(node)
    ? node.openingElement.attributes.properties
    : node.attributes.properties;
}

function jsxAttribute(node, name) {
  return jsxAttributes(node).find(
    (attribute) => ts.isJsxAttribute(attribute) && attribute.name.getText() === name
  );
}

function staticStringAttribute(attribute, sourceFile, name) {
  const initializer = attribute?.initializer;
  if (ts.isStringLiteral(initializer)) {
    return initializer.text;
  }
  if (
    ts.isJsxExpression(initializer) &&
    (ts.isStringLiteral(initializer.expression) ||
      ts.isNoSubstitutionTemplateLiteral(initializer.expression))
  ) {
    return initializer.expression.text;
  }
  throw new Error(`Route ${name} must be static in ${sourceFile.fileName}`);
}

function booleanAttribute(attribute, sourceFile, name) {
  if (!attribute) return false;
  if (!attribute.initializer) return true;
  if (ts.isJsxExpression(attribute.initializer)) {
    if (attribute.initializer.expression?.kind === ts.SyntaxKind.TrueKeyword) return true;
    if (attribute.initializer.expression?.kind === ts.SyntaxKind.FalseKeyword) return false;
  }
  throw new Error(`Route ${name} must be static in ${sourceFile.fileName}`);
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

function isLocalSourceSpecifier(moduleSpecifier) {
  return (
    (moduleSpecifier.startsWith('.') ||
      moduleSpecifier === '@' ||
      moduleSpecifier.startsWith('@/')) &&
    CODE_EXTENSIONS.has(extname(moduleSpecifier))
  );
}

function resolveTarget(moduleSpecifier, repositoryRoot, sourceEntry) {
  if (!isLocalSourceSpecifier(moduleSpecifier)) return null;
  return resolveWebSourceEntry({
    moduleSpecifier,
    repositoryRoot,
    entryKind: 'route mount',
    importerRelativePath: sourceEntry,
  });
}

function localBindings(sourceFile, repositoryRoot, sourceEntry) {
  const bindings = new Map();
  const reexports = [];
  for (const statement of sourceFile.statements) {
    if (
      ts.isExportDeclaration(statement) &&
      statement.moduleSpecifier &&
      ts.isStringLiteral(statement.moduleSpecifier)
    ) {
      const target = resolveTarget(statement.moduleSpecifier.text, repositoryRoot, sourceEntry);
      if (target) reexports.push(target);
      continue;
    }
    if (
      !ts.isImportDeclaration(statement) ||
      !ts.isStringLiteral(statement.moduleSpecifier) ||
      !statement.importClause
    ) {
      continue;
    }
    const target = resolveTarget(statement.moduleSpecifier.text, repositoryRoot, sourceEntry);
    if (!target) continue;
    if (statement.importClause.name) {
      bindings.set(statement.importClause.name.text, target);
    }
    const named = statement.importClause.namedBindings;
    if (named && ts.isNamespaceImport(named)) {
      bindings.set(named.name.text, target);
    } else if (named && ts.isNamedImports(named)) {
      for (const element of named.elements) bindings.set(element.name.text, target);
    }
  }

  function visitLazy(node) {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      let importTarget = null;
      function findImport(candidate) {
        if (
          ts.isCallExpression(candidate) &&
          candidate.expression.kind === ts.SyntaxKind.ImportKeyword &&
          candidate.arguments.length === 1 &&
          ts.isStringLiteral(candidate.arguments[0])
        ) {
          importTarget = resolveTarget(candidate.arguments[0].text, repositoryRoot, sourceEntry);
          return;
        }
        ts.forEachChild(candidate, findImport);
      }
      findImport(node.initializer);
      if (importTarget) bindings.set(node.name.text, importTarget);
    }
    ts.forEachChild(node, visitLazy);
  }
  visitLazy(sourceFile);
  return { bindings, reexports };
}

function routeBindings(sourceFile) {
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
    const named = statement.importClause.namedBindings;
    if (named && ts.isNamespaceImport(named)) {
      bindings.add(`${named.name.text}.Route`);
    } else if (named && ts.isNamedImports(named)) {
      for (const element of named.elements) {
        if ((element.propertyName?.text ?? element.name.text) === 'Route') {
          bindings.add(element.name.text);
        }
      }
    }
  }
  return bindings;
}

function componentMountEdges(source, repositoryRoot, sourceEntry, mountPath) {
  const sourceFile = parseSource(sourceEntry, source);
  const routes = routeBindings(sourceFile);
  const { bindings, reexports } = localBindings(sourceFile, repositoryRoot, sourceEntry);
  const edges = reexports.map((target) => ({ target, parent_path: mountPath }));

  function visit(node, parentRoutePath) {
    const tagName = jsxTagName(node);
    if (tagName && routes.has(tagName)) {
      const pathAttribute = jsxAttribute(node, 'path');
      const isIndex = booleanAttribute(jsxAttribute(node, 'index'), sourceFile, 'index');
      if (!pathAttribute && !isIndex) {
        throw new Error(`Route must declare path or index in ${sourceFile.fileName}`);
      }
      const pathPattern = isIndex
        ? parentRoutePath || '/'
        : joinRoutePath(parentRoutePath, staticStringAttribute(pathAttribute, sourceFile, 'path'));
      ts.forEachChild(node, (child) => visit(child, pathPattern));
      return;
    }
    if (tagName) {
      const target = bindings.get(tagName.split('.')[0]);
      if (target) edges.push({ target, parent_path: parentRoutePath });
    }
    ts.forEachChild(node, (child) => visit(child, parentRoutePath));
  }

  visit(sourceFile, mountPath);
  for (const objectMount of collectObjectRouteComponentMounts(sourceFile, mountPath)) {
    const target = bindings.get(objectMount.component.split('.')[0]);
    if (target) {
      edges.push({ target, parent_path: objectMount.parent_path });
    }
  }
  return edges;
}

export function resolveRouteRegistrationMounts(sourceGraph, repositoryRoot) {
  const sources = new Map(
    sourceGraph.reachable_sources.map((source) => [source.source_entry, source.source])
  );
  const mounts = new Map();

  function visit(sourceEntry, mountPath, ancestry) {
    const sourceMounts = mounts.get(sourceEntry) ?? new Set();
    if (sourceMounts.has(mountPath)) return;
    if (ancestry.has(sourceEntry)) {
      throw new Error(`Reachable route component cycle changes the mount path for ${sourceEntry}`);
    }
    sourceMounts.add(mountPath);
    mounts.set(sourceEntry, sourceMounts);
    const nextAncestry = new Set(ancestry).add(sourceEntry);
    const source = sources.get(sourceEntry);
    if (source === undefined) {
      throw new Error(`Missing reachable route source ${sourceEntry}`);
    }
    for (const edge of componentMountEdges(source, repositoryRoot, sourceEntry, mountPath)) {
      if (!sources.has(edge.target)) {
        continue;
      }
      visit(edge.target, edge.parent_path, nextAncestry);
    }
  }

  visit(ROUTER_RELATIVE_PATH, '', new Set());
  return new Map(
    [...mounts].map(([sourceEntry, sourceMounts]) => [sourceEntry, [...sourceMounts].sort()])
  );
}
