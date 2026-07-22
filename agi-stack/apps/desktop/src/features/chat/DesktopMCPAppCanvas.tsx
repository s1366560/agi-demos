import React, { Component, Suspense, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Badge, IconButton, Spinner, Tooltip } from '@radix-ui/themes';
import { Cross2Icon, CubeIcon, ExclamationTriangleIcon } from '@radix-ui/react-icons';
import type { AppRendererProps, SandboxConfig } from '@mcp-ui/client';

import { useI18n } from '../../i18n';
import type { MCPAppCanvasState, MCPAppCanvasTab } from './mcpAppCanvasEventModel';
import './DesktopMCPAppCanvas.css';

const LazyAppRenderer = React.lazy(async () => {
  const module = await import('@mcp-ui/client');
  return { default: module.AppRenderer };
});

type DesktopMCPAppCanvasProps = {
  state: MCPAppCanvasState;
  sandboxProxyUrl: string;
  onSelect: (tabId: string) => void;
  onClose: (tabId: string) => void;
};

type RendererBoundaryProps = {
  children: ReactNode;
  fallback: ReactNode;
  resetKey: string;
};

type RendererBoundaryState = { failed: boolean };

class MCPAppRendererBoundary extends Component<RendererBoundaryProps, RendererBoundaryState> {
  state: RendererBoundaryState = { failed: false };

  static getDerivedStateFromError(): RendererBoundaryState {
    return { failed: true };
  }

  componentDidUpdate(previous: RendererBoundaryProps) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export function DesktopMCPAppCanvas({
  state,
  sandboxProxyUrl,
  onSelect,
  onClose,
}: DesktopMCPAppCanvasProps) {
  const { t } = useI18n();
  const active =
    state.tabs.find((candidate) => candidate.id === state.activeTabId) ??
    state.tabs[state.tabs.length - 1];
  const [renderError, setRenderError] = useState<string | null>(null);
  const [frameHeight, setFrameHeight] = useState(420);
  const sandboxConfig = useMemo(
    () => buildSandboxConfig(sandboxProxyUrl, active?.uiMetadata),
    [active?.uiMetadata, sandboxProxyUrl],
  );

  useEffect(() => {
    setRenderError(null);
    setFrameHeight(420);
  }, [active?.id]);

  if (!active) return null;
  const title = active.title || active.toolName || t('mcpApp.untitled');
  const errorFallback = (
    <div className="desktop-mcp-app-error" role="alert">
      <ExclamationTriangleIcon aria-hidden="true" />
      <span>
        <strong>{t('mcpApp.rendererError')}</strong>
        <small>{renderError ?? t('mcpApp.rendererErrorDescription')}</small>
      </span>
    </div>
  );

  return (
    <section className="desktop-mcp-app-canvas" aria-label={t('mcpApp.canvas')}>
      <header>
        <span>
          <CubeIcon aria-hidden="true" />
          <span>
            <strong>{title}</strong>
            <small>{t('mcpApp.canvasDescription')}</small>
          </span>
        </span>
        <Badge color="violet" variant="soft">
          {active.serverName || active.toolName || t('mcpApp.plugin')}
        </Badge>
      </header>
      <nav role="tablist" aria-label={t('mcpApp.tabs')}>
        {state.tabs.map((tab) => {
          const selected = tab.id === active.id;
          const tabTitle = tab.title || tab.toolName || t('mcpApp.untitled');
          return (
            <span className={selected ? 'selected' : ''} key={tab.id}>
              <button
                type="button"
                role="tab"
                aria-selected={selected}
                tabIndex={selected ? 0 : -1}
                onClick={() => onSelect(tab.id)}
              >
                {tabTitle}
              </button>
              <Tooltip content={t('mcpApp.closeTab', { title: tabTitle })}>
                <IconButton
                  type="button"
                  size="1"
                  variant="ghost"
                  color="gray"
                  aria-label={t('mcpApp.closeTab', { title: tabTitle })}
                  onClick={() => onClose(tab.id)}
                >
                  <Cross2Icon />
                </IconButton>
              </Tooltip>
            </span>
          );
        })}
      </nav>
      <article
        className="desktop-mcp-app-frame"
        aria-label={t('mcpApp.content', { title })}
        style={{ minHeight: frameHeight }}
      >
        {renderError ? (
          errorFallback
        ) : (
          <MCPAppRendererBoundary fallback={errorFallback} resetKey={active.id}>
            <Suspense
              fallback={
                <div className="desktop-mcp-app-loading" role="status">
                  <Spinner /> {t('mcpApp.loading')}
                </div>
              }
            >
              <LazyAppRenderer
                toolName={active.toolName || active.appId || 'mcp-app'}
                sandbox={sandboxConfig}
                {...(active.resourceHtml ? { html: active.resourceHtml } : {})}
                {...(active.resourceUri ? { toolResourceUri: active.resourceUri } : {})}
                {...(active.toolInput ? { toolInput: active.toolInput } : {})}
                {...(active.toolResult !== undefined
                  ? { toolResult: toCallToolResult(active.toolResult) }
                  : {})}
                onSizeChanged={({ height }) => {
                  if (typeof height !== 'number' || !Number.isFinite(height)) return;
                  setFrameHeight(Math.min(900, Math.max(240, height)));
                }}
                onError={(error) => setRenderError(error.message)}
              />
            </Suspense>
          </MCPAppRendererBoundary>
        )}
      </article>
    </section>
  );
}

function buildSandboxConfig(
  proxyUrl: string,
  uiMetadata: MCPAppCanvasTab['uiMetadata'] | undefined,
): SandboxConfig {
  let url: URL;
  try {
    url = new URL(proxyUrl);
  } catch {
    url = new URL(window.location.href);
  }
  const config: SandboxConfig = {
    url,
    permissions: 'allow-scripts allow-same-origin allow-forms',
  };
  const csp = recordValue(uiMetadata?.csp);
  if (!csp) return config;
  const connectDomains = stringArray(csp.connectDomains);
  const resourceDomains = stringArray(csp.resourceDomains);
  return {
    ...config,
    csp: {
      ...(connectDomains ? { connectDomains } : {}),
      ...(resourceDomains ? { resourceDomains } : {}),
    },
  };
}

function toCallToolResult(value: unknown): NonNullable<AppRendererProps['toolResult']> {
  const record = recordValue(value);
  if (record && Array.isArray(record.content)) {
    return value as NonNullable<AppRendererProps['toolResult']>;
  }
  let text: string;
  if (typeof value === 'string') {
    text = value;
  } else {
    try {
      text = JSON.stringify(value, null, 2) ?? '';
    } catch {
      text = String(value);
    }
  }
  const structuredContent = recordValue(record?.structuredContent);
  return {
    content: [{ type: 'text', text }],
    ...(structuredContent ? { structuredContent } : {}),
  };
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringArray(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((item) => typeof item === 'string') ? value : null;
}
