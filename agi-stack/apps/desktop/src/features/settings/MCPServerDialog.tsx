import { useMemo, useRef, useState } from 'react';
import {
  ComponentInstanceIcon,
  Cross2Icon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { DesktopMCPTransport } from '../../api/client';
import { parseMCPStdioCommand } from './mcpCommandModel';
import type { MCPServerCreateSubmission } from './useMCPServerManagement';
import { useModalDialog } from './useModalDialog';

import './PluginManagementDialogs.css';

const TRANSPORTS: readonly DesktopMCPTransport[] = ['stdio', 'http', 'sse', 'websocket'];

export function MCPServerCreateDialog({
  busy,
  error,
  onClose,
  onSubmit,
}: {
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: MCPServerCreateSubmission) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [serverType, setServerType] = useState<DesktopMCPTransport>('stdio');
  const [command, setCommand] = useState('');
  const [url, setUrl] = useState('');
  const [credentialKind, setCredentialKind] = useState<'none' | 'env' | 'header'>('none');
  const [credentialName, setCredentialName] = useState('');
  const [secret, setSecret] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const dialogRef = useModalDialog({
    active: true,
    initialFocusRef: nameRef,
    nested: true,
    onClose,
  });
  const requiresCommand = serverType === 'stdio';
  const requiresUrl = !requiresCommand;
  const secretKind = credentialKind === 'none' ? null : credentialKind;
  const parsedCommand = useMemo(
    () => (requiresCommand ? parseMCPStdioCommand(command) : null),
    [command, requiresCommand],
  );
  const canSubmit = useMemo(() => {
    if (!name.trim()) return false;
    if (requiresCommand && parsedCommand?.ok !== true) return false;
    if (requiresUrl && !url.trim()) return false;
    if (secretKind && (!credentialName.trim() || !secret)) return false;
    return true;
  }, [credentialName, name, parsedCommand, requiresCommand, requiresUrl, secret, secretKind, url]);

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
    setSecret('');
  };

  return (
    <div className="plugin-management-backdrop" onMouseDown={onClose}>
      <section
        ref={dialogRef}
        className="plugin-management-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={t('settings.mcpServers.createTitle')}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="plugin-management-heading">
          <ComponentInstanceIcon />
          <div>
            <span>{t('settings.mcp')}</span>
            <h2>{t('settings.mcpServers.createTitle')}</h2>
            <p>{t('settings.mcpServers.createDescription')}</p>
          </div>
          <button type="button" aria-label={t('common.close')} onClick={onClose}>
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
              onChange={(event) => setServerType(event.target.value as DesktopMCPTransport)}
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
                <option value="env">{t('settings.mcpServers.credentialKinds.env')}</option>
                <option value="header">{t('settings.mcpServers.credentialKinds.header')}</option>
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
        <footer className="plugin-management-footer">
          <button type="button" className="secondary" disabled={busy} onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button type="button" className="primary" disabled={busy || !canSubmit} onClick={submit}>
            {busy ? <ReloadIcon className="managed-resource-spin" /> : <ComponentInstanceIcon />}
            {t('settings.mcpServers.create')}
          </button>
        </footer>
      </section>
    </div>
  );
}
