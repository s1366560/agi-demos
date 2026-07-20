import { useEffect, useState } from 'react';
import { Button, Dialog, Select, Switch, Text, TextArea, TextField } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import type { AutomationCreateInput, AutomationJob } from '../../types';

type ScheduleKind = 'cron' | 'every' | 'at';
type PayloadKind = 'system_event' | 'agent_turn';
type DeliveryKind = 'none' | 'announce' | 'webhook';

type AutomationDraft = {
  name: string;
  description: string;
  enabled: boolean;
  scheduleKind: ScheduleKind;
  scheduleValue: string;
  payloadKind: PayloadKind;
  payloadMessage: string;
  deliveryKind: DeliveryKind;
  conversationMode: 'reuse' | 'fresh';
  timezone: string;
  timeoutSeconds: string;
  maxRetries: string;
  deleteAfterRun: boolean;
};

type AutomationEditorDialogProps = {
  open: boolean;
  job: AutomationJob | null;
  busy: boolean;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (input: Omit<AutomationCreateInput, 'idempotency_key'>) => Promise<void>;
};

export function AutomationEditorDialog({
  open,
  job,
  busy,
  error,
  onOpenChange,
  onSubmit,
}: AutomationEditorDialogProps) {
  const { t } = useI18n();
  const [draft, setDraft] = useState<AutomationDraft>(() => draftFromJob(job));

  useEffect(() => {
    if (open) setDraft(draftFromJob(job));
  }, [job, open]);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const timeoutSeconds = Number(draft.timeoutSeconds);
    const maxRetries = Number(draft.maxRetries);
    const schedule = scheduleInput(draft);
    if (!schedule || !Number.isInteger(timeoutSeconds) || !Number.isInteger(maxRetries)) return;
    await onSubmit({
      name: draft.name.trim(),
      description: draft.description.trim(),
      enabled: draft.enabled,
      delete_after_run: draft.deleteAfterRun,
      schedule,
      payload: {
        kind: draft.payloadKind,
        config:
          draft.payloadKind === 'agent_turn'
            ? { message: draft.payloadMessage.trim() }
            : { content: draft.payloadMessage.trim() },
      },
      delivery: { kind: draft.deliveryKind, config: {} },
      conversation_mode: draft.conversationMode,
      timezone: draft.timezone.trim(),
      stagger_seconds: 0,
      timeout_seconds: timeoutSeconds,
      max_retries: maxRetries,
    });
  };

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Content className="automation-editor-dialog" maxWidth="620px">
        <Dialog.Title>
          {job ? t('automations.form.editTitle') : t('automations.form.createTitle')}
        </Dialog.Title>
        <Dialog.Description>{t('automations.form.description')}</Dialog.Description>
        <form className="automation-editor-form" onSubmit={(event) => void submit(event)}>
          <label className="automation-form-field automation-form-span">
            <Text size="1" weight="bold">
              {t('automations.form.name')}
            </Text>
            <TextField.Root
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              placeholder={t('automations.form.namePlaceholder')}
              maxLength={200}
              required
              disabled={busy}
            />
          </label>
          <label className="automation-form-field automation-form-span">
            <Text size="1" weight="bold">
              {t('automations.form.jobDescription')}
            </Text>
            <TextArea
              value={draft.description}
              onChange={(event) => setDraft({ ...draft, description: event.target.value })}
              rows={2}
              disabled={busy}
            />
          </label>
          <AutomationSelect
            label={t('automations.form.scheduleType')}
            value={draft.scheduleKind}
            onValueChange={(value) =>
              setDraft({
                ...draft,
                scheduleKind: value as ScheduleKind,
                scheduleValue: defaultScheduleValue(value as ScheduleKind),
              })
            }
            disabled={busy}
            options={[
              ['cron', t('automations.form.cron')],
              ['every', t('automations.form.every')],
              ['at', t('automations.form.at')],
            ]}
          />
          <label className="automation-form-field">
            <Text size="1" weight="bold">
              {t(`automations.form.scheduleValue.${draft.scheduleKind}`)}
            </Text>
            <TextField.Root
              type={draft.scheduleKind === 'every' ? 'number' : 'text'}
              value={draft.scheduleValue}
              min={draft.scheduleKind === 'every' ? '1' : undefined}
              onChange={(event) => setDraft({ ...draft, scheduleValue: event.target.value })}
              required
              disabled={busy}
            />
          </label>
          <AutomationSelect
            label={t('automations.form.payloadType')}
            value={draft.payloadKind}
            onValueChange={(value) => setDraft({ ...draft, payloadKind: value as PayloadKind })}
            disabled={busy}
            options={[
              ['agent_turn', t('automations.form.agentTurn')],
              ['system_event', t('automations.form.systemEvent')],
            ]}
          />
          <label className="automation-form-field">
            <Text size="1" weight="bold">
              {t('automations.form.payloadMessage')}
            </Text>
            <TextField.Root
              value={draft.payloadMessage}
              onChange={(event) => setDraft({ ...draft, payloadMessage: event.target.value })}
              required
              disabled={busy}
            />
          </label>
          <AutomationSelect
            label={t('automations.form.delivery')}
            value={draft.deliveryKind}
            onValueChange={(value) => setDraft({ ...draft, deliveryKind: value as DeliveryKind })}
            disabled={busy}
            options={[
              ['none', t('automations.form.deliveryNone')],
              ['announce', t('automations.form.deliveryAnnounce')],
              ['webhook', t('automations.form.deliveryWebhook')],
            ]}
          />
          <AutomationSelect
            label={t('automations.form.conversationMode')}
            value={draft.conversationMode}
            onValueChange={(value) =>
              setDraft({
                ...draft,
                conversationMode: value as 'reuse' | 'fresh',
              })
            }
            disabled={busy}
            options={[
              ['reuse', t('automations.form.reuseConversation')],
              ['fresh', t('automations.form.freshConversation')],
            ]}
          />
          <label className="automation-form-field">
            <Text size="1" weight="bold">
              {t('automations.form.timezone')}
            </Text>
            <TextField.Root
              value={draft.timezone}
              onChange={(event) => setDraft({ ...draft, timezone: event.target.value })}
              required
              disabled={busy}
            />
          </label>
          <label className="automation-form-field">
            <Text size="1" weight="bold">
              {t('automations.form.timeout')}
            </Text>
            <TextField.Root
              type="number"
              min="1"
              max="86400"
              value={draft.timeoutSeconds}
              onChange={(event) => setDraft({ ...draft, timeoutSeconds: event.target.value })}
              required
              disabled={busy}
            />
          </label>
          <label className="automation-form-field">
            <Text size="1" weight="bold">
              {t('automations.form.retries')}
            </Text>
            <TextField.Root
              type="number"
              min="0"
              max="20"
              value={draft.maxRetries}
              onChange={(event) => setDraft({ ...draft, maxRetries: event.target.value })}
              required
              disabled={busy}
            />
          </label>
          <div className="automation-form-switches automation-form-span">
            <label>
              <Switch
                checked={draft.enabled}
                onCheckedChange={(enabled) => setDraft({ ...draft, enabled })}
                disabled={busy}
              />
              <Text size="2">{t('automations.form.enabled')}</Text>
            </label>
            <label>
              <Switch
                checked={draft.deleteAfterRun}
                onCheckedChange={(deleteAfterRun) => setDraft({ ...draft, deleteAfterRun })}
                disabled={busy}
              />
              <Text size="2">{t('automations.form.deleteAfterRun')}</Text>
            </label>
          </div>
          {error ? (
            <div className="automation-inline-error automation-form-span" role="alert">
              {error}
            </div>
          ) : null}
          <div className="automation-editor-actions automation-form-span">
            <Dialog.Close>
              <Button type="button" variant="soft" color="gray" disabled={busy}>
                {t('automations.form.cancel')}
              </Button>
            </Dialog.Close>
            <Button type="submit" disabled={busy}>
              {busy
                ? t('automations.form.saving')
                : job
                  ? t('automations.form.save')
                  : t('automations.form.create')}
            </Button>
          </div>
        </form>
      </Dialog.Content>
    </Dialog.Root>
  );
}

function AutomationSelect({
  label,
  value,
  options,
  disabled,
  onValueChange,
}: {
  label: string;
  value: string;
  options: Array<[string, string]>;
  disabled: boolean;
  onValueChange: (value: string) => void;
}) {
  return (
    <label className="automation-form-field">
      <Text size="1" weight="bold">
        {label}
      </Text>
      <Select.Root value={value} onValueChange={onValueChange} disabled={disabled}>
        <Select.Trigger />
        <Select.Content>
          {options.map(([optionValue, optionLabel]) => (
            <Select.Item key={optionValue} value={optionValue}>
              {optionLabel}
            </Select.Item>
          ))}
        </Select.Content>
      </Select.Root>
    </label>
  );
}

function draftFromJob(job: AutomationJob | null): AutomationDraft {
  const scheduleKind = isScheduleKind(job?.schedule.kind) ? job.schedule.kind : 'cron';
  return {
    name: job?.name ?? '',
    description: job?.description ?? '',
    enabled: job?.enabled ?? true,
    scheduleKind,
    scheduleValue: job ? scheduleValue(job, scheduleKind) : defaultScheduleValue(scheduleKind),
    payloadKind: job?.payload.kind === 'system_event' ? 'system_event' : 'agent_turn',
    payloadMessage: String(job?.payload.config.message ?? job?.payload.config.content ?? ''),
    deliveryKind: isDeliveryKind(job?.delivery.kind) ? job.delivery.kind : 'none',
    conversationMode: job?.conversation_mode === 'fresh' ? 'fresh' : 'reuse',
    timezone: job?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    timeoutSeconds: String(job?.timeout_seconds ?? 300),
    maxRetries: String(job?.max_retries ?? 0),
    deleteAfterRun: job?.delete_after_run ?? false,
  };
}

function scheduleInput(draft: AutomationDraft): AutomationCreateInput['schedule'] | null {
  const value = draft.scheduleValue.trim();
  if (!value) return null;
  if (draft.scheduleKind === 'every') {
    const intervalSeconds = Number(value);
    if (!Number.isInteger(intervalSeconds) || intervalSeconds < 1) return null;
    return { kind: 'every', config: { interval_seconds: intervalSeconds } };
  }
  if (draft.scheduleKind === 'at') return { kind: 'at', config: { run_at: value } };
  return { kind: 'cron', config: { expr: value } };
}

function scheduleValue(job: AutomationJob, kind: ScheduleKind): string {
  if (kind === 'every') return String(job.schedule.config.interval_seconds ?? '');
  if (kind === 'at')
    return String(job.schedule.config.run_at ?? job.schedule.config.target_time ?? '');
  return String(job.schedule.config.expr ?? job.schedule.config.expression ?? '');
}

function defaultScheduleValue(kind: ScheduleKind): string {
  if (kind === 'every') return '300';
  if (kind === 'at') return '';
  return '0 * * * *';
}

function isScheduleKind(value: string | undefined): value is ScheduleKind {
  return value === 'cron' || value === 'every' || value === 'at';
}

function isDeliveryKind(value: string | undefined): value is DeliveryKind {
  return value === 'none' || value === 'announce' || value === 'webhook';
}
