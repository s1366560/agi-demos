import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { DownloadIcon, FileIcon, ReloadIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import { createSandboxFileOperationGate } from './sandboxFileOperationGate';
import type {
  SandboxFileContent,
  SandboxFileDownload,
  SandboxFileEntry,
  SandboxFileAuthority,
  SandboxRuntimeCapability,
  SandboxRuntimeClient,
} from './sandboxRuntimeClient';
import './SandboxFileBrowser.css';

type SandboxFileBrowserProps = {
  capability: SandboxRuntimeCapability;
  client: SandboxRuntimeClient;
  rootPath?: string;
  onOpenFile?: (file: SandboxFileContent) => void;
  onDownloadFile?: (file: SandboxFileDownload) => void | Promise<void>;
};

export function SandboxFileBrowser({
  capability,
  client,
  rootPath = '/',
  onOpenFile,
  onDownloadFile,
}: SandboxFileBrowserProps) {
  const { t } = useI18n();
  const [path, setPath] = useState(rootPath);
  const [entries, setEntries] = useState<SandboxFileEntry[]>([]);
  const [authority, setAuthority] = useState<SandboxFileAuthority | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const operationGateRef = useRef(createSandboxFileOperationGate());

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (capability.availability !== 'available') return;
      setStatus('loading');
      setError(null);
      try {
        const result = await client.listFiles({ path, limit: 200 }, signal);
        if (signal?.aborted) return;
        if (result.status === 'unavailable') {
          setEntries([]);
          setAuthority(null);
          setError(result.reason_code);
          setStatus('error');
          return;
        }
        setEntries(result.value.entries);
        setAuthority(
          result.value.authority === 'sandbox'
            ? { authority: 'sandbox', isolation: 'isolated' }
            : {
                authority: 'native_workspace',
                isolation: 'not_applicable',
              },
        );
        setStatus('ready');
      } catch (caught) {
        if (signal?.aborted) return;
        setEntries([]);
        setAuthority(null);
        setError(caught instanceof Error ? caught.message : String(caught));
        setStatus('error');
      }
    },
    [capability.availability, client, path],
  );

  useLayoutEffect(() => {
    operationGateRef.current.invalidate();
    setPath(rootPath);
    setEntries([]);
    setAuthority(null);
    setStatus('idle');
    setError(null);
    return () => operationGateRef.current.invalidate();
  }, [capability.availability, client, rootPath]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (capability.availability !== 'available') {
    return (
      <section
        className="sandbox-file-browser sandbox-file-browser--unavailable"
        data-authority="unavailable"
        data-isolation="unavailable"
        data-reason-code={capability.reason_code ?? 'sandbox_file_api_unavailable'}
      >
        <FileIcon aria-hidden />
        <strong>{t('sandbox.filesUnavailable')}</strong>
        <span>{t('sandbox.filesUnavailableDescription')}</span>
        {capability.reason_code ? <code>{capability.reason_code}</code> : null}
      </section>
    );
  }

  const open = async (entry: SandboxFileEntry) => {
    if (entry.kind === 'directory') {
      setPath(entry.path);
      return;
    }
    const operation = operationGateRef.current.begin();
    try {
      const result = await client.readFile({ path: entry.path }, operation.signal);
      if (!operation.isCurrent()) return;
      if (result.status === 'ready') {
        onOpenFile?.(result.value);
        return;
      }
      setError(result.reason_code);
      setStatus('error');
    } catch (caught) {
      if (!operation.isCurrent()) return;
      setError(caught instanceof Error ? caught.message : String(caught));
      setStatus('error');
    } finally {
      operation.finish();
    }
  };

  const download = async (entry: SandboxFileEntry) => {
    const operation = operationGateRef.current.begin();
    try {
      const result = await client.downloadFile({ path: entry.path }, operation.signal);
      if (!operation.isCurrent()) return;
      if (result.status === 'ready') {
        await onDownloadFile?.(result.value);
        return;
      }
      setError(result.reason_code);
      setStatus('error');
    } catch (caught) {
      if (!operation.isCurrent()) return;
      setError(caught instanceof Error ? caught.message : String(caught));
      setStatus('error');
    } finally {
      operation.finish();
    }
  };

  return (
    <section
      className="sandbox-file-browser"
      data-authority={authority?.authority ?? 'sandbox'}
      data-isolation={authority?.isolation ?? 'unknown'}
    >
      <header>
        <span>
          <strong>{t('sandbox.filesTitle')}</strong>
          <small>{path}</small>
        </span>
        <button
          type="button"
          aria-label={t('sandbox.filesRefresh')}
          disabled={status === 'loading'}
          onClick={() => void load()}
        >
          <ReloadIcon aria-hidden />
        </button>
      </header>
      {path !== rootPath ? (
        <button
          type="button"
          className="sandbox-file-browser__up"
          onClick={() => setPath(parentPath(path, rootPath))}
        >
          {t('sandbox.filesParent')}
        </button>
      ) : null}
      {status === 'loading' ? <p role="status">{t('sandbox.filesLoading')}</p> : null}
      {status === 'error' ? (
        <p role="alert">
          {t('sandbox.filesError')}
          {error ? ` (${error})` : ''}
        </p>
      ) : null}
      {status === 'ready' && entries.length === 0 ? <p>{t('sandbox.filesEmpty')}</p> : null}
      {entries.length ? (
        <ul>
          {entries.map((entry) => (
            <li key={entry.path}>
              <button type="button" onClick={() => void open(entry)}>
                <FileIcon aria-hidden />
                <span>{entry.name}</span>
                <small>
                  {entry.kind === 'directory'
                    ? t('sandbox.filesDirectory')
                    : formatBytes(entry.size_bytes)}
                </small>
              </button>
              {entry.kind === 'file' ? (
                <button
                  type="button"
                  aria-label={t('sandbox.filesDownload', { name: entry.name })}
                  onClick={() => void download(entry)}
                >
                  <DownloadIcon aria-hidden />
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function parentPath(path: string, rootPath: string): string {
  const parent = path.split('/').slice(0, -1).join('/') || '/';
  return parent.length < rootPath.length ? rootPath : parent;
}

function formatBytes(value: number | null): string {
  if (value === null) return '';
  if (value < 1_024) return `${value} B`;
  return `${(value / 1_024).toFixed(value < 10_240 ? 1 : 0)} KB`;
}
