import { useMemo, useRef, useState } from 'react';
import {
  ComponentInstanceIcon,
  Cross2Icon,
  ReloadIcon,
  TrashIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { DesktopMCPServerSummary, DesktopMCPTransport } from '../../api/client';
import {
  formatMCPStdioCommand,
  mcpStdioCommandArgv,
  parseMCPStdioCommand,
} from './mcpCommandModel';
import type { MCPServerSubmission } from './useMCPServerManagement';
import { useModalDialog } from './useModalDialog';

import './PluginManagementDialogs.css';

const TRANSPORTS: readonly DesktopMCPTransport[] = ['stdio', 'http', 'sse', 'websocket'];

function initialCommand(server: DesktopMCPServerSummary | null): string {
  const config = server?.transport_config;
  return formatMCPStdioCommand(mcpStdioCommandArgv(config?.command, config?.args));
}

function initialCredential(server: DesktopMCPServerSummary | null): {
  kind: 'none' | 'env' | 'header';
  name: string;
} {
  const envName = server?.transport_config?.vault_env_names?.[0];
  if (envName) return { kind: 'env', name: envName };
  const headerName = server?.transport_config?.vault_header_names?.[0];
  if (headerName) return { kind: 'header', name: headerName };
  return { kind: 'none', name: '' };
}

export function MCPServerDialog({
  server,
  busy,
  error,
  onClose,
  onSubmit,
  onDelete,
}: {
  server: DesktopMCPServerSummary | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: MCPServerSubmission) => void;
  onDelete: (() => void) | null;
}) {
  const { t } = useI18n();
  const existingCredential = initialCredential(server);
  const existingCommand = initialCommand(server);
  const existingUrl = server?.transport_config?.url ?? '';
  const [name, setName] = useState(server?.name ?? '');
  const [description, setDescription] = useState(server?.description ?? '');
  const [serverType, setServerType] = useState<DesktopMCPTransport>(
    server?.server_type ?? 'stdio',
  );
  const [command, setCommand] = useState(
    server?.transport_config?.arguments_redacted ? '' : existingCommand,
  );
  const [url, setUrl] = useState(existingUrl);
  const [credentialKind, setCredentialKind] = useState<'none' | 'env' | 'header'>(
    existingCredential.kind,
  );
  const [credentialName, setCredentialName] = useState(existingCredential.name);
  const [secret, setSecret] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const requestClose = () => {
    if (!busy) onClose();
  };
  const dialogRef = useModalDialog({
    active: true,
    initialFocusRef: nameRef,
    nested: true,
    onClose: requestClose,
  });
  const requiresCommand = serverType === 'stdio';
  const requiresUrl = !requiresCommand;
  const secretKind = credentialKind === 'none' ? null : credentialKind;
  const parsedCommand = useMemo(
    () => (requiresCommand ? parseMCPStdioCommand(command) : null),
    [command, requiresCommand],
  );
  const credentialRequiresSecret = useMemo(() => {
    if (!secretKind) return false;
    if (!server) return true;
    if (
      secretKind !== existingCredential.kind ||
      credentialName.trim() !== existingCredential.name ||
      name.trim() !== server.name ||
      serverType !== server.server_type
    ) {
      return true;
    }
    if (requiresCommand) {
      return (
        Boolean(server.transport_config?.arguments_redacted) ||
        command.trim() !== existingCommand
      );
    }
    return url.trim() !== existingUrl;
  }, [
    command,
    credentialName,
    existingCommand,
    existingCredential.kind,
    existingCredential.name,
    existingUrl,
    name,
    requiresCommand,
    secretKind,
    server,
    serverType,
    url,
  ]);
  const canSubmit = useMemo(() => {
    if (!name.trim()) return false;
    if (requiresCommand && parsedCommand?.ok !== true) return false;
    if (requiresUrl && !url.trim()) return false;
    if (secretKind && (!credentialName.trim() || (credentialRequiresSecret && !secret))) {
      return false;
    }
    return true;
  }, [
    credentialName,
    credentialRequiresSecret,
    name,
    parsedCommand,
    requiresCommand,
    requiresUrl,
    secret,
    secretKind,
    url,
  ]);

  const submit = () => {
    if (!canSubmit) {
      setFormError('settings.mcpServers.error.required');
      return;
    }
    onSubmit({
      name: name.trim(),
      description: description.trim() || undefined,
      serverType,
      transport: requiresCommand
        ? { command: parsedCommand?.ok ? parsedCommand.argv : [] }
        : { url: url.trim() },
      credential: secretKind
        ? {
            kind: secretKind,
            name: credentialName.trim(),
            secret,
          }
        : null,
    });
  };

  return (
    <div className="plugin-management-backdrop" onMouseDown={requestClose}>
      <section
        ref={dialogRef}
        className="plugin-management-dialog"
        role="dialog"
        aria-modal="true"
        aria-busy={busy}
        aria-label={t(server ? 'common.edit' : 'settings.mcpServers.createTitle')}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="plugin-management-heading">
          <ComponentInstanceIcon />
          <div>
            <span>{t('settings.mcp')}</span>
            <h2>{t(server ? 'common.edit' : 'settings.mcpServers.createTitle')}</h2>
            <p>{t('settings.mcpServers.createDescription')}</p>
          </div>
          <button
            type="button"
            aria-label={t('common.close')}
            disabled={busy}
            onClick={requestClose}
          >
            <Cross2Icon />
          </button>
        </header>
        <div className="plugin-management-body">
          <label>
            <span>{t('settings.mcpServers.name')}</span>
            <input
              ref={nameRef}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label>
            <span>{t('settings.mcpServers.description')}</span>
            <input
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <label>
            <span>{t('settings.mcpServers.transport')}</span>
            <select
              value={serverType}
              onChange={(event) => {
                setServerType(event.target.value as DesktopMCPTransport);
                setCredentialKind('none');
                setCredentialName('');
                setSecret('');
              }}
            >
              {TRANSPORTS.map((transport) => (
                <option key={transport} value={transport}>
                  {t(`settings.mcpServers.transports.${transport}`)}
                </option>
              ))}
            </select>
          </label>
          {requiresCommand ? (
            <label>
              <span>{t('settings.mcpServers.command')}</span>
              <input
                value={command}
                onChange={(event) => setCommand(event.target.value)}
                placeholder={t('settings.mcpServers.commandPlaceholder')}
              />
              {command && parsedCommand?.ok === false ? (
                <small className="plugin-management-error">
                  {t(`settings.mcpServers.error.command.${parsedCommand.reason}`)}
                </small>
              ) : null}
            </label>
          ) : (
            <label>
              <span>{t('settings.mcpServers.url')}</span>
              <input
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder={t('settings.mcpServers.urlPlaceholder')}
              />
            </label>
          )}
          <fieldset className="plugin-management-fieldset">
            <legend>{t('settings.mcpServers.credential')}</legend>
            <label>
              <span>{t('settings.mcpServers.credentialKind')}</span>
              <select
                value={credentialKind}
                onChange={(event) =>
                  setCredentialKind(event.target.value as 'none' | 'env' | 'header')
                }
              >
                <option value="none">{t('settings.mcpServers.credentialKinds.none')}</option>
                {requiresCommand ? (
                  <option value="env">{t('settings.mcpServers.credentialKinds.env')}</option>
                ) : (
                  <option value="header">
                    {t('settings.mcpServers.credentialKinds.header')}
                  </option>
                )}
              </select>
            </label>
            {secretKind ? (
              <>
                <label>
                  <span>{t('settings.mcpServers.credentialName')}</span>
                  <input
                    value={credentialName}
                    onChange={(event) => setCredentialName(event.target.value)}
                  />
                </label>
                <label>
                  <span>{t('settings.mcpServers.secret')}</span>
                  <input
                    type="password"
                    value={secret}
                    onChange={(event) => setSecret(event.target.value)}
                    autoComplete="new-password"
                  />
                </label>
              </>
            ) : null}
          </fieldset>
          {formError || error ? (
            <div className="plugin-management-error" role="alert">
              {formError ? t(formError) : error}
            </div>
          ) : null}
        </div>
        <footer className={`plugin-management-footer${server ? ' split' : ''}`}>
          {server ? (
            <div>
              <button
                type="button"
                className="danger"
                disabled={busy}
                onClick={onDelete ?? undefined}
              >
                <TrashIcon />
                {t('common.delete')}
              </button>
            </div>
          ) : null}
          <div>
            <button type="button" className="secondary" disabled={busy} onClick={onClose}>
              {t('common.cancel')}
            </button>
            <button
              type="button"
              className="primary"
              disabled={busy || !canSubmit}
              onClick={submit}
            >
              {busy ? (
                <ReloadIcon className="managed-resource-spin" />
              ) : (
                <ComponentInstanceIcon />
              )}
              {t(server ? 'common.save' : 'settings.mcpServers.create')}
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
