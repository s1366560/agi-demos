import { useEffect, useState } from 'react';
import { ChevronDownIcon, ChevronRightIcon } from '@radix-ui/react-icons';
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
  browserCapabilityConsentView,
  browserCredentialFillAllowResponseData,
  browserFullCdpAllowResponseData,
  browserOriginAllowResponseData,
  browserOriginConsentView,
  buildDecisionResponse,
  buildEnvVarResponse,
  formatHitlRemaining,
  hitlDecisionView,
  hitlEnvVarView,
  hitlRequestExpiry,
  permissionParameterPreview,
  toggleDecisionSelection,
} from './hitlResponseCardModel';
import { hitlResponsePresentation } from './hitlResponseEventModel';
import { permissionDenialResponseData } from './permissionPresetModel';
import {
  booleanPayloadField,
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
  const decisionView = hitlDecisionView(item);
  const envVarView = hitlEnvVarView(item);
  const [answer, setAnswer] = useState('');
  const [envValues, setEnvValues] = useState<Record<string, string>>({});
  const [decisionSelections, setDecisionSelections] = useState<string[]>(() =>
    decisionView.defaultOption ? [decisionView.defaultOption] : [],
  );
  const [customDecisionSelected, setCustomDecisionSelected] = useState(
    () =>
      decisionView.selectionMode === 'single' &&
      decisionView.allowCustom &&
      !decisionView.defaultOption &&
      decisionView.options.length === 0,
  );
  const [saveEnvironmentValues, setSaveEnvironmentValues] = useState(false);
  const [denyFeedbackOpen, setDenyFeedbackOpen] = useState(false);
  const [denyFeedback, setDenyFeedback] = useState('');
  const [detailsExpanded, setDetailsExpanded] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const requestId = timelineHitlRequestId(item);
  const options = timelineHitlOptions(item);
  const answered = Boolean(item.answered);
  const expiry = hitlRequestExpiry(item, approvalRequest, nowMs);
  const authorityDisabled = !answered && !canRespond;
  const responseDisabled = !answered && (!canRespond || !expiry.canRespond);
  const allowCustom =
    hitlType === 'decision'
      ? decisionView.allowCustom
      : item.allowCustom ?? booleanPayloadField(item, 'allow_custom') ?? options.length === 0;
  const question = timelineHitlQuestion(item, t);
  const approvalValidation = approvalRequest ? validateApprovalRequest(approvalRequest) : null;
  const responsePresentation = hitlResponsePresentation(item, hitlType);
  const parameterPreview =
    hitlType === 'permission' ? permissionParameterPreview(item) : null;
  const browserOrigin =
    hitlType === 'permission' ? browserOriginConsentView(item, approvalRequest) : null;
  const browserCapability =
    hitlType === 'permission' ? browserCapabilityConsentView(item, approvalRequest) : null;
  const browserConsentTitle = browserOrigin
    ? t('chat.browserOrigin.title', { origin: browserOrigin.origin })
    : browserCapability?.kind === 'browser_full_cdp'
      ? t('chat.browserFullCdp.title', { origin: browserCapability.origin })
      : browserCapability?.kind === 'browser_credential_fill'
        ? t('chat.browserCredentialFill.title', { origin: browserCapability.origin })
        : null;

  useEffect(() => {
    if (answered || expiry.state !== 'active') return;
    const timer = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [answered, expiry.expiresAt, expiry.state]);

  const submit = async (responseData: Record<string, unknown>) => {
    if (!requestId || answered || busy || responseDisabled) return;
    setBusy(true);
    setSubmitError(null);
    try {
      const expectedRevision = approvalRequest?.authority_revision;
      await onRespond({
        requestId,
        hitlType,
        responseData,
        ...(typeof expectedRevision === 'number' ? { expectedRevision } : {}),
        idempotencyKey: [requestId, expectedRevision ?? 'unversioned', hitlType].join(':'),
      });
    } catch (caught) {
      setSubmitError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  const submitApproval = async (action: 'approve' | 'request_changes') => {
    if (!approvalRequest || answered || busy || responseDisabled) return;
    setBusy(true);
    setSubmitError(null);
    try {
      await onRespond(approvalResponseSubmission(approvalRequest, action));
    } catch (caught) {
      setSubmitError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="timeline-details">
      <Text as="p" size="2" className="timeline-detail-summary">
        {browserConsentTitle ?? question}
      </Text>
      {browserOrigin ? (
        <div className="agent-run-meta">
          {browserOrigin.tool ? (
            <span>{t('chat.browserOrigin.toolRequest', { tool: browserOrigin.tool })}</span>
          ) : null}
          {browserOrigin.reason ? <span>{browserOrigin.reason}</span> : null}
        </div>
      ) : null}
      {browserCapability ? (
        <div className="agent-run-meta">
          {browserCapability.tool ? (
            <span>
              {t('chat.browserOrigin.toolRequest', { tool: browserCapability.tool })}
            </span>
          ) : null}
          {browserCapability.reason ? <span>{browserCapability.reason}</span> : null}
          {browserCapability.kind === 'browser_credential_fill' ? (
            <span>{t('chat.browserCredentialFill.description')}</span>
          ) : null}
        </div>
      ) : null}
      <div className="agent-run-meta">
        <span>
          {t(
            answered
              ? 'chat.status.answered'
              : expiry.state === 'expired'
                ? 'chat.requestExpired'
                : expiry.state === 'invalid'
                  ? 'chat.invalidExpiry'
                  : 'chat.status.waitingForInput',
          )}
        </span>
        {requestId ? <span>{requestId}</span> : <span>{t('chat.missingRequestId')}</span>}
        {expiry.state === 'active' ? (
          <span>
            {t('chat.expiresIn', {
              time: formatHitlRemaining(expiry.remainingSeconds),
            })}
          </span>
        ) : null}
      </div>

      {responsePresentation ? (
        <div className="timeline-hitl-response" role="status" aria-readonly="true">
          <span>{t(responsePresentation.labelKey)}</span>
          <strong>
            {responsePresentation.valueKey
              ? t(responsePresentation.valueKey)
              : responsePresentation.value}
          </strong>
        </div>
      ) : null}

      {authorityDisabled ? (
        <Text size="1" color="amber">
          {t('session.authorityActionUnavailable')}
        </Text>
      ) : null}
      {!answered && expiry.state === 'expired' ? (
        <Text size="1" color="red" role="alert">
          {t('chat.requestExpired')}
        </Text>
      ) : null}
      {!answered && expiry.state === 'invalid' ? (
        <Text size="1" color="red" role="alert">
          {t('chat.invalidExpiry')}
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
      ) : !answered && !browserOrigin && !browserCapability && (hitlType === 'permission' || hitlType === 'decision') ? (
        <Text size="1" color="red">
          {t('approval.incomplete', {
            fields: 'action, target, data, reason, risk, reversibility, scope, evidence',
          })}
        </Text>
      ) : null}

      {hitlType === 'permission' && parameterPreview ? (
        <div className="timeline-approval-params">
          <button
            type="button"
            className="timeline-approval-params-toggle"
            aria-expanded={detailsExpanded}
            onClick={() => setDetailsExpanded((current) => !current)}
          >
            {detailsExpanded ? (
              <ChevronDownIcon aria-hidden="true" />
            ) : (
              <ChevronRightIcon aria-hidden="true" />
            )}
            {t('chat.permissionDetails')}
          </button>
          {detailsExpanded ? (
            <pre className="timeline-approval-params-block">{parameterPreview}</pre>
          ) : null}
        </div>
      ) : null}

      {!answered && hitlType === 'permission' && browserOrigin ? (
        <>
          <Flex gap="2" wrap="wrap">
            <Button
              size="1"
              color="green"
              disabled={responseDisabled || !requestId || busy}
              loading={busy}
              onClick={() => void submit(browserOriginAllowResponseData('once'))}
            >
              {t('chat.browserOrigin.allowOnce')}
            </Button>
            <Button
              size="1"
              color="green"
              variant="soft"
              disabled={responseDisabled || !requestId || busy}
              loading={busy}
              onClick={() => void submit(browserOriginAllowResponseData('site'))}
            >
              {t('chat.browserOrigin.allowSite')}
            </Button>
            <Button
              size="1"
              color="amber"
              variant="soft"
              disabled={responseDisabled || !requestId || busy}
              loading={busy}
              onClick={() => void submit(browserOriginAllowResponseData('all'))}
            >
              {t('chat.browserOrigin.allowAll')}
            </Button>
            <Button
              size="1"
              color="red"
              variant="soft"
              disabled={responseDisabled || !requestId || busy}
              loading={busy}
              onClick={() => void submit(permissionDenialResponseData())}
            >
              {t('chat.deny')}
            </Button>
          </Flex>
          <Text size="1" color="amber">
            {t('chat.browserOrigin.allowAllWarning')}
          </Text>
        </>
      ) : null}

      {!answered && hitlType === 'permission' && browserCapability?.kind === 'browser_full_cdp' ? (
        <>
          <Flex gap="2" wrap="wrap">
            <Button
              size="1"
              color="green"
              disabled={responseDisabled || !requestId || busy}
              loading={busy}
              onClick={() => void submit(browserFullCdpAllowResponseData('once'))}
            >
              {t('chat.browserFullCdp.allowOnce')}
            </Button>
            <Button
              size="1"
              color="amber"
              variant="soft"
              disabled={responseDisabled || !requestId || busy}
              loading={busy}
              onClick={() => void submit(browserFullCdpAllowResponseData('site'))}
            >
              {t('chat.browserFullCdp.allowSite')}
            </Button>
            <Button
              size="1"
              color="red"
              variant="soft"
              disabled={responseDisabled || !requestId || busy}
              loading={busy}
              onClick={() => void submit(permissionDenialResponseData())}
            >
              {t('chat.deny')}
            </Button>
          </Flex>
          <Text size="1" color="amber">
            {t('chat.browserFullCdp.warning')}
          </Text>
        </>
      ) : null}

      {!answered && hitlType === 'permission' && browserCapability?.kind === 'browser_credential_fill' ? (
        <Flex gap="2" wrap="wrap">
          <Button
            size="1"
            color="green"
            disabled={responseDisabled || !requestId || busy}
            loading={busy}
            onClick={() => void submit(browserCredentialFillAllowResponseData())}
          >
            {t('chat.browserCredentialFill.allowOnce')}
          </Button>
          <Button
            size="1"
            color="red"
            variant="soft"
            disabled={responseDisabled || !requestId || busy}
            loading={busy}
            onClick={() => void submit(permissionDenialResponseData())}
          >
            {t('chat.deny')}
          </Button>
        </Flex>
      ) : null}

      {!answered && hitlType === 'permission' && !browserOrigin && !browserCapability ? (
        <>
          <Flex gap="2" wrap="wrap">
            <Button
              size="1"
              color="green"
              disabled={responseDisabled || !requestId || busy || !approvalValidation?.canApprove}
              loading={busy}
              onClick={() => void submit({ action: 'allow', granted: true, scope: 'once' })}
            >
              {t('chat.allowOnce')}
            </Button>
            <Button
              size="1"
              color="green"
              variant="soft"
              disabled={
                responseDisabled ||
                !requestId ||
                busy ||
                !approvalValidation?.canApprove ||
                !(
                  approvalRequest?.permission?.allow_remember ||
                  approvalRequest?.decision?.action?.name
                )
              }
              onClick={() =>
                void submit({ action: 'allow_always', granted: true, scope: 'workspace_tool' })
              }
            >
              {t('chat.allowAlways')}
            </Button>
            <Button
              size="1"
              color="red"
              variant="soft"
              disabled={responseDisabled || !requestId || busy}
              aria-expanded={denyFeedbackOpen}
              onClick={() => setDenyFeedbackOpen((current) => !current)}
            >
              {t('chat.deny')}
            </Button>
          </Flex>
          {denyFeedbackOpen ? (
            <div className="timeline-deny-feedback">
              <TextArea
                size="1"
                autoFocus
                value={denyFeedback}
                disabled={busy}
                placeholder={t('chat.denyFeedbackPlaceholder')}
                onChange={(event) => setDenyFeedback(event.currentTarget.value)}
              />
              <Text size="1" color="gray">
                {t('chat.denyFeedbackHint')}
              </Text>
              <Flex gap="2" wrap="wrap">
                <Button
                  size="1"
                  color="red"
                  disabled={busy || !denyFeedback.trim()}
                  loading={busy}
                  onClick={() => void submit(permissionDenialResponseData(denyFeedback))}
                >
                  {t('chat.denyWithFeedback')}
                </Button>
                <Button
                  size="1"
                  color="gray"
                  variant="soft"
                  disabled={busy}
                  loading={busy}
                  onClick={() => void submit(permissionDenialResponseData())}
                >
                  {t('chat.denyWithoutFeedback')}
                </Button>
              </Flex>
            </div>
          ) : null}
        </>
      ) : null}

      {!answered && hitlType === 'env_var' ? (
        <div className="timeline-detail-block">
          <span>{t('chat.environmentValues')}</span>
          {envVarView.fields.map((field) => (
            <label key={field.name}>
              <span>
                {field.label}
                {!field.required ? ` · ${t('chat.optionalField')}` : ''}
              </span>
              {field.description ? <small>{field.description}</small> : null}
              {field.inputElement === 'textarea' ? (
                <textarea
                  autoComplete="off"
                  disabled={responseDisabled || busy}
                  required={field.required}
                  placeholder={field.placeholder ?? undefined}
                  value={envValues[field.name] ?? ''}
                  onChange={(event) =>
                    setEnvValues((current) => ({
                      ...current,
                      [field.name]: event.currentTarget.value,
                    }))
                  }
                />
              ) : (
                <input
                  type={
                    field.inputElement === 'password'
                      ? 'password'
                      : field.inputElement === 'url'
                        ? 'url'
                        : 'text'
                  }
                  autoComplete="off"
                  disabled={responseDisabled || busy}
                  required={field.required}
                  placeholder={field.placeholder ?? undefined}
                  value={envValues[field.name] ?? ''}
                  onChange={(event) =>
                    setEnvValues((current) => ({
                      ...current,
                      [field.name]: event.currentTarget.value,
                    }))
                  }
                />
              )}
            </label>
          ))}
          {envVarView.allowSave ? (
            <label>
              <input
                type="checkbox"
                checked={saveEnvironmentValues}
                disabled={responseDisabled || busy}
                onChange={(event) => setSaveEnvironmentValues(event.currentTarget.checked)}
              />
              <span>{t('chat.saveEnvironmentValues')}</span>
            </label>
          ) : null}
          <Button
            size="1"
            disabled={
              !requestId ||
              responseDisabled ||
              busy ||
              !buildEnvVarResponse(envValues, saveEnvironmentValues, envVarView)
            }
            loading={busy}
            onClick={() => {
              const response = buildEnvVarResponse(
                envValues,
                saveEnvironmentValues,
                envVarView,
              );
              if (response) void submit(response);
            }}
          >
            {t('chat.submitSecurely')}
          </Button>
        </div>
      ) : null}

      {!answered && hitlType === 'decision' ? (
        <div className="timeline-detail-block">
          {decisionView.selectionMode === 'multiple' ? (
            <small>
              {decisionView.maxSelections
                ? t('chat.selectionLimit', { count: decisionView.maxSelections })
                : t('chat.selectOneOrMore')}
            </small>
          ) : null}
          {decisionView.options.map((option) => {
            const selected = decisionSelections.includes(option.value);
            const selectOption = () => {
              setCustomDecisionSelected(false);
              setDecisionSelections((current) =>
                toggleDecisionSelection(current, option.value, decisionView),
              );
            };
            return (
              <label key={option.value}>
                {decisionView.selectionMode === 'multiple' ? (
                  <input
                    type="checkbox"
                    checked={selected}
                    disabled={responseDisabled || busy}
                    onChange={selectOption}
                  />
                ) : (
                  <input
                    type="radio"
                    name={`hitl-decision-${requestId}`}
                    checked={selected}
                    disabled={responseDisabled || busy}
                    onChange={selectOption}
                  />
                )}
                <span>
                  <strong>{option.label}</strong>
                  {option.recommended ? <em>{t('chat.recommended')}</em> : null}
                  {option.description ? <small>{option.description}</small> : null}
                  {option.riskLevel ? (
                    <small>
                      {t('chat.risk')}: {option.riskLevel}
                    </small>
                  ) : null}
                  {option.estimatedTime ? (
                    <small>
                      {t('chat.estimatedTime')}: {option.estimatedTime}
                    </small>
                  ) : null}
                  {option.estimatedCost ? (
                    <small>
                      {t('chat.estimatedCost')}: {option.estimatedCost}
                    </small>
                  ) : null}
                  {option.risks.map((risk) => (
                    <small key={risk}>{risk}</small>
                  ))}
                </span>
              </label>
            );
          })}
          {decisionView.allowCustom ? (
            <>
              <label>
                <input
                  type="radio"
                  name={`hitl-decision-${requestId}`}
                  checked={customDecisionSelected}
                  disabled={responseDisabled || busy}
                  onChange={() => {
                    setCustomDecisionSelected(true);
                    setDecisionSelections([]);
                  }}
                />
                <span>{t('chat.enterDecision')}</span>
              </label>
              <TextArea
                size="1"
                value={answer}
                disabled={responseDisabled || busy || !customDecisionSelected}
                placeholder={t('chat.enterDecision')}
                onChange={(event) => setAnswer(event.currentTarget.value)}
              />
            </>
          ) : null}
          <Button
            size="1"
            disabled={
              responseDisabled ||
              !requestId ||
              busy ||
              !buildDecisionResponse(
                decisionSelections,
                customDecisionSelected,
                answer,
                decisionView,
              )
            }
            loading={busy}
            onClick={() => {
              const response = buildDecisionResponse(
                decisionSelections,
                customDecisionSelected,
                answer,
                decisionView,
              );
              if (response) void submit(response);
            }}
          >
            {t('chat.confirmSelection')}
          </Button>
        </div>
      ) : null}

      {!answered && hitlType === 'clarification' ? (
        <div className="timeline-detail-block">
          {options.length ? (
            <Flex gap="2" wrap="wrap">
              {options.map((option) => (
                <Button
                  size="1"
                  variant="soft"
                  disabled={responseDisabled || !requestId || busy}
                  title={option.description}
                  key={option.value}
                  onClick={() => void submit({ answer: option.value })}
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
                disabled={responseDisabled || busy}
                placeholder={t('chat.enterAnswer')}
                onChange={(event) => setAnswer(event.currentTarget.value)}
              />
              <Button
                size="1"
                disabled={responseDisabled || !requestId || busy || !answer.trim()}
                loading={busy}
                onClick={() => void submit({ answer: answer.trim() })}
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
                disabled={responseDisabled || !requestId || busy}
                loading={busy}
                key={`${action.sourceComponentId}:${action.actionName}`}
                onClick={() =>
                  void submit({
                    action_name: action.actionName,
                    source_component_id: action.sourceComponentId,
                    context: action.context ?? {},
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
