/**
 * Script to fix exactOptionalPropertyTypes errors (v3).
 *
 * For every optional property signature (`prop?: T`) inside interfaces
 * and type literals, adds `| undefined` if not already present.
 *
 * Key improvements over v2:
 * - Runs iteratively until convergence (handles nested type literals safely)
 * - Wraps function/constructor types in parens before adding `| undefined`
 * - Only processes direct children of interface/type-literal
 * - Filters overlapping replacements per pass to avoid position corruption
 *
 * Usage: npx tsx fix-exact-optional.ts
 */

import * as ts from 'typescript';
import * as fs from 'fs';
import * as path from 'path';

function getAllTsFiles(dir: string): string[] {
  const results: string[] = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === 'dist') continue;
      results.push(...getAllTsFiles(fullPath));
    } else if (entry.isFile() && (entry.name.endsWith('.ts') || entry.name.endsWith('.tsx'))) {
      results.push(fullPath);
    }
  }
  return results;
}

interface Replacement {
  start: number;
  end: number;
  newText: string;
}

/**
 * Check if the IMMEDIATE parent of this PropertySignature is an
 * InterfaceDeclaration or TypeLiteralNode.
 */
function isDirectChildOfInterfaceOrTypeLiteral(node: ts.Node): boolean {
  const parent = node.parent;
  if (!parent) return false;
  return ts.isInterfaceDeclaration(parent) || ts.isTypeLiteralNode(parent);
}

/**
 * Collect replacements for a single file. Only collects NON-OVERLAPPING
 * replacements per pass (keeps outer, defers inner to next iteration).
 */
function processFile(filePath: string): { replacements: Replacement[]; skipped: number } {
  const sourceText = fs.readFileSync(filePath, 'utf-8');
  const sourceFile = ts.createSourceFile(
    filePath,
    sourceText,
    ts.ScriptTarget.Latest,
    true,
    filePath.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  );

  const allReplacements: Replacement[] = [];

  function visit(node: ts.Node) {
    if (ts.isPropertySignature(node) && node.questionToken && node.type) {
      if (isDirectChildOfInterfaceOrTypeLiteral(node)) {
        const typeNode = node.type;
        const typeStart = typeNode.getStart(sourceFile);
        const typeEnd = typeNode.getEnd();
        const typeText = sourceText.substring(typeStart, typeEnd);

        // Check if already has undefined
        if (!/\bundefined\b/.test(typeText)) {
          let newText: string;
          if (ts.isFunctionTypeNode(typeNode) || ts.isConstructorTypeNode(typeNode)) {
            newText = `(${typeText}) | undefined`;
          } else {
            newText = `${typeText} | undefined`;
          }
          allReplacements.push({ start: typeStart, end: typeEnd, newText });
        }
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);

  // Sort by start, filter overlapping (keep first/outer, defer inner)
  const sorted = [...allReplacements].sort((a, b) => a.start - b.start || b.end - a.end);
  const filtered: Replacement[] = [];
  let skipped = 0;

  for (const r of sorted) {
    const overlaps = filtered.some((f) => r.start < f.end && r.end > f.start);
    if (!overlaps) {
      filtered.push(r);
    } else {
      skipped++;
    }
  }

  return { replacements: filtered, skipped };
}

function applyReplacements(filePath: string, replacements: Replacement[]): void {
  if (replacements.length === 0) return;

  let content = fs.readFileSync(filePath, 'utf-8');

  // Apply from end to start to preserve positions
  const sorted = [...replacements].sort((a, b) => b.start - a.start);

  for (const r of sorted) {
    content = content.substring(0, r.start) + r.newText + content.substring(r.end);
  }

  fs.writeFileSync(filePath, content, 'utf-8');
}

// Main - run iteratively until convergence
const srcDir = path.join(process.cwd(), 'src');
const files = getAllTsFiles(srcDir);

let iteration = 0;
let grandTotal = 0;

while (true) {
  iteration++;
  let totalReplacements = 0;
  let totalSkipped = 0;
  let filesModified = 0;

  for (const file of files) {
    const { replacements, skipped } = processFile(file);
    totalSkipped += skipped;
    if (replacements.length > 0) {
      applyReplacements(file, replacements);
      filesModified++;
      totalReplacements += replacements.length;
      if (iteration === 1) {
        const rel = path.relative(process.cwd(), file);
        console.log(`  ${rel}: ${replacements.length} properties fixed`);
      }
    }
  }

  grandTotal += totalReplacements;
  console.log(`Iteration ${iteration}: ${totalReplacements} fixes across ${filesModified} files (${totalSkipped} deferred)`);

  if (totalReplacements === 0) {
    break;
  }

  if (iteration > 5) {
    console.log('WARNING: Exceeded 5 iterations, stopping.');
    break;
  }
}

console.log(`\nDone: ${grandTotal} total optional properties fixed`);
