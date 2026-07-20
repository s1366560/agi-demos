import '@radix-ui/themes/styles.css';
import React, { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';

import { DesktopApiError } from '../api/client';
import { AutomationsPage } from '../features/automations/AutomationsPage';
import { I18nProvider } from '../i18n';
import type { AutomationCapabilities, AutomationJob, AutomationRun } from '../types';
import '../styles.css';
import './automationsQa.css';

declare global {
  var __automationsQaRoot: Root | undefined;
}

type QaState = 'populated' | 'empty' | 'unavailable' | 'permission' | 'error';

function readOnlyCapabilities(reasonCode: string): AutomationCapabilities {
  const unavailable = { allowed: false, reason_code: reasonCode };
  return {
    schema_version: 1,
    read: true,
    revision_guarded: false,
    idempotency_guarded: false,
    durable_execution: false,
    supported_read_trigger_kinds: ['manual', 'schedule', 'event'],
    create: unavailable,
    edit: unavailable,
    toggle: unavailable,
    run_now: unavailable,
    delete: unavailable,
  };
}

function guardedCapabilities(): AutomationCapabilities {
  return {
    schema_version: 1,
    read: true,
    revision_guarded: true,
    idempotency_guarded: true,
    durable_execution: false,
    supported_read_trigger_kinds: ['manual', 'schedule', 'event'],
    create: { allowed: true },
    edit: { allowed: true },
    toggle: { allowed: true },
    run_now: {
      allowed: false,
      reason_code: 'durable_automation_execution_unavailable',
    },
    delete: { allowed: true },
  };
}

const jobs: AutomationJob[] = [
  {
    id: 'automation-nightly-review',
    project_id: 'local-project',
    tenant_id: 'northstar',
    name: 'Nightly codebase review',
    description: 'Review changed modules and prepare a concise engineering brief.',
    enabled: true,
    delete_after_run: false,
    revision: 7,
    schedule_revision: 3,
    trigger: {
      kind: 'schedule',
      schedule: { kind: 'cron', config: { expr: '0 2 * * *' } },
    },
    schedule: { kind: 'cron', config: { expr: '0 2 * * *' } },
    payload: { kind: 'agent_turn', config: {} },
    delivery: { kind: 'announce', config: {} },
    conversation_mode: 'reuse',
    conversation_id: 'conversation-nightly-review',
    timezone: 'Asia/Shanghai',
    stagger_seconds: 0,
    timeout_seconds: 900,
    max_retries: 3,
    state: {
      last_run_at: '2026-07-13T02:00:00+08:00',
      last_run_status: 'success',
      next_run_at: '2026-07-14T02:00:00+08:00',
      environment_id: 'worktree-nightly-review',
      permission_profile: 'workspace_write',
    },
    created_at: '2026-07-01T10:00:00Z',
  },
  {
    id: 'automation-deploy-check',
    project_id: 'local-project',
    tenant_id: 'northstar',
    name: 'Deploy compliance check',
    description: 'Inspect release evidence when a deployment event arrives.',
    enabled: false,
    delete_after_run: false,
    revision: 4,
    schedule_revision: 2,
    trigger: { kind: 'event', source_id: 'deployment-events', event_type: 'deployment.ready' },
    schedule: { kind: 'event', config: { event_name: 'deployment.ready' } },
    payload: { kind: 'agent_turn', config: {} },
    delivery: { kind: 'announce', config: {} },
    conversation_mode: 'fresh',
    timezone: 'UTC',
    stagger_seconds: 0,
    timeout_seconds: 600,
    max_retries: 2,
    state: {},
    created_at: '2026-07-08T08:00:00Z',
  },
  {
    id: 'automation-release-brief',
    project_id: 'local-project',
    tenant_id: 'northstar',
    name: 'Release brief',
    description: 'Prepare a manual release summary from current project evidence.',
    enabled: true,
    delete_after_run: false,
    revision: 1,
    schedule_revision: 1,
    trigger: { kind: 'manual' },
    schedule: { kind: 'manual', config: {} },
    payload: { kind: 'agent_turn', config: {} },
    delivery: { kind: 'none', config: {} },
    conversation_mode: 'fresh',
    timezone: 'UTC',
    stagger_seconds: 0,
    timeout_seconds: 300,
    max_retries: 1,
    state: {},
    created_at: '2026-07-10T08:00:00Z',
  },
];

const runs: AutomationRun[] = [
  {
    id: 'automation-run-42',
    job_id: 'automation-nightly-review',
    project_id: 'local-project',
    status: 'success',
    trigger_type: 'scheduled',
    started_at: '2026-07-13T02:00:00+08:00',
    finished_at: '2026-07-13T02:01:24+08:00',
    duration_ms: 84000,
    result_summary: {},
    conversation_id: 'conversation-nightly-review',
  },
  {
    id: 'automation-run-41',
    job_id: 'automation-nightly-review',
    project_id: 'local-project',
    status: 'failed',
    trigger_type: 'scheduled',
    started_at: '2026-07-12T02:00:00+08:00',
    finished_at: '2026-07-12T02:00:12+08:00',
    duration_ms: 12000,
    error_message: 'Run authority expired before delivery.',
    result_summary: {},
    conversation_id: 'conversation-nightly-review',
  },
];

function AutomationsQa() {
  const [state, setState] = useState<QaState>('populated');
  const api = useMemo(
    () => ({
      async listAutomations() {
        if (state === 'unavailable') {
          throw new DesktopApiError('Not found', 404, { detail: 'Not found' });
        }
        return { items: state === 'empty' ? [] : jobs, total: state === 'empty' ? 0 : jobs.length };
      },
      async getAutomationCapabilities() {
        if (state === 'error') {
          throw new DesktopApiError('Service unavailable', 503, {
            detail: 'Service unavailable',
          });
        }
        return state === 'permission'
          ? readOnlyCapabilities('project_write_required')
          : guardedCapabilities();
      },
      async createAutomation(input: { name: string }) {
        return { ...jobs[0]!, id: 'automation-created', name: input.name, revision: 1 };
      },
      async updateAutomation(_automationId: string, input: { name?: string }) {
        return { ...jobs[0]!, name: input.name ?? jobs[0]!.name, revision: 8 };
      },
      async toggleAutomation(_automationId: string, input: { enabled: boolean }) {
        return { ...jobs[0]!, enabled: input.enabled, revision: 8 };
      },
      async deleteAutomation() {},
      async listAutomationRuns(automationId: string) {
        return { items: runs.filter((run) => run.job_id === automationId), total: runs.length };
      },
    }),
    [state],
  );
  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="automations-qa-shell">
        <nav aria-label="Automation QA states">
          {(['populated', 'empty', 'unavailable', 'permission', 'error'] as QaState[]).map(
            (nextState) => (
              <button
                type="button"
                className={state === nextState ? 'selected' : ''}
                onClick={() => setState(nextState)}
                key={nextState}
              >
                {nextState}
              </button>
            ),
          )}
        </nav>
        <AutomationsPage
          key={state}
          api={api}
          projectId="local-project"
          projectName="Desktop Client"
          onOpenProjectSettings={() => {}}
          onOpenConnection={() => {}}
        />
      </div>
    </Theme>
  );
}

const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__automationsQaRoot ??= createRoot(container);
globalThis.__automationsQaRoot.render(
  <I18nProvider>
    <AutomationsQa />
  </I18nProvider>,
);
