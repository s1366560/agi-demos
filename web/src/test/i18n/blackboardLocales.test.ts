import { describe, expect, it } from 'vitest';

import enUS from '@/locales/en-US.json';
import zhCN from '@/locales/zh-CN.json';

const BLACKBOARD_PRODUCT_KEYS = [
  'blackboard.title',
  'blackboard.shellHint',
  'blackboard.shellSensingHint',
  'blackboard.tabs.goals',
  'blackboard.tabGroups.work',
  'blackboard.autonomy.title',
  'blackboard.autonomy.run',
  'blackboard.autonomy.success',
  'blackboard.executionFeedback.title',
  'blackboard.executionFeedback.stage.waitingRoot',
  'blackboard.executionFeedback.helper.running',
  'blackboard.executionFeedback.eventLogTitle',
  'blackboard.executionFeedback.controls.copySnapshot',
  'workspaceDetail.taskBoard.forceAutonomy',
  'workspaceDetail.taskBoard.forceAutonomySuccess',
  'workspaceDetail.taskBoard.forceAutonomyFailed',
  'blackboard.discussionPosts',
  'blackboard.createPost',
  'blackboard.backToList',
  'blackboard.pin',
  'blackboard.unpin',
  'blackboard.date',
  'blackboard.unknownAuthor',
  'blackboard.statusOverviewTitle',
  'blackboard.planRunPlanNext',
  'blackboard.planRunPlanNextManual',
  'blackboard.planRunPlanNextManualHint',
  'blackboard.planRunIterationLimitHint',
  'blackboard.iterationLedgerTitle',
  'blackboard.iterationLedgerDescription',
  'blackboard.iterationTasksTitle',
  'blackboard.iterationOutputsTitle',
  'blackboard.iterationActivityTitle',
  'blackboard.iterationOpenTask',
  'blackboard.iterationPhaseResearch',
  'blackboard.iterationPhasePlan',
  'blackboard.iterationPhaseImplement',
  'blackboard.iterationPhaseTest',
  'blackboard.iterationPhaseDeploy',
  'blackboard.iterationPhaseReview',
  'blackboard.iterationActivityWorker',
  'blackboard.iterationActivityVerifier',
  'blackboard.iterationActivitySupervisor',
  'blackboard.iterationActivityOperator',
  'blackboard.iterationActivityRetry',
  'blackboard.iterationActivityFailed',
  'blackboard.executionDiagnosticsTitle',
  'blackboard.executionDiagnosticsEmpty',
  'blackboard.executionDiagnosticsNoBlockers',
  'blackboard.pendingAdjudicationTitle',
  'blackboard.pendingAdjudicationEmpty',
] as const;

function readLocaleValue(locale: Record<string, unknown>, key: string): unknown {
  return key.split('.').reduce<unknown>((current, segment) => {
    if (current && typeof current === 'object' && segment in current) {
      return (current as Record<string, unknown>)[segment];
    }
    return undefined;
  }, locale);
}

describe('Blackboard locale coverage', () => {
  it.each([
    ['en-US', enUS],
    ['zh-CN', zhCN],
  ])('covers product chrome and diagnostics for %s', (_name, locale) => {
    for (const key of BLACKBOARD_PRODUCT_KEYS) {
      const value = readLocaleValue(locale, key);
      expect(value, key).toEqual(expect.any(String));
      expect(value, key).not.toBe(key);
      expect(String(value).trim(), key).not.toHaveLength(0);
    }
  });
});
