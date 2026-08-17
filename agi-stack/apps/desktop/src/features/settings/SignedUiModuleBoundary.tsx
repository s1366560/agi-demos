import { useEffect, useMemo, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

export type SignedUiModuleBoundaryProps = {
  config: DesktopRuntimeConfig;
  pluginId: string;
  expectedDigest: string;
};

const MAX_MODULE_HTML_BYTES = 1024 * 1024;
export const SIGNED_UI_MODULE_SANDBOX = 'allow-scripts';

export function signedModuleDocument(moduleHtml: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="referrer" content="no-referrer"><title>Plugin module</title></head><body>${moduleHtml}</body></html>`;
}

export function SignedUiModuleBoundary({
  config,
  pluginId,
  expectedDigest,
}: SignedUiModuleBoundaryProps) {
  const [moduleHtml, setModuleHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const source = useMemo(() => {
    if (moduleHtml === null) return null;
    return signedModuleDocument(moduleHtml);
  }, [moduleHtml]);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    setModuleHtml(null);
    new DesktopApiClient(config)
      .getPlatformPluginFrontendModule(pluginId, controller.signal)
      .then((module) => {
        if (controller.signal.aborted) return;
        if (module.plugin_id !== pluginId || module.digest !== expectedDigest) {
          throw new Error('signed_ui_module_mismatch');
        }
        if (module.trust !== 'signed' || module.html.length > MAX_MODULE_HTML_BYTES) {
          throw new Error('signed_ui_module_rejected');
        }
        setModuleHtml(module.html);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : String(caught));
        }
      });
    return () => controller.abort();
  }, [config, expectedDigest, pluginId]);

  if (error) {
    return <p className="signed-ui-module-error">{error}</p>;
  }
  if (source === null) {
    return <p className="signed-ui-module-loading">Loading signed plugin module…</p>;
  }
  return (
    <iframe
      className="signed-ui-module-frame"
      title={`Signed plugin module ${pluginId}`}
      sandbox={SIGNED_UI_MODULE_SANDBOX}
      referrerPolicy="no-referrer"
      srcDoc={source}
    />
  );
}
