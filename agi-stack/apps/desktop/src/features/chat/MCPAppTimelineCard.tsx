import {
  ArrowTopRightIcon,
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CodeIcon,
  CubeIcon,
  ExclamationTriangleIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  MCPAppTimelineGroup,
  MCPAppTimelineStatus,
} from './mcpAppTimelineModel';

export function MCPAppTimelineCard({
  app,
  expanded,
  onToggle,
  onOpen,
  anchorId,
}: {
  app: MCPAppTimelineGroup;
  expanded: boolean;
  onToggle: () => void;
  onOpen: (() => void) | undefined;
  anchorId: string;
}) {
  const { t } = useI18n();
  const title = app.title || app.toolName || app.appId || t('chat.mcpAppUnnamed');
  const facts = structuredFacts(app.structuredContent);
  const input = formatEvidence(app.toolInput);
  const output = formatEvidence(app.toolResult);
  const structured = formatEvidence(app.structuredContent);

  return (
    <article
      className="mcp-app-timeline-card"
      data-status={app.status}
      data-timeline-anchor-id={anchorId}
      data-timeline-anchor-members={JSON.stringify(app.itemIds)}
    >
      <div className="mcp-app-timeline-header">
        <button
          type="button"
          className="mcp-app-timeline-toggle"
          aria-expanded={expanded}
          aria-label={t(expanded ? 'chat.collapseItem' : 'chat.expandItem', { item: title })}
          onClick={onToggle}
        >
          <span className="mcp-app-timeline-chevron" aria-hidden="true">
            {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
          </span>
          <span className="mcp-app-timeline-icon" aria-hidden="true">
            <MCPAppStatusIcon status={app.status} />
          </span>
          <span className="mcp-app-timeline-copy">
            <strong>{t('chat.mcpAppTimelineTitle', { title })}</strong>
            <small>{app.serverName || t('chat.mcpAppUnknownServer')}</small>
          </span>
          <span className="mcp-app-timeline-metrics">
            {app.source ? <span>{t(`chat.mcpAppSource.${sourceKey(app.source)}`)}</span> : null}
            <em className={`timeline-status ${statusTone(app.status)}`}>
              {t(`chat.mcpAppStatus.${app.status}`)}
            </em>
          </span>
        </button>
        {app.interactive && app.resultItem && onOpen ? (
          <button type="button" className="mcp-app-open-action" onClick={onOpen}>
            <ArrowTopRightIcon aria-hidden="true" />
            {t('chat.mcpAppOpen')}
          </button>
        ) : null}
      </div>
      {expanded ? (
        <div className="mcp-app-timeline-body">
          <dl className="mcp-app-identity-facts">
            {app.toolName ? (
              <div>
                <dt>{t('chat.mcpAppTool')}</dt>
                <dd>
                  <CodeIcon aria-hidden="true" />
                  {app.toolName}
                </dd>
              </div>
            ) : null}
            {app.resourceUri ? (
              <div>
                <dt>{t('chat.mcpAppResource')}</dt>
                <dd>{app.resourceUri}</dd>
              </div>
            ) : null}
            {app.appId ? (
              <div>
                <dt>{t('chat.mcpAppIdentity')}</dt>
                <dd>{app.appId}</dd>
              </div>
            ) : null}
          </dl>
          {facts.length ? (
            <section
              className="mcp-app-structured-content"
              aria-label={t('chat.mcpAppStructuredResult')}
            >
              <span>{t('chat.mcpAppStructuredResult')}</span>
              <dl>
                {facts.map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}
          {input || output || structured ? (
            <div className="mcp-app-event-evidence">
              <MCPAppEvidence label={t('chat.mcpAppInput')} value={input} />
              <MCPAppEvidence label={t('chat.mcpAppOutput')} value={output} />
              <MCPAppEvidence label={t('chat.mcpAppStructuredData')} value={structured} />
            </div>
          ) : null}
          {app.error ? <p className="mcp-app-timeline-error">{app.error}</p> : null}
          {app.interactive ? (
            <p className="mcp-app-sandbox-note">{t('chat.mcpAppSandboxNote')}</p>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function MCPAppEvidence({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <details>
      <summary>{label}</summary>
      <pre>{value}</pre>
    </details>
  );
}

function MCPAppStatusIcon({ status }: { status: MCPAppTimelineStatus }) {
  if (status === 'error') return <ExclamationTriangleIcon />;
  if (status === 'ready') return <CheckIcon />;
  return <CubeIcon />;
}

function statusTone(status: MCPAppTimelineStatus): 'ok' | 'error' | 'waiting' {
  if (status === 'ready') return 'ok';
  if (status === 'error') return 'error';
  return 'waiting';
}

function sourceKey(source: string): 'agent' | 'user' | 'other' {
  const normalized = source.toLowerCase();
  if (normalized === 'agent_developed') return 'agent';
  if (normalized === 'user_added') return 'user';
  return 'other';
}

function structuredFacts(value: unknown): Array<[string, string]> {
  if (!isRecord(value)) return [];
  return Object.entries(value)
    .flatMap(([key, entry]) => {
      if (typeof entry === 'string' || typeof entry === 'number' || typeof entry === 'boolean') {
        return [[humanizeKey(key), String(entry)] as [string, string]];
      }
      return [];
    })
    .slice(0, 8);
}

function humanizeKey(value: string): string {
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatEvidence(value: unknown): string {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
