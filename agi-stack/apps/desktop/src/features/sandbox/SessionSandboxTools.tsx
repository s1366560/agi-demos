import { useLayoutEffect, useState } from 'react';
import { DesktopIcon, FileIcon, ReloadIcon } from '@radix-ui/react-icons';
import { Button, Text } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import { saveBlobWithDesktopDialog } from '../runtime/nativeFileBridge';
import { RemoteDesktopSurface } from './RemoteDesktopSurface';
import { SandboxFileBrowser } from './SandboxFileBrowser';
import type { SandboxFileContent, SandboxFileDownload } from './sandboxRuntimeClient';
import type { SessionSandboxRuntimeSurface } from './useSandboxRuntimeSurface';
import './SessionSandboxTools.css';

type SessionSandboxToolsProps = {
  runtime: SessionSandboxRuntimeSurface;
};

export function SessionSandboxTools({ runtime }: SessionSandboxToolsProps) {
  const { t } = useI18n();
  const [activeSurface, setActiveSurface] = useState<'desktop' | 'files'>('desktop');
  const [previewFile, setPreviewFile] = useState<SandboxFileContent | null>(null);

  useLayoutEffect(() => {
    setPreviewFile(null);
  }, [runtime.fileClient]);

  if (runtime.capabilityStatus !== 'ready') {
    return (
      <section
        className="session-sandbox-tools session-sandbox-tools--unavailable"
        data-status={runtime.capabilityStatus}
        data-reason-code={
          runtime.capabilityLoadReason ?? 'sandbox_runtime_capability_contract_unavailable'
        }
      >
        <strong>{t('sandbox.runtimeToolsTitle')}</strong>
        <Text size="1" color="gray">
          {runtime.capabilityStatus === 'loading'
            ? t('sandbox.runtimeCapabilitiesLoading')
            : t('sandbox.runtimeCapabilitiesUnavailable')}
        </Text>
        {runtime.capabilityLoadReason ? (
          <code>{runtime.capabilityLoadReason}</code>
        ) : null}
        {runtime.capabilityStatus === 'unavailable' ? (
          <Button size="1" variant="soft" onClick={runtime.reloadCapabilities}>
            <ReloadIcon />
            {t('common.retry')}
          </Button>
        ) : null}
      </section>
    );
  }

  return (
    <section
      className="session-sandbox-tools"
      aria-label={t('sandbox.runtimeToolsTitle')}
    >
      <header>
        <Text size="1" weight="bold" color="gray">
          {t('sandbox.runtimeToolsTitle')}
        </Text>
        <div role="tablist" aria-label={t('sandbox.runtimeToolsTitle')}>
          <button
            type="button"
            role="tab"
            aria-selected={activeSurface === 'desktop'}
            onClick={() => setActiveSurface('desktop')}
          >
            <DesktopIcon />
            {t('sandbox.desktop')}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeSurface === 'files'}
            onClick={() => setActiveSurface('files')}
          >
            <FileIcon />
            {t('sandbox.filesTitle')}
          </button>
        </div>
      </header>

      {activeSurface === 'desktop' ? (
        <RemoteDesktopSurface
          capability={runtime.remoteDesktopCapability}
          session={runtime.remoteDesktopSession}
          sessionRevision={runtime.remoteDesktopRevision}
          status={runtime.remoteDesktopStatus}
          reasonCode={runtime.remoteDesktopReason}
          resolution={runtime.remoteDesktopResolution}
          onResolutionChange={runtime.setRemoteDesktopResolution}
          onStart={runtime.startRemoteDesktop}
          onReconnect={runtime.startRemoteDesktop}
        />
      ) : runtime.fileClient ? (
        <div className="session-sandbox-tools__files">
          <SandboxFileBrowser
            capability={runtime.filesCapability}
            client={runtime.fileClient}
            onOpenFile={setPreviewFile}
            onDownloadFile={downloadSandboxFile}
          />
          {previewFile ? (
            <section
              className="session-sandbox-tools__preview"
              data-authority={previewFile.authority}
              data-isolation={previewFile.isolation}
            >
              <header>
                <span>
                  <strong>{t('sandbox.filePreviewTitle')}</strong>
                  <small>{previewFile.path}</small>
                </span>
                <Button size="1" variant="ghost" onClick={() => setPreviewFile(null)}>
                  {t('common.close')}
                </Button>
              </header>
              {previewFile.truncated ? (
                <Text size="1" color="amber">
                  {t('sandbox.filePreviewTruncated')}
                </Text>
              ) : null}
              <pre tabIndex={0}>{previewFile.content}</pre>
            </section>
          ) : null}
        </div>
      ) : (
        <Text role="alert">{t('sandbox.filesUnavailableDescription')}</Text>
      )}
    </section>
  );
}

async function downloadSandboxFile(file: SandboxFileDownload): Promise<void> {
  const result = await saveBlobWithDesktopDialog({
    suggestedName: file.filename,
    mimeType: file.mime_type || file.bytes.type || 'application/octet-stream',
    blob: file.bytes,
  });
  if (result.status === 'cancelled') return;
}
