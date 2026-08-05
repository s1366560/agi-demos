import { useRef, useState } from 'react';
import { Button, TextArea } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type {
  SubAgentControlCommand,
  SubAgentControlReceipt,
} from '../../hooks/useAgentSocket';
import {
  subAgentGroupControlAvailability,
  type SubAgentControlAuthority,
} from './subagentControlAuthorityModel';
import type { SubAgentTimelineGroup } from './subagentTimelineGroupModel';

type SubAgentControlPanelProps = {
  group: SubAgentTimelineGroup;
  authority: SubAgentControlAuthority;
  onControl: (
    command: SubAgentControlCommand,
  ) => Promise<SubAgentControlReceipt>;
};

type ControlAttempt = {
  fingerprint: string;
  idempotencyKey: string;
};

let controlSequence = 0;

export function SubAgentControlPanel({
  group,
  authority,
  onControl,
}: SubAgentControlPanelProps) {
  const { t } = useI18n();
  const availability = subAgentGroupControlAvailability(authority, group);
  const [instruction, setInstruction] = useState('');
  const [busyAction, setBusyAction] = useState<'steer' | 'kill_run' | null>(
    null,
  );
  const [confirmingKill, setConfirmingKill] = useState(false);
  const [notice, setNotice] = useState<{
    accepted: boolean;
    reasonCode: string | null;
  } | null>(null);
  const attemptRef = useRef<ControlAttempt | null>(null);
  const liveStatus = ['running', 'steered', 'queued', 'background'].includes(
    group.status,
  );

  if (!availability.available) {
    return liveStatus ? (
      <p className="subagent-control-unavailable">
        {t('chat.subagentControlUnavailable', {
          reason: availability.reasonCode ?? 'subagent_control_unavailable',
        })}
      </p>
    ) : null;
  }

  const dispatch = async (action: 'steer' | 'kill_run') => {
    const normalizedInstruction = instruction.trim();
    const fingerprint = `${action}\u0000${group.runId}\u0000${normalizedInstruction}`;
    if (attemptRef.current?.fingerprint !== fingerprint) {
      attemptRef.current = {
        fingerprint,
        idempotencyKey: createControlIdempotencyKey(action, group.runId),
      };
    }
    setBusyAction(action);
    setNotice(null);
    const receipt = await onControl({
      action,
      conversationId: authority.conversationId ?? '',
      runId: group.runId,
      expectedRunRevision: authority.authorityRevision ?? 0,
      idempotencyKey: attemptRef.current.idempotencyKey,
      ...(action === 'steer'
        ? { instruction: normalizedInstruction }
        : { cascade: false }),
    });
    setBusyAction(null);
    setNotice({ accepted: receipt.accepted, reasonCode: receipt.reasonCode });
    if (receipt.accepted) {
      attemptRef.current = null;
      if (action === 'steer') setInstruction('');
      setConfirmingKill(false);
    }
  };

  const canSteer = availability.allowedActions.includes('steer');
  const canKill = availability.allowedActions.includes('kill_run');
  return (
    <div
      className="subagent-control-panel"
      aria-label={t('chat.subagentControls')}
    >
      {canSteer ? (
        <div className="subagent-steer-control">
          <TextArea
            aria-label={t('chat.subagentSteerInstruction')}
            placeholder={t('chat.subagentSteerPlaceholder')}
            value={instruction}
            disabled={busyAction !== null}
            onChange={(event) => {
              setInstruction(event.currentTarget.value);
              attemptRef.current = null;
              setNotice(null);
            }}
          />
          <Button
            type="button"
            size="1"
            disabled={!instruction.trim() || busyAction !== null}
            onClick={() => void dispatch('steer')}
          >
            {busyAction === 'steer'
              ? t('chat.subagentSteering')
              : t('chat.subagentSteer')}
          </Button>
        </div>
      ) : null}
      {canKill ? (
        <div className="subagent-kill-control">
          {confirmingKill ? (
            <>
              <span>{t('chat.subagentKillConfirm')}</span>
              <Button
                type="button"
                size="1"
                color="red"
                disabled={busyAction !== null}
                onClick={() => void dispatch('kill_run')}
              >
                {busyAction === 'kill_run'
                  ? t('chat.subagentKilling')
                  : t('chat.subagentKillConfirmAction')}
              </Button>
              <Button
                type="button"
                size="1"
                variant="soft"
                disabled={busyAction !== null}
                onClick={() => setConfirmingKill(false)}
              >
                {t('common.cancel')}
              </Button>
            </>
          ) : (
            <Button
              type="button"
              size="1"
              color="red"
              variant="soft"
              disabled={busyAction !== null}
              onClick={() => setConfirmingKill(true)}
            >
              {t('chat.subagentKill')}
            </Button>
          )}
        </div>
      ) : null}
      {notice ? (
        <p
          className={
            notice.accepted
              ? 'subagent-control-accepted'
              : 'subagent-control-rejected'
          }
        >
          {notice.accepted
            ? t('chat.subagentControlAccepted')
            : t('chat.subagentControlRejected', {
                reason: notice.reasonCode ?? 'control_rejected',
              })}
        </p>
      ) : null}
    </div>
  );
}

function createControlIdempotencyKey(
  action: 'steer' | 'kill_run',
  runId: string,
): string {
  const randomId = globalThis.crypto?.randomUUID?.();
  controlSequence += 1;
  return `desktop-subagent-${action}:${runId}:${randomId ?? `${Date.now()}-${controlSequence}`}`;
}
