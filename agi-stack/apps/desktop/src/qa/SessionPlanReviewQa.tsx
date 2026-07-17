import '@radix-ui/themes/styles.css';
import { Theme } from '@radix-ui/themes';
import React from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { SessionPlanReview } from '../features/session/SessionPlanReview';
import { I18nProvider, useI18n } from '../i18n';
import type {
  SessionProjectionCapabilities,
  SessionProjectionPlan,
} from '../features/session/sessionProjectionTypes';
import '../styles.css';

declare global {
  var __sessionPlanReviewQaRoot: Root | undefined;
}

const tasks = [
  {
    id: 'plan-task-1',
    content: '核对会话投影与当前计划版本的权威边界',
    status: 'pending',
    priority: 'high',
  },
  {
    id: 'plan-task-2',
    content: '实现可恢复的人工计划审查与批准入口',
    status: 'pending',
    priority: 'high',
  },
  {
    id: 'plan-task-3',
    content: '将执行环境、权限配置与幂等审批请求绑定',
    status: 'pending',
    priority: 'medium',
  },
  {
    id: 'plan-task-4',
    content: '批准后刷新会话投影并打开对应运行',
    status: 'pending',
    priority: 'medium',
  },
];

function SessionPlanReviewQa() {
  const { t } = useI18n();
  const params = new URLSearchParams(window.location.search);
  const approved = params.get('state') === 'approved';
  const readonly = params.get('authority') === 'readonly';
  const canApprove = !approved && !readonly;
  const plan: SessionProjectionPlan = {
    id: 'plan-version-desktop-session-v7',
    conversation_id: 'conversation-desktop-session',
    version: 7,
    status: approved ? 'approved' : 'draft',
    tasks,
    created_at: '2026-07-16T09:12:00Z',
    approved_at: approved ? '2026-07-16T09:18:00Z' : null,
  };
  const capabilities: SessionProjectionCapabilities = {
    canSendMessage: !approved,
    canApprovePlan: canApprove,
    canRespondToHitl: false,
    canSteerNow: false,
    canQueueNext: false,
    canReviewArtifacts: false,
    canDeliverArtifacts: false,
    runActions: [],
    allowedActions: [
      ...(!approved ? (['send_message'] as const) : []),
      ...(canApprove ? (['approve_plan_and_start'] as const) : []),
    ],
  };

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <main
        style={{
          boxSizing: 'border-box',
          display: 'grid',
          width: '100%',
          minHeight: '100%',
          padding: 36,
          placeItems: 'center',
          background: '#080c12',
        }}
      >
        <aside
          className="review-panel review-panel-session"
          aria-label={t('session.canvas')}
          style={{
            width: 'min(680px, 100%)',
            height: 'min(820px, calc(100vh - 72px))',
            border: '1px solid var(--desktop-border)',
            borderRadius: 7,
          }}
        >
          <div className="review-tabs" aria-label={t('session.canvas')}>
            <nav className="review-tab-scroll">
              <button className="review-tab selected" type="button">
                <span>{t('session.canvasPlan')}</span>
                <em>versioned_atomic · v{plan.version}</em>
              </button>
            </nav>
          </div>
          <div className="review-content">
            <div className="review-plan">
              <SessionPlanReview
                plan={plan}
                capabilities={capabilities}
                capabilityMode="code"
                pending={false}
                onApprove={async () => undefined}
              />
            </div>
          </div>
        </aside>
      </main>
    </Theme>
  );
}

try {
  window.localStorage.setItem('agistack.desktop.locale', 'zh-CN');
} catch {
  // The QA fixture still renders with the in-memory default when storage is unavailable.
}
document.documentElement.lang = 'zh-CN';

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root container');

const qaRoot = globalThis.__sessionPlanReviewQaRoot ?? createRoot(root);
globalThis.__sessionPlanReviewQaRoot = qaRoot;

qaRoot.render(
  <React.StrictMode>
    <I18nProvider>
      <SessionPlanReviewQa />
    </I18nProvider>
  </React.StrictMode>,
);
