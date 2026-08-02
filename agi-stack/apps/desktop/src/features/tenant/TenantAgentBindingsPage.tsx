import {
  Cross2Icon,
  ExclamationTriangleIcon,
  Link2Icon,
  MagnifyingGlassIcon,
  PlusIcon,
  ReloadIcon,
  TrashIcon,
} from '@radix-ui/react-icons';
import { Button, Select, Switch, TextField } from '@radix-ui/themes';
import { useState } from 'react';

import { useI18n } from '../../i18n';
import {
  createTenantAgentBindingMutationKey,
  type CreateTenantAgentBindingInput,
  type TestTenantAgentBindingInput,
} from './tenantAgentBindingsClient';
import type {
  TenantAgentBindingsController,
  TenantAgentBindingsViewModel,
} from './tenantAgentBindingsController';
import './TenantAgentBindingsPage.css';

const CHANNEL_TYPES = ['web', 'feishu', 'dingtalk', 'wechat', 'slack', 'api'];

export function TenantAgentBindingsPage({
  model,
  controller,
  onRetry,
}: Readonly<{
  model: TenantAgentBindingsViewModel;
  controller: TenantAgentBindingsController | null;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  const [editor, setEditor] = useState<'create' | 'test' | null>(null);
  if (
    model.state !== 'ready' &&
    model.state !== 'empty' &&
    model.state !== 'stale' &&
    model.state !== 'conflict'
  ) {
    return <TenantAgentBindingsState model={model} onRetry={onRetry} />;
  }
  return (
    <section className="tenant-agent-bindings-page" data-state={model.state}>
      <header className="tenant-agent-bindings-header">
        <div>
          <span>{t('tenantAgentBindings.eyebrow')}</span>
          <h1>{t('tenantAgentBindings.title')}</h1>
          <p>{t('tenantAgentBindings.subtitle')}</p>
        </div>
        <div className="tenant-agent-bindings-header-actions">
          {model.allowedActions.includes('test') ? (
            <Button color="gray" variant="soft" onClick={() => setEditor('test')}>
              <Link2Icon />
              {t('tenantAgentBindings.test')}
            </Button>
          ) : null}
          {model.allowedActions.includes('create') ? (
            <Button color="gray" onClick={() => setEditor('create')}>
              <PlusIcon />
              {t('tenantAgentBindings.create')}
            </Button>
          ) : null}
        </div>
      </header>
      {model.state === 'stale' || model.state === 'conflict' ? (
        <div className="tenant-agent-bindings-notice" role="status">
          <ExclamationTriangleIcon />
          <span>
            {t(
              model.state === 'conflict'
                ? 'tenantAgentBindings.state.conflict.description'
                : 'tenantAgentBindings.state.stale.description',
            )}
          </span>
          <code>{model.reasonCode}</code>
          <Button color="gray" variant="ghost" onClick={onRetry}>
            <ReloadIcon />
            {t('common.retry')}
          </Button>
        </div>
      ) : null}
      <BindingFilters model={model} controller={controller} />
      <div className="tenant-agent-bindings-summary">
        <strong>{model.visibleBindings.length}</strong>
        <span>{t('tenantAgentBindings.summary')}</span>
        <code>{model.scope.tenantId}</code>
      </div>
      {model.visibleBindings.length === 0 ? (
        <div className="tenant-agent-bindings-empty">
          <h2>
            {t(
              model.emptyReason === 'filter'
                ? 'tenantAgentBindings.empty.filter.title'
                : 'tenantAgentBindings.empty.source.title',
            )}
          </h2>
          <p>
            {t(
              model.emptyReason === 'filter'
                ? 'tenantAgentBindings.empty.filter.description'
                : 'tenantAgentBindings.empty.source.description',
            )}
          </p>
        </div>
      ) : (
        <div className="tenant-agent-bindings-grid">
          {model.visibleBindings.map((binding) => (
            <article key={binding.id}>
              <header>
                <div>
                  <strong>{binding.agentName}</strong>
                  <code>{binding.agentId}</code>
                </div>
                {model.allowedActions.includes('set-enabled') && controller ? (
                  <Switch
                    checked={binding.enabled}
                    disabled={model.busyAction !== null}
                    aria-label={t('tenantAgentBindings.enabled', {
                      name: binding.agentName,
                    })}
                    onCheckedChange={(enabled) => {
                      void controller
                        .setEnabled(binding.id, enabled)
                        .catch(() => undefined);
                    }}
                  />
                ) : (
                  <span data-enabled={binding.enabled}>
                    {t(
                      binding.enabled
                        ? 'tenantAgentBindings.status.enabled'
                        : 'tenantAgentBindings.status.disabled',
                    )}
                  </span>
                )}
              </header>
              <dl>
                <BindingField
                  label={t('tenantAgentBindings.field.channel')}
                  value={binding.channelType}
                />
                <BindingField
                  label={t('tenantAgentBindings.field.channelId')}
                  value={binding.channelId}
                />
                <BindingField
                  label={t('tenantAgentBindings.field.account')}
                  value={binding.accountId}
                />
                <BindingField
                  label={t('tenantAgentBindings.field.peer')}
                  value={binding.peerId}
                />
                <BindingField
                  label={t('tenantAgentBindings.field.group')}
                  value={binding.groupId}
                />
                <BindingField
                  label={t('tenantAgentBindings.field.specificity')}
                  value={String(binding.specificityScore)}
                />
                <BindingField
                  label={t('tenantAgentBindings.field.priority')}
                  value={String(binding.priority)}
                />
              </dl>
              {model.allowedActions.includes('delete') && controller ? (
                <footer>
                  <Button
                    color="red"
                    variant="soft"
                    disabled={model.busyAction !== null}
                    onClick={() => {
                      void controller.delete(binding.id).catch(() => undefined);
                    }}
                  >
                    <TrashIcon />
                    {t('common.delete')}
                  </Button>
                </footer>
              ) : null}
            </article>
          ))}
        </div>
      )}
      {model.testResult ? (
        <TestResult model={model} />
      ) : null}
      {editor && controller ? (
        <BindingEditor
          kind={editor}
          model={model}
          controller={controller}
          onClose={() => setEditor(null)}
        />
      ) : null}
    </section>
  );
}

function BindingFilters({
  model,
  controller,
}: Readonly<{
  model: TenantAgentBindingsViewModel;
  controller: TenantAgentBindingsController | null;
}>) {
  const { t } = useI18n();
  return (
    <div className="tenant-agent-bindings-filters">
      <label>
        <MagnifyingGlassIcon />
        <span>{t('tenantAgentBindings.search')}</span>
        <TextField.Root
          value={model.filters.search}
          onChange={(event) =>
            controller?.setFilters({ search: event.target.value })
          }
          placeholder={t('tenantAgentBindings.search')}
        />
      </label>
      <Select.Root
        value={model.filters.channelType ?? 'all'}
        onValueChange={(value) =>
          controller?.setFilters({
            channelType: value === 'all' ? null : value,
          })
        }
      >
        <Select.Trigger aria-label={t('tenantAgentBindings.filter.channel')} />
        <Select.Content>
          <Select.Item value="all">{t('tenantAgentBindings.filter.all')}</Select.Item>
          <Select.Item value="any">{t('tenantAgentBindings.filter.any')}</Select.Item>
          {CHANNEL_TYPES.map((channel) => (
            <Select.Item key={channel} value={channel}>
              {channel}
            </Select.Item>
          ))}
        </Select.Content>
      </Select.Root>
      <Select.Root
        value={
          model.filters.enabled === null
            ? 'all'
            : model.filters.enabled
              ? 'enabled'
              : 'disabled'
        }
        onValueChange={(value) =>
          controller?.setFilters({
            enabled: value === 'all' ? null : value === 'enabled',
          })
        }
      >
        <Select.Trigger aria-label={t('tenantAgentBindings.filter.status')} />
        <Select.Content>
          <Select.Item value="all">{t('tenantAgentBindings.filter.all')}</Select.Item>
          <Select.Item value="enabled">
            {t('tenantAgentBindings.status.enabled')}
          </Select.Item>
          <Select.Item value="disabled">
            {t('tenantAgentBindings.status.disabled')}
          </Select.Item>
        </Select.Content>
      </Select.Root>
    </div>
  );
}

function BindingEditor({
  kind,
  model,
  controller,
  onClose,
}: Readonly<{
  kind: 'create' | 'test';
  model: TenantAgentBindingsViewModel;
  controller: TenantAgentBindingsController;
  onClose: () => void;
}>) {
  const { t } = useI18n();
  const [agentId, setAgentId] = useState(model.definitions[0]?.id ?? '');
  const [channelType, setChannelType] = useState('web');
  const [channelId, setChannelId] = useState('');
  const [accountId, setAccountId] = useState('');
  const [peerId, setPeerId] = useState('');
  const [groupId, setGroupId] = useState('');
  const [priority, setPriority] = useState('0');
  const submit = async () => {
    if (kind === 'create') {
      const input: CreateTenantAgentBindingInput = {
        agentId,
        channelType,
        channelId: nullable(channelId),
        accountId: nullable(accountId),
        peerId: nullable(peerId),
        groupId: nullable(groupId),
        priority: Number.parseInt(priority, 10) || 0,
      };
      await controller.create(
        input,
        createTenantAgentBindingMutationKey('create'),
      );
    } else {
      const input: TestTenantAgentBindingInput = {
        channelType,
        channelId: nullable(channelId),
        accountId: nullable(accountId),
        peerId: nullable(peerId),
      };
      await controller.test(input);
    }
    onClose();
  };
  return (
    <div className="tenant-agent-bindings-dialog">
      <div
        className="tenant-agent-bindings-dialog-card"
        role="dialog"
        aria-modal="true"
        onKeyDown={(event) => {
          if (event.key === 'Escape') onClose();
        }}
      >
        <header>
          <h2>
            {t(
              kind === 'create'
                ? 'tenantAgentBindings.create'
                : 'tenantAgentBindings.test',
            )}
          </h2>
          <Button
            color="gray"
            variant="ghost"
            aria-label={t('common.close')}
            onClick={onClose}
          >
            <Cross2Icon />
          </Button>
        </header>
        {kind === 'create' ? (
          <label>
            <span>{t('tenantAgentBindings.field.agent')}</span>
            <Select.Root value={agentId} onValueChange={setAgentId}>
              <Select.Trigger />
              <Select.Content>
                {model.definitions.map((definition) => (
                  <Select.Item key={definition.id} value={definition.id}>
                    {definition.displayName}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </label>
        ) : null}
        <EditorField
          label={t('tenantAgentBindings.field.channel')}
          value={channelType}
          onChange={setChannelType}
        />
        <EditorField
          label={t('tenantAgentBindings.field.channelId')}
          value={channelId}
          onChange={setChannelId}
        />
        <EditorField
          label={t('tenantAgentBindings.field.account')}
          value={accountId}
          onChange={setAccountId}
        />
        <EditorField
          label={t('tenantAgentBindings.field.peer')}
          value={peerId}
          onChange={setPeerId}
        />
        {kind === 'create' ? (
          <>
            <EditorField
              label={t('tenantAgentBindings.field.group')}
              value={groupId}
              onChange={setGroupId}
            />
            <EditorField
              label={t('tenantAgentBindings.field.priority')}
              value={priority}
              onChange={setPriority}
            />
          </>
        ) : null}
        <footer>
          <Button color="gray" variant="soft" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            autoFocus
            color="gray"
            disabled={
              model.busyAction !== null ||
              !channelType.trim() ||
              (kind === 'create' && !agentId)
            }
            onClick={() => {
              void submit().catch(() => undefined);
            }}
          >
            {t(kind === 'create' ? 'common.create' : 'tenantAgentBindings.test')}
          </Button>
        </footer>
      </div>
    </div>
  );
}

function TestResult({
  model,
}: Readonly<{ model: TenantAgentBindingsViewModel }>) {
  const { t } = useI18n();
  const result = model.testResult;
  if (!result) return null;
  return (
    <section className="tenant-agent-bindings-test-result" aria-live="polite">
      <span>{t('tenantAgentBindings.test.result')}</span>
      <strong>
        {result.matched
          ? result.agentName ?? result.agentId
          : t('tenantAgentBindings.test.noMatch')}
      </strong>
      <code>{Math.round(result.confidence * 100)}%</code>
      <span>{t('tenantAgentBindings.test.trace', { count: result.trace.length })}</span>
    </section>
  );
}

function TenantAgentBindingsState({
  model,
  onRetry,
}: Readonly<{
  model: TenantAgentBindingsViewModel;
  onRetry: () => void;
}>) {
  const { t } = useI18n();
  return (
    <section
      className="tenant-agent-bindings-page tenant-agent-bindings-state"
      data-state={model.state}
    >
      <ExclamationTriangleIcon />
      <h1>{t(`tenantAgentBindings.state.${model.state}.title`)}</h1>
      <p>{t(`tenantAgentBindings.state.${model.state}.description`)}</p>
      {model.reasonCode ? <code>{model.reasonCode}</code> : null}
      {model.retryVisible ? (
        <Button color="gray" onClick={onRetry}>
          <ReloadIcon />
          {t('common.retry')}
        </Button>
      ) : null}
    </section>
  );
}

function BindingField({
  label,
  value,
}: Readonly<{ label: string; value: string | null }>) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value || '—'}</dd>
    </div>
  );
}

function EditorField({
  label,
  value,
  onChange,
}: Readonly<{
  label: string;
  value: string;
  onChange: (value: string) => void;
}>) {
  return (
    <label>
      <span>{label}</span>
      <TextField.Root
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function nullable(value: string): string | null {
  return value.trim() || null;
}
