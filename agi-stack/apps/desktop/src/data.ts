export type TaskMode = 'work' | 'code';

export interface TaskPlanStep {
  title: string;
  detail: string;
  output: string;
  duration: string;
}

export interface TaskItem {
  id: string;
  title: string;
  summary: string;
  status: string;
  meta: string;
  progress: number;
  phase: string;
  plan?: TaskPlanStep[];
  context?: string[];
}

export const workTasks: TaskItem[] = [
  {
    id: 'strategy-brief',
    title: 'Q3 product strategy brief',
    summary: 'Synthesize research into a leadership-ready product strategy.',
    status: 'input',
    meta: 'Needs your input',
    progress: 86,
    phase: 'Drafting final brief',
  },
  {
    id: 'customer-risk',
    title: 'Review customer escalation',
    summary: 'Needs your decision on the proposed service-credit range.',
    status: 'ready',
    meta: 'Ready 9 min ago',
    progress: 100,
    phase: 'Ready to review',
  },
  {
    id: 'competitor-watch',
    title: 'Competitor launch watch',
    summary: 'Monitor product announcements and summarize material changes.',
    status: 'running',
    meta: '5 sources · live',
    progress: 63,
    phase: 'Comparing launch claims',
  },
  {
    id: 'weekly-brief',
    title: 'Weekly leadership digest',
    summary: 'A concise readout of decisions, risks, and metrics.',
    status: 'ready',
    meta: 'Ready 12 min ago',
    progress: 100,
    phase: 'Ready to review',
  },
];

export const codeTasks: TaskItem[] = [
  {
    id: 'flaky-test',
    title: 'Fix flaky data-pipeline test',
    summary: 'Trace the race, isolate the shared fixture, and verify the CI path.',
    status: 'running',
    meta: 'worktree · 6 files',
    progress: 72,
    phase: 'Running targeted tests',
  },
  {
    id: 'auth-review',
    title: 'Review auth middleware refactor',
    summary: 'Needs approval before replacing the token refresh boundary.',
    status: 'input',
    meta: 'Approval required',
    progress: 51,
    phase: 'Waiting for approval',
  },
  {
    id: 'desktop-search',
    title: 'Add task search shortcuts',
    summary: 'Implement command-palette search for task titles and artifacts.',
    status: 'ready',
    meta: '+148 −29 · 7 files',
    progress: 100,
    phase: 'Changes ready to review',
  },
  {
    id: 'sdk-upgrade',
    title: 'Plan agent SDK upgrade',
    summary: 'Map breaking changes and propose a staged migration.',
    status: 'ready',
    meta: 'Plan ready',
    progress: 100,
    phase: 'Plan ready to review',
  },
];

export const workSources = [
  ['Q3 customer interviews', '12 transcripts', 'Synced 4 min ago'],
  ['Product analytics snapshot', '28 charts', 'Synced 7 min ago'],
  ['Market landscape', '9 web sources', 'Verified today'],
  ['FY26 company priorities', '1 document', 'Private workspace'],
];

export const codeChanges = [
  ['src/pipeline/runner.py', '+42', '−18'],
  ['src/tests/test_pipeline.py', '+61', '−7'],
  ['src/fixtures/shared.py', '+18', '−4'],
  ['docs/testing.md', '+17', '—'],
];
