import { useState } from 'react';
import { Button, Flex, Text, TextArea } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type {
  AgentTimelineItem,
  DesktopApprovalRequest,
  HitlResponseSubmission,
  HitlType,
} from '../../types';
import {
  approvalResponseSubmission,
  validateApprovalRequest,
} from '../session/sessionDecisionModel';
import type { A2UIActionView } from './a2uiAction';
import {
  booleanPayloadField,
  timelineHitlFields,
  timelineHitlOptions,
  timelineHitlQuestion,
  timelineHitlRequestId,
} from './chatTimelinePresentation';

export function HitlResponseCard({
  item,
  hitlType,
  onRespond,
  canRespond,
  a2uiActionView,
  approvalRequest,
}: {
  item: AgentTimelineItem;
  hitlType: HitlType;
  onRespond: (submission: HitlResponseSubmission) => Promise<void>;
  canRespond: boolean;
  a2uiActionView?: A2UIActionView;
  approvalRequest?: DesktopApprovalRequest;
}) {
  const { t } = useI18n();
  const [answer, setAnswer] = useState('');
  const [envValues, setEnvValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const requestId = timelineHitlRequestId(item);
  const options = timelineHitlOptions(item);
  const fields = timelineHitlFields(item);
  const answered = Boolean(item.answered) || submitted;
  const authorityDisabled = !answered && !canRespond;
  const allowCustom =
    item.allowCustom ?? booleanPayloadField(item, 'allow_custom') ?? options.length === 0;
  const question = timelineHitlQuestion(item, t);
  const approvalValidation = approvalRequest ? validateApprovalRequest(approvalRequest) : null;

  const submit = async (responseData: Record<string, unknown>) => {
    if (!requestId || answered || busy || authorityDisabled) return;
    setBusy(true);
    setSubmitError(null);
    try {
      const expectedRevision = approvalRequest?.run_revision;
      await onRespond({
        requestId,
        hitlType,
        responseData,
        ...(typeof expectedRevision === 'number' ? { expectedRevision } : {}),
        idempotencyKey: [requestId, expectedRevision ?? 'unversioned', hitlType].join(':'),
      });
      setSubmitted(true);
    } catch (caught) {
      setSubmitError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const submitApproval = async (action: 'approve' | 'request_changes') => {
    if (!approvalRequest || answered || busy || authorityDisabled) return;
    setBusy(true);
    setSubmitError(null);
    try {
      await onRespond(approvalResponseSubmission(approvalRequest, action));
      setSubmitted(true);
    } catch (caught) {
      setSubmitError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="timeline-details">
      <Text as="p" size="2" className="timeline-detail-summary">
        {question}
      </Text>
      <div className="agent-run-meta">
        <span>{t(answered ? 'chat.status.answered' : 'chat.status.waitingForInput')}</span>
        {requestId ? <span>{requestId}</span> : <span>{t('chat.missingRequestId')}</span>}
      </div>

      {authorityDisabled ? (
        <Text size="1" color="amber">
          {t('session.authorityActionUnavailable')}
        </Text>
      ) : null}

      {approvalRequest?.decision ? (
        <div className="timeline-approval-evidence">
          <div>
            <span>{t('approval.action')}</span>
            <strong>{approvalRequest.decision.action.label}</strong>
          </div>
          <div>
            <span>{t('approval.target')}</span>
            <strong>
              {approvalRequest.decision.target.kind} · {approvalRequest.decision.target.id}
            </strong>
          </div>
          <div>
            <span>{t('approval.agentRisk')}</span>
            <strong>{approvalRequest.decision.risk.level}</strong>
          </div>
          <div>
            <span>{t('approval.scope')}</span>
            <strong>
              {approvalRequest.decision.scope.kind} ·{' '}
              {approvalRequest.decision.scope.ids.join(', ')}
            </strong>
          </div>
          <p>{approvalRequest.decision.reason}</p>
          <small>
            {t('approval.requestIdentity', {
              requestId: approvalRequest.id,
              revision: approvalRequest.run_revision ?? '—',
            })}
          </small>
        </div>
      ) : approvalRequest?.permission ? (
        <div className="timeline-approval-evidence">
          <div>
            <span>{t('approval.action')}</span>
            <strong>{approvalRequest.permission.action}</strong>
          </div>
          <div>
            <span>{t('approval.target')}</span>
            <strong>{approvalRequest.permission.tool_name}</strong>
          </div>
          <div>
            <span>{t('approval.agentRisk')}</span>
            <strong>{approvalRequest.permission.risk_level}</strong>
          </div>
          <p>{approvalRequest.permission.description}</p>
          <small>
            {t('approval.requestIdentity', {
              requestId: approvalRequest.id,
              revision: approvalRequest.run_revision ?? '—',
            })}
          </small>
        </div>
      ) : !answered && (hitlType === 'permission' || hitlType === 'decision') ? (
        <Text size="1" color="red">
          {t('approval.incomplete', {
            fields: 'action, target, data, reason, risk, reversibility, scope, evidence',
          })}
        </Text>
      ) : null}

      {!answered && hitlType === 'permission' ? (
        <Flex gap="2" wrap="wrap">
          <Button
            size="1"
            color="green"
            disabled={authorityDisabled || !requestId || busy || !approvalValidation?.canApprove}
            loading={busy}
            onClick={() => void submitApproval('approve')}
          >
            {t('chat.allowOnce')}
          </Button>
          <Button
            size="1"
            color="red"
            variant="soft"
            disabled={authorityDisabled || !requestId || busy}
            onClick={() =>
              void (approvalRequest
                ? submitApproval('request_changes')
                : submit({ granted: false, action: 'deny' }))
            }
          >
            {t('chat.deny')}
          </Button>
        </Flex>
      ) : null}

      {!answered && hitlType === 'env_var' ? (
        <div className="timeline-detail-block">
          <span>{t('chat.environmentValues')}</span>
          {fields.map((field) => (
            <label key={field.name}>
              <span>{field.label}</span>
              <input
                type="password"
                autoComplete="off"
                disabled={authorityDisabled || busy}
                required={field.required}
                value={envValues[field.name] ?? ''}
                onChange={(event) =>
                  setEnvValues((current) => ({
                    ...current,
                    [field.name]: event.currentTarget.value,
                  }))
                }
              />
            </label>
          ))}
          <Button
            size="1"
            disabled={
              !requestId ||
              authorityDisabled ||
              busy ||
              fields.length === 0 ||
              fields.some((field) => field.required && !envValues[field.name]?.trim())
            }
            loading={busy}
            onClick={() => void submit({ values: envValues })}
          >
            {t('chat.submitSecurely')}
          </Button>
        </div>
      ) : null}

      {!answered && (hitlType === 'clarification' || hitlType === 'decision') ? (
        <div className="timeline-detail-block">
          {options.length ? (
            <Flex gap="2" wrap="wrap">
              {options.map((option) => (
                <Button
                  size="1"
                  variant="soft"
                  disabled={authorityDisabled || !requestId || busy}
                  title={option.description}
                  key={option.value}
                  onClick={() =>
                    void submit(
                      hitlType === 'clarification'
                        ? { answer: option.value }
                        : { decision: option.value },
                    )
                  }
                >
                  {option.label}
                </Button>
              ))}
            </Flex>
          ) : null}
          {allowCustom ? (
            <>
              <TextArea
                size="1"
                value={answer}
                disabled={authorityDisabled || busy}
                placeholder={t(
                  hitlType === 'decision' ? 'chat.enterDecision' : 'chat.enterAnswer',
                )}
                onChange={(event) => setAnswer(event.currentTarget.value)}
              />
              <Button
                size="1"
                disabled={authorityDisabled || !requestId || busy || !answer.trim()}
                loading={busy}
                onClick={() =>
                  void submit(
                    hitlType === 'clarification'
                      ? { answer: answer.trim() }
                      : { decision: answer.trim() },
                  )
                }
              >
                {t('chat.submitResponse')}
              </Button>
            </>
          ) : null}
        </div>
      ) : null}

      {!answered && hitlType === 'a2ui_action' ? (
        a2uiActionView?.actions.length ? (
          <Flex gap="2" wrap="wrap">
            {a2uiActionView.actions.map((action) => (
              <Button
                size="1"
                variant="soft"
                disabled={authorityDisabled || !requestId || busy}
                loading={busy}
                key={`${action.sourceComponentId}:${action.actionName}`}
                onClick={() =>
                  void submit({
                    action_name: action.actionName,
                    source_component_id: action.sourceComponentId,
                    context: {},
                  })
                }
              >
                {action.label}
              </Button>
            ))}
          </Flex>
        ) : (
          <Text size="1" color="amber">
            {a2uiActionView?.reason ?? t('chat.a2uiOriginalSurfaceRequired')}{' '}
            {t('chat.openWebClientToRespond')}
          </Text>
        )
      ) : null}

      {submitError ? (
        <Text size="1" color="red" role="alert">
          {submitError}
        </Text>
      ) : null}
    </div>
  );
}
