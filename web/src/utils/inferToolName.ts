/**
 * Infer the actual tool name when an upstream provider reports a generic
 * placeholder (`unknown`, `other`, `tool`, `""`).
 *
 * Distilled from routa's `trace-panel.tsx::inferToolName`. Uses input-shape
 * heuristics so the timeline UI can label tool cards even when SSE adapters
 * fail to forward the proper `tool_name`.
 *
 * Add new shape rules here, not in render code, to keep the inference
 * surface auditable and unit-testable.
 */

const PLACEHOLDER_NAMES = new Set(['', 'unknown', 'other', 'tool']);

/** Ordered list of `(predicate, inferredName)` rules. First match wins. */
type Rule = readonly [(input: Record<string, unknown>) => boolean, string];

const RULES: readonly Rule[] = [
  [(i) => 'information_request' in i, 'codebase-retrieval'],
  [(i) => 'pattern' in i && 'isRegexp' in i, 'grep_search'],
  [(i) => 'query' in i && ('files' in i || 'maxResults' in i), 'file_search'],
  [(i) => 'symbol' in i && 'newName' in i, 'rename_symbol'],
  [(i) => 'file_path' in i && 'content' in i, 'write_file'],
  [(i) => 'file_path' in i && 'old_string' in i && 'new_string' in i, 'replace_string_in_file'],
  [(i) => 'file_path' in i, 'read_file'],
  [(i) => 'filePath' in i && 'content' in i, 'write_file'],
  [(i) => 'filePath' in i && 'oldString' in i && 'newString' in i, 'replace_string_in_file'],
  [(i) => 'filePath' in i && ('startLine' in i || 'endLine' in i), 'read_file'],
  [(i) => 'filePath' in i, 'read_file'],
  [(i) => 'command' in i && 'mode' in i, 'run_in_terminal'],
  [(i) => 'command' in i, 'run_command'],
  [(i) => 'url' in i && 'query' in i, 'fetch_webpage'],
  [(i) => 'urls' in i, 'fetch_webpage'],
  [(i) => 'sql' in i || ('query' in i && 'database' in i), 'sql_query'],
];

/**
 * Returns the original name when it is non-placeholder, otherwise returns the
 * first matching inferred name, otherwise returns the original.
 */
export function inferToolName(name: string | null | undefined, input: unknown): string {
  const original = (name ?? '').trim();
  if (!PLACEHOLDER_NAMES.has(original)) {
    return original;
  }

  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return original || 'unknown';
  }

  const record = input as Record<string, unknown>;
  for (const [predicate, inferred] of RULES) {
    try {
      if (predicate(record)) {
        return inferred;
      }
    } catch {
      // Predicates are pure shape checks; defensive against rogue proxies.
    }
  }
  return original || 'unknown';
}

/** True iff inference would change the name. Useful for telemetry/badging. */
export function isInferredToolName(name: string | null | undefined, input: unknown): boolean {
  return inferToolName(name, input) !== (name ?? '').trim();
}
