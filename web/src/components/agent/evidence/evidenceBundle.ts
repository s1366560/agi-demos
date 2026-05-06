import type { Artifact, ArtifactCategory } from '@/types/agent/config';

/**
 * Distilled from routa's "evidence bundle" idea — a single derived view of all
 * artifact-shaped evidence the agent has produced for one conversation, sliced
 * into four review-friendly tabs.
 *
 * Pure function. No store reads, no side-effects. Caller picks the artifact
 * source (sandbox store, dedicated artifact API, mock for tests, ...).
 */

export type EvidenceTab = 'screenshots' | 'diffs' | 'testRuns' | 'logs';

export interface EvidenceBundle {
  screenshots: Artifact[];
  diffs: Artifact[];
  testRuns: Artifact[];
  logs: Artifact[];
  total: number;
}

const EMPTY_BUNDLE: EvidenceBundle = {
  screenshots: [],
  diffs: [],
  testRuns: [],
  logs: [],
  total: 0,
};

const DIFF_EXT = /\.(diff|patch)$/i;
const TEST_TOOLS = new Set(['run_tests', 'analyze_coverage', 'generate_tests']);
const LOG_EXT = /\.(log|txt|jsonl)$/i;

function isImage(a: Artifact): boolean {
  return a.category === ('image' as ArtifactCategory) || a.mimeType.startsWith('image/');
}

function isDiff(a: Artifact): boolean {
  if (a.mimeType === 'text/x-diff' || a.mimeType === 'text/x-patch') return true;
  return DIFF_EXT.test(a.filename);
}

function isTestRun(a: Artifact): boolean {
  if (a.sourceTool && TEST_TOOLS.has(a.sourceTool)) return true;
  const meta = a.metadata as Record<string, unknown> | undefined;
  return Boolean(meta && typeof meta['testRun'] === 'object');
}

function isLog(a: Artifact): boolean {
  if (a.category === ('code' as ArtifactCategory) && LOG_EXT.test(a.filename)) return true;
  if (a.mimeType === 'text/plain' && LOG_EXT.test(a.filename)) return true;
  return a.mimeType === 'application/x-ndjson';
}

/**
 * Bucket a flat list of artifacts (already filtered to one conversation) into
 * the four evidence tabs. An artifact lands in the first bucket it matches —
 * order of preference: testRuns, diffs, screenshots, logs.
 */
export function buildEvidenceBundle(artifacts: readonly Artifact[]): EvidenceBundle {
  if (artifacts.length === 0) return EMPTY_BUNDLE;

  const screenshots: Artifact[] = [];
  const diffs: Artifact[] = [];
  const testRuns: Artifact[] = [];
  const logs: Artifact[] = [];

  for (const artifact of artifacts) {
    if (isTestRun(artifact)) testRuns.push(artifact);
    else if (isDiff(artifact)) diffs.push(artifact);
    else if (isImage(artifact)) screenshots.push(artifact);
    else if (isLog(artifact)) logs.push(artifact);
  }

  return {
    screenshots,
    diffs,
    testRuns,
    logs,
    total: screenshots.length + diffs.length + testRuns.length + logs.length,
  };
}

/**
 * Filter a flat artifact map (e.g. `useSandboxStore().artifacts`) down to a
 * conversation, then bucket. Convenience wrapper for store consumers.
 */
export function selectEvidenceBundle(
  artifacts: Iterable<Artifact>,
  conversationId: string,
): EvidenceBundle {
  const filtered: Artifact[] = [];
  for (const artifact of artifacts) {
    if (artifact.conversationId === conversationId) filtered.push(artifact);
  }
  return buildEvidenceBundle(filtered);
}

export const EVIDENCE_TAB_ORDER: readonly EvidenceTab[] = [
  'testRuns',
  'diffs',
  'screenshots',
  'logs',
];
