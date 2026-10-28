import ts from 'typescript';

const printer = ts.createPrinter({ newLine: ts.NewLineKind.LineFeed });
const f = ts.factory;
const globalName = (name) => f.createElementAccessExpression(f.createIdentifier('globalThis'), f.createStringLiteral(name));

function assignmentTarget(name) {
  if (ts.isIdentifier(name)) return globalName(name.text);
  if (ts.isArrayBindingPattern(name)) {
    return f.createArrayLiteralExpression(name.elements.map((element) => {
      if (ts.isOmittedExpression(element)) return element;
      const target = assignmentTarget(element.name);
      if (element.dotDotDotToken) return f.createSpreadElement(target);
      return element.initializer ? f.createAssignment(target, element.initializer) : target;
    }));
  }
  return f.createObjectLiteralExpression(name.elements.map((element) => {
    const target = assignmentTarget(element.name);
    if (element.dotDotDotToken) return f.createSpreadAssignment(target);
    return f.createPropertyAssignment(element.propertyName ?? element.name,
      element.initializer ? f.createAssignment(target, element.initializer) : target);
  }));
}

/** Lower only REPL top-level bindings; nested lexical scopes stay ordinary JavaScript. */
export function compileCell(code, filename) {
  const source = ts.createSourceFile(filename, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);
  if (source.parseDiagnostics.length) {
    throw new SyntaxError(ts.flattenDiagnosticMessageText(source.parseDiagnostics[0].messageText, '\n'));
  }
  const statements = [];
  const hoisted = [];
  let importIndex = 0;
  const assign = (name, expression) => f.createExpressionStatement(f.createAssignment(assignmentTarget(name), expression));
  for (const statement of source.statements) {
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        // var without an initializer does not overwrite an existing REPL binding.
        if (!declaration.initializer && !(statement.declarationList.flags & ts.NodeFlags.BlockScoped)) {
          if (ts.isIdentifier(declaration.name)) statements.push(f.createExpressionStatement(
            f.createBinaryExpression(globalName(declaration.name.text), ts.SyntaxKind.QuestionQuestionEqualsToken, f.createIdentifier('undefined'))));
        } else statements.push(assign(declaration.name, declaration.initializer ?? f.createIdentifier('undefined')));
      }
    } else if (ts.isFunctionDeclaration(statement) && statement.name) {
      hoisted.push(assign(statement.name, f.createFunctionExpression(statement.modifiers?.filter(m => m.kind === ts.SyntaxKind.AsyncKeyword),
        statement.asteriskToken, statement.name, undefined, statement.parameters, undefined, statement.body)));
    } else if (ts.isClassDeclaration(statement) && statement.name) {
      statements.push(assign(statement.name, f.createClassExpression(undefined, statement.name, undefined, statement.heritageClauses, statement.members)));
    } else if (ts.isImportDeclaration(statement)) {
      const load = f.createAwaitExpression(f.createCallExpression(f.createIdentifier('__cua_import__'), undefined, [statement.moduleSpecifier]));
      const clause = statement.importClause;
      if (!clause) statements.push(f.createExpressionStatement(load));
      else {
        const temp = f.createIdentifier(`__cua_import_${importIndex++}`);
        statements.push(f.createVariableStatement(undefined, f.createVariableDeclarationList([f.createVariableDeclaration(temp, undefined, undefined, load)], ts.NodeFlags.Const)));
        if (clause.name) statements.push(assign(clause.name, f.createPropertyAccessExpression(temp, 'default')));
        if (clause.namedBindings && ts.isNamespaceImport(clause.namedBindings)) statements.push(assign(clause.namedBindings.name, temp));
        else for (const binding of clause.namedBindings?.elements ?? []) {
          statements.push(assign(binding.name, f.createElementAccessExpression(temp, f.createStringLiteral((binding.propertyName ?? binding.name).text))));
        }
      }
    } else if (ts.isExportDeclaration(statement) || ts.isExportAssignment(statement) || statement.modifiers?.some(m => m.kind === ts.SyntaxKind.ExportKeyword)) {
      throw new SyntaxError('REPL cells do not export modules; write a module file to use exports');
    } else statements.push(statement);
  }
  const last = statements.at(-1);
  if (last && ts.isExpressionStatement(last) && source.statements.at(-1)?.kind === ts.SyntaxKind.ExpressionStatement) {
    statements[statements.length - 1] = f.createReturnStatement(last.expression);
  }
  const body = [...hoisted, ...statements].map(node => printer.printNode(ts.EmitHint.Unspecified, node, source)).join('\n');
  return `(async () => {\n${body}\n})()`;
}
