import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';

// P2-5 render performance budget (docs/render-performance-budget.md).
// Generalizes the P1-4 SessionChangesCanvas source pin into a standing budget:
// heavy render surfaces stay event-driven so the diff view cannot regress into
// a Codex #15330-style idle CPU burn (200%+ while idling).

const desktopRoot = new URL('..', import.meta.url);

function readSource(relativePath) {
  return readFileSync(new URL(relativePath, desktopRoot), 'utf8');
}

function countOccurrences(source, pattern) {
  return (source.match(pattern) ?? []).length;
}

// Tier 1 — zero tolerance: diff-view and canvas surfaces must contain no
// timers or rAF at all. Any repaint here is event-driven from props/state.
const ZERO_TIMER_FILES = [
  'src/features/session/SessionChangesCanvas.tsx',
  'src/features/session/sessionChangesModel.ts',
  'src/features/session/sessionChangesReviewModel.ts',
  'src/features/session/SessionTerminalCanvas.tsx',
  'src/features/chat/LiveArtifactCanvas.tsx',
];

// Tier 2 — recurring-timer whitelist: setInterval is the idle-CPU risk, so its
// occurrences must exactly match the whitelisted entries below (one comment
// per exception). One-shot setTimeout/rAF triggered by user input or socket
// events (focus restore, scroll anchoring, 16ms event batching) is allowed and
// documented in docs/render-performance-budget.md; self-rescheduling loops are
// not.
const INTERVAL_WHITELIST = [
  {
    file: 'src/features/chat/CurrentActivityHeadline.tsx',
    count: 1,
    // 1s elapsed-clock tick; the bar only mounts while a run is live, so the
    // interval never fires on an idle session.
  },
  {
    file: 'src/features/chat/ChatTimeline.tsx',
    count: 1,
    // TimelineWorkingRow 1s tick; rendered only while the agent-working
    // indicator is visible (startedAtUs truthy), cleared otherwise.
  },
  {
    file: 'src/features/chat/HitlResponseCard.tsx',
    count: 1,
    // 1s expiry countdown; gated to unanswered + active requests only.
  },
  {
    file: 'src/features/chat/VoiceCallPanel.tsx',
    count: 1,
    // 1s call-duration tick; the panel only exists during an active call.
  },
  {
    file: 'src/features/chat/ChatPanel.tsx',
    count: 0,
    // No recurring timers allowed in the timeline panel; scroll/focus restore
    // uses one-shot rAF only.
  },
  {
    file: 'src/features/sandbox/InteractiveTerminal.tsx',
    count: 0,
    // xterm internals are exempt by design; the wrapper itself must stay
    // timer-free (single mount-time fit rAF is one-shot).
  },
  {
    file: 'src/hooks/useAgentSocket.ts',
    count: 2,
    // WebSocket heartbeat + watchdog: connection keepalive, a network-layer
    // structural fact that does not drive rendering; cleared on close.
  },
  {
    file: 'src/hooks/useTerminalProxy.ts',
    count: 0,
    // Terminal proxy batches output with one-shot rAF/timeout flush only.
  },
];

test('zero-timer render surfaces contain no setInterval/setTimeout/requestAnimationFrame', () => {
  for (const file of ZERO_TIMER_FILES) {
    const source = readSource(file);
    assert.doesNotMatch(source, /setInterval\(/, `${file} must not use setInterval`);
    assert.doesNotMatch(source, /setTimeout\(/, `${file} must not use setTimeout`);
    assert.doesNotMatch(
      source,
      /requestAnimationFrame\(/,
      `${file} must not use requestAnimationFrame`,
    );
  }
});

test('recurring timers outside the zero-timer set match the explicit whitelist', () => {
  const whitelistedFiles = new Set(INTERVAL_WHITELIST.map((entry) => entry.file));
  for (const entry of INTERVAL_WHITELIST) {
    const source = readSource(entry.file);
    const actual = countOccurrences(source, /setInterval\(/g);
    assert.equal(
      actual,
      entry.count,
      `${entry.file} has ${actual} setInterval occurrence(s), whitelist expects ${entry.count}; ` +
        'update the whitelist with a justification comment or remove the new timer',
    );
  }
  // Guard the inverse direction: no whitelisted file may silently drop its
  // timer (dead whitelist entries hide regressions in the gating logic).
  for (const file of whitelistedFiles) {
    assert.ok(file.startsWith('src/'), `${file} must be a src-relative path`);
  }
});

test('diff view CSS stays free of animation sources (P1-4 red line)', () => {
  const cssSource = readSource('src/features/session/SessionChangesCanvas.css');
  assert.doesNotMatch(cssSource, /@keyframes/);
  assert.doesNotMatch(cssSource, /animation[^-]/);
  assert.doesNotMatch(cssSource, /infinite/);
});

function listCssFiles(directory) {
  const entries = readdirSync(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...listCssFiles(path));
    } else if (entry.isFile() && entry.name.endsWith('.css')) {
      files.push(path);
    }
  }
  return files;
}

test('every CSS file with @keyframes gates infinite motion behind prefers-reduced-motion', () => {
  const srcRoot = new URL('src/', desktopRoot);
  const cssFiles = listCssFiles(srcRoot.pathname);
  assert.ok(cssFiles.length > 0, 'expected to discover CSS files under src/');
  const offenders = [];
  for (const path of cssFiles) {
    const source = readFileSync(path, 'utf8');
    if (source.includes('@keyframes') && !source.includes('prefers-reduced-motion')) {
      offenders.push(path.replace(srcRoot.pathname, 'src/'));
    }
  }
  assert.deepEqual(
    offenders,
    [],
    'CSS files with @keyframes must include a prefers-reduced-motion guard in the same file',
  );
});

test('chrome CSS does not transition layout-triggering properties', () => {
  // Always-mounted chrome (sidebar/header shell) must not animate layout
  // properties; confined exceptions (2px in-track progress bars, the settings
  // toggle thumb) are documented in docs/render-performance-budget.md.
  const stylesDirectory = new URL('src/styles/', desktopRoot);
  const chromeCss = readdirSync(stylesDirectory)
    .filter((entry) => entry.endsWith('.css'))
    .map((entry) => readFileSync(new URL(entry, stylesDirectory), 'utf8'))
    .join('\n');
  const layoutTransitions = chromeCss.match(
    /transition[^;]*\b(width|height|top|left|right|bottom|margin|padding)\b[^;]*;/g,
  );
  assert.deepEqual(
    layoutTransitions ?? [],
    [],
    'src/styles/*.css chrome must not transition layout-triggering properties',
  );
});
