import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const flowStyles = readFileSync(
  new URL('../src/features/task/NewTaskFlow.css', import.meta.url),
  'utf8',
);
const reviewStyles = readFileSync(
  new URL('../src/features/task/NewTaskPlanReview.css', import.meta.url),
  'utf8',
);
const stagesSource = readFileSync(
  new URL('../src/features/task/NewTaskFlowStages.tsx', import.meta.url),
  'utf8',
);
const qaSource = readFileSync(new URL('../src/qa/NewTaskFlowQa.tsx', import.meta.url), 'utf8');

test('new task shell preserves the prototype header and define-stage proportions', () => {
  assert.match(
    flowStyles,
    /\.new-task-header\s*\{[\s\S]*?grid-template-columns:\s*220px minmax\(0, 1fr\) 40px;/,
  );
  assert.match(
    flowStyles,
    /\.new-task-define\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1\.55fr\) minmax\(320px, 0\.85fr\);/,
  );
  assert.match(
    flowStyles,
    /\.new-task-primary-column,[\s\S]*?padding:\s*38px clamp\(40px, 7vw, 96px\);/,
  );
});

test('planning stage preserves prototype geometry and a distinct code identity', () => {
  assert.match(
    flowStyles,
    /\.new-task-planning\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1\.4fr\) minmax\(300px, 0\.6fr\);/,
  );
  assert.match(flowStyles, /\.new-task-planning-main h2\s*\{[\s\S]*?font-size:\s*25px;/);
  assert.match(flowStyles, /\.new-task-planning-icon\.code\s*\{/);
  assert.match(
    stagesSource,
    /className=\{`new-task-planning-icon \$\{kind === 'programming' \? 'code' : 'work'\}`\}/,
  );
  assert.match(
    stagesSource,
    /className="new-task-planning-progress"[\s\S]*?role="progressbar"[\s\S]*?aria-valuetext=/,
  );
  const definitionStage =
    stagesSource.match(
      /export function NewTaskDefinitionStage\([\s\S]*?\n}\n\ntype PlanningStageProps/,
    )?.[0] ?? '';
  assert.doesNotMatch(definitionStage, /new-task-code-boundary|task\.codeRoot|EnvironmentButton/);
});

test('human plan review retains the prototype split and step rhythm', () => {
  assert.match(
    reviewStyles,
    /\.new-task-review\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1\.5fr\) minmax\(320px, 0\.62fr\);/,
  );
  assert.match(
    reviewStyles,
    /\.new-task-plan-step\s*\{[\s\S]*?min-height:\s*74px;[\s\S]*?grid-template-columns:\s*20px 28px minmax\(0, 1fr\) 46px 28px;/,
  );
  assert.match(
    reviewStyles,
    /\.new-task-review-heading h2:focus\s*\{[\s\S]*?outline:\s*none;/,
  );
  assert.match(
    reviewStyles,
    /\.new-task-review-heading h2\[data-keyboard-focus='true'\]:focus\s*\{[\s\S]*?outline:\s*2px solid #55d8f7;/,
  );
});

test('QA route exercises and diagnoses the production task authority boundary', () => {
  assert.match(qaSource, /workspaceAuthority=\{\{ status: 'ready', items: \[\], error: null \}\}/);
  assert.match(
    qaSource,
    /url\.pathname ===[\s\S]*?\/api\/v1\/tenants\/northstar\/projects\/product-strategy\/task-sessions[\s\S]*?method === 'POST'/,
  );
  assert.match(qaSource, /taskSessionPostCount !== 1/);
  assert.match(qaSource, /qaSessionPersisted/);
  assert.match(qaSource, /qaSessionReady/);
  assert.match(qaSource, /qaAgentTurns/);
  assert.match(qaSource, /\/api\/v1\/agent\/plans\/approve-and-start/);
  assert.match(qaSource, /qaApprovalPosts/);
  assert.match(qaSource, /qaContractErrors/);
});
