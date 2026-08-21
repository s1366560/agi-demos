#!/usr/bin/env node
/** Fail-closed TypeScript Compiler API scanner for protocol-v2 module contracts. */

import process from 'node:process';

import ts from 'typescript';

const CONTEXT_METHODS = new Set(['provide', 'require', 'on', 'dispatch']);

export function scanTypeScriptContractV2(request) {
  const sourceFile = ts.createSourceFile(
    'plugin.ts',
    request.source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TS
  );
  const parseDiagnostics = sourceFile.parseDiagnostics ?? [];
  if (parseDiagnostics.length > 0) {
    return {
      issues: parseDiagnostics.map((diagnostic) => ({
        code: 'typescript_source_invalid',
        line: diagnostic.start === undefined ? null : lineOf(sourceFile, diagnostic.start),
        detail: ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n'),
      })),
    };
  }

  const functions = collectFunctions(sourceFile);
  const constants = collectConstants(sourceFile);
  const resolved = resolveEntrypoint(request.entrypoint, functions);
  if (resolved.issue) return { issues: [resolved.issue] };
  const { key: entrypoint, node: entrypointNode } = resolved;
  if (contextParameterNames(entrypointNode).size === 0) {
    return {
      issues: [
        issueAt(
          sourceFile,
          entrypointNode,
          'unclassified_entrypoint_context',
          'TypeScript entrypoint has no typed ContextV2 parameter'
        ),
      ],
    };
  }

  const declarations = new Map(
    Object.entries(request.declarations).map(([method, values]) => [method, new Set(values)])
  );
  const pending = [entrypoint];
  const visited = new Set();
  const issues = [];
  while (pending.length > 0) {
    const name = pending.shift();
    if (visited.has(name)) continue;
    visited.add(name);
    const [node] = functions.get(name) ?? [];
    if (!node) continue;
    const contextNames = contextParameterNames(node);
    scanFunction({
      sourceFile,
      node,
      contextNames,
      constants,
      declarations,
      functions,
      pending,
      issues,
    });
  }
  issues.sort(
    (left, right) =>
      (left.line ?? 0) - (right.line ?? 0) ||
      left.code.localeCompare(right.code) ||
      left.detail.localeCompare(right.detail)
  );
  return { issues };
}

function collectFunctions(sourceFile) {
  const functions = new Map();
  const add = (name, node) => functions.set(name, [...(functions.get(name) ?? []), node]);
  for (const statement of sourceFile.statements) {
    if (ts.isFunctionDeclaration(statement) && statement.name && statement.body) {
      add(statement.name.text, statement);
      continue;
    }
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (
          ts.isIdentifier(declaration.name) &&
          declaration.initializer &&
          (ts.isArrowFunction(declaration.initializer) ||
            ts.isFunctionExpression(declaration.initializer)) &&
          declaration.initializer.body
        ) {
          add(declaration.name.text, declaration.initializer);
        }
      }
      continue;
    }
    if (ts.isClassDeclaration(statement) && statement.name) {
      for (const member of statement.members) {
        if (ts.isMethodDeclaration(member) && member.name && member.body) {
          const name = propertyName(member.name);
          if (name) add(`${statement.name.text}.${name}`, member);
        }
      }
    }
  }
  return functions;
}

function resolveEntrypoint(entrypoint, functions) {
  const parts = entrypoint.split(/[:#.]/).filter(Boolean);
  const symbol = parts.at(-1) ?? entrypoint;
  const qualified = parts.length >= 2 ? `${parts.at(-2)}.${symbol}` : undefined;
  const exact = entrypoint.replaceAll('#', '.').replaceAll('::', '.');
  const candidateKeys = [...new Set([exact, qualified, symbol].filter(Boolean))];
  for (const key of candidateKeys) {
    const candidates = functions.get(key);
    if (!candidates) continue;
    if (candidates.length === 1) return { key, node: candidates[0] };
    return {
      issue: {
        code: 'unclassified_entrypoint_apply',
        line: null,
        detail: `TypeScript entrypoint function is ambiguous: ${entrypoint}`,
      },
    };
  }
  const suffix = `.${symbol}`;
  const matches = [...functions.entries()].filter(([key]) => key.endsWith(suffix));
  if (matches.length === 1 && matches[0][1].length === 1) {
    return { key: matches[0][0], node: matches[0][1][0] };
  }
  return {
    issue: {
      code: matches.length === 0 ? 'entrypoint_missing' : 'unclassified_entrypoint_apply',
      line: null,
      detail:
        matches.length === 0
          ? `TypeScript entrypoint function is not defined: ${entrypoint}`
          : `TypeScript entrypoint function is ambiguous: ${entrypoint}`,
    },
  };
}

function collectConstants(sourceFile) {
  const constants = new Map();
  for (const statement of sourceFile.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    if (!(statement.declarationList.flags & ts.NodeFlags.Const)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || !declaration.initializer) continue;
      const value = literalString(declaration.initializer);
      if (value !== undefined) constants.set(declaration.name.text, value);
    }
  }
  return constants;
}

function scanFunction(state) {
  const visit = (node) => {
    if (ts.isCallExpression(node)) {
      const direct = directContextMethod(node.expression, state.contextNames);
      if (direct) {
        checkContextCall(state, node, direct);
      } else if (computedContextCall(node.expression, state.contextNames)) {
        state.issues.push(
          issueAt(
            state.sourceFile,
            node,
            'unclassified_context_call',
            'computed ContextV2 call cannot be classified'
          )
        );
      } else if (ts.isIdentifier(node.expression) && state.functions.has(node.expression.text)) {
        state.pending.push(node.expression.text);
      }
    }
    if (
      ts.isPropertyAccessExpression(node) &&
      ts.isIdentifier(node.expression) &&
      state.contextNames.has(node.expression.text) &&
      CONTEXT_METHODS.has(node.name.text) &&
      !(ts.isCallExpression(node.parent) && node.parent.expression === node)
    ) {
      state.issues.push(
        issueAt(
          state.sourceFile,
          node,
          'unclassified_context_call',
          `context.${node.name.text} is not called directly`
        )
      );
    }
    ts.forEachChild(node, visit);
  };
  visit(state.node.body);
}

function checkContextCall(state, call, method) {
  const first = call.arguments[0];
  const value = first ? staticKey(first, state.constants) : undefined;
  if (value === undefined) {
    state.issues.push(
      issueAt(
        state.sourceFile,
        call,
        'unclassified_context_call',
        `context.${method} requires a literal string declaration key`
      )
    );
    return;
  }
  if (!state.declarations.get(method)?.has(value)) {
    state.issues.push(
      issueAt(
        state.sourceFile,
        call,
        'undeclared_context_call',
        `context.${method} ${value} is absent from the module contract`
      )
    );
  }
}

function directContextMethod(expression, contextNames) {
  if (
    !ts.isPropertyAccessExpression(expression) ||
    !ts.isIdentifier(expression.expression) ||
    !contextNames.has(expression.expression.text) ||
    !CONTEXT_METHODS.has(expression.name.text)
  ) {
    return undefined;
  }
  return expression.name.text;
}

function computedContextCall(expression, contextNames) {
  return (
    ts.isElementAccessExpression(expression) &&
    ts.isIdentifier(expression.expression) &&
    contextNames.has(expression.expression.text)
  );
}

function contextParameterNames(node) {
  return new Set(
    node.parameters
      .filter(
        (parameter) =>
          ts.isIdentifier(parameter.name) &&
          parameter.type &&
          typeName(parameter.type) === 'ContextV2'
      )
      .map((parameter) => parameter.name.text)
  );
}

function typeName(type) {
  if (ts.isTypeReferenceNode(type) && ts.isIdentifier(type.typeName)) return type.typeName.text;
  if (ts.isTypeReferenceNode(type) && ts.isQualifiedName(type.typeName))
    return type.typeName.right.text;
  if (ts.isParenthesizedTypeNode(type)) return typeName(type.type);
  return undefined;
}

function staticKey(expression, constants) {
  return (
    literalString(expression) ??
    (ts.isIdentifier(expression) ? constants.get(expression.text) : undefined)
  );
}

function literalString(expression) {
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) {
    return expression.text;
  }
  return undefined;
}

function propertyName(name) {
  return ts.isIdentifier(name) || ts.isStringLiteral(name) ? name.text : undefined;
}

function issueAt(sourceFile, node, code, detail) {
  return { code, line: lineOf(sourceFile, node.getStart(sourceFile)), detail };
}

function lineOf(sourceFile, position) {
  return sourceFile.getLineAndCharacterOfPosition(position).line + 1;
}

async function main() {
  let input = '';
  process.stdin.setEncoding('utf8');
  for await (const chunk of process.stdin) input += chunk;
  const request = JSON.parse(input);
  process.stdout.write(JSON.stringify(scanTypeScriptContractV2(request)));
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 2;
  });
}
