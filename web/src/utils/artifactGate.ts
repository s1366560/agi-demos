/**
 * ArtifactGate — declarative "what evidence each lane requires" model.
 *
 * Distilled from routa's `src/core/kanban/transition-artifacts.ts` +
 * `src/core/models/kanban` happy-path ordering.
 *
 * The gate evaluates a task against the *next* column's required artifacts:
 * - `requiredArtifacts`: kinds the task must have produced before advancing.
 * - `missing`: subset of `requiredArtifacts` not yet attached to the task.
 * - `canAdvance`: true iff `missing` is empty.
 *
 * Keep this file framework-free so it can run in tests, hooks, server tools.
 */

export type ArtifactType =
  | 'screenshot'
  | 'test_results'
  | 'code_diff'
  | 'logs'
  | 'commit'
  | 'review_findings'
  | 'completion_summary';

const ARTIFACT_LABELS: Record<ArtifactType, string> = {
  screenshot: 'Screenshot',
  test_results: 'Test Results',
  code_diff: 'Code Diff',
  logs: 'Logs',
  commit: 'Commit',
  review_findings: 'Review Findings',
  completion_summary: 'Completion Summary',
};

export function formatArtifactLabel(artifact: string): string {
  return artifact in ARTIFACT_LABELS ? ARTIFACT_LABELS[artifact as ArtifactType] : artifact;
}

export interface KanbanColumnGateConfig {
  id: string;
  name: string;
  /** Position in happy-path order (0-indexed). */
  position: number;
  /** Artifacts that must be produced *in this column* before moving forward. */
  requiredArtifacts: ArtifactType[];
}

export interface ArtifactSummary {
  /** Total number of artifacts attached to the task. */
  total: number;
  /** Per-type counts. Missing keys mean zero. */
  byType: Partial<Record<ArtifactType, number>>;
}

export interface ArtifactGateEvaluation {
  currentColumn: KanbanColumnGateConfig | null;
  nextColumn: KanbanColumnGateConfig | null;
  /** Artifacts the next column expects this task to have. */
  requiredArtifacts: ArtifactType[];
  /** Required artifacts not yet present on the task. */
  missing: ArtifactType[];
  canAdvance: boolean;
}

export interface KanbanBoardGateConfig {
  /** Columns in happy-path order. */
  columns: KanbanColumnGateConfig[];
}

/**
 * Evaluate whether `task` (with its `summary` of attached artifacts) can move
 * out of `currentColumnId` into the next happy-path column.
 *
 * If the task is already in the terminal column, `canAdvance` is true and
 * `nextColumn` is null.
 */
export function evaluateArtifactGate(
  board: KanbanBoardGateConfig,
  currentColumnId: string,
  summary: ArtifactSummary
): ArtifactGateEvaluation {
  const sorted = [...board.columns].sort((a, b) => a.position - b.position);
  const currentIdx = sorted.findIndex((c) => c.id === currentColumnId);
  const currentColumn = currentIdx >= 0 ? (sorted[currentIdx] ?? null) : null;
  const nextColumn =
    currentIdx >= 0 && currentIdx + 1 < sorted.length ? (sorted[currentIdx + 1] ?? null) : null;

  if (!nextColumn) {
    return {
      currentColumn,
      nextColumn: null,
      requiredArtifacts: [],
      missing: [],
      canAdvance: true,
    };
  }

  const required = nextColumn.requiredArtifacts;
  const missing = required.filter((kind) => (summary.byType[kind] ?? 0) === 0);

  return {
    currentColumn,
    nextColumn,
    requiredArtifacts: required,
    missing,
    canAdvance: missing.length === 0,
  };
}

/**
 * Default lane contract distilled from routa's Kanban specialist contracts.
 * Use as a starting point; teams can override per board.
 */
export const DEFAULT_LANE_CONTRACT: KanbanBoardGateConfig = {
  columns: [
    { id: 'backlog', name: 'Backlog', position: 0, requiredArtifacts: [] },
    { id: 'todo', name: 'Todo', position: 1, requiredArtifacts: [] },
    { id: 'dev', name: 'Dev', position: 2, requiredArtifacts: ['code_diff'] },
    {
      id: 'review',
      name: 'Review',
      position: 3,
      requiredArtifacts: ['code_diff', 'test_results', 'commit'],
    },
    {
      id: 'done',
      name: 'Done',
      position: 4,
      requiredArtifacts: ['code_diff', 'test_results', 'commit', 'review_findings'],
    },
  ],
};
