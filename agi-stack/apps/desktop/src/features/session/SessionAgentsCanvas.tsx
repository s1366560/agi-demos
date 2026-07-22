import { useState } from 'react';
import type { CSSProperties } from 'react';
import { Badge } from '@radix-ui/themes';
import {
  ChatBubbleIcon,
  CheckCircledIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CrossCircledIcon,
  ExternalLinkIcon,
  PersonIcon,
  StopIcon,
  UpdateIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  SessionAgentNode,
  SessionAgentStatus,
  SessionAgentTreeModel,
} from './sessionAgentTreeModel';
import './SessionAgentsCanvas.css';

export function SessionAgentsCanvas({
  model,
  onOpenSession,
}: {
  model: SessionAgentTreeModel;
  onOpenSession?: (sessionId: string) => void;
}) {
  const { t } = useI18n();
  const [expandedNodes, setExpandedNodes] = useState<Record<string, boolean>>({});

  if (model.summary.total === 0) {
    return (
      <section className="session-agent-tree-canvas is-empty" aria-label={t('session.canvasAgents')}>
        <PersonIcon aria-hidden="true" />
        <strong>{t('session.agents.emptyTitle')}</strong>
        <p>{t('session.agents.emptyDescription')}</p>
      </section>
    );
  }

  const setExpanded = (key: string, expanded: boolean) => {
    setExpandedNodes((current) => ({ ...current, [key]: expanded }));
  };

  return (
    <section className="session-agent-tree-canvas" aria-label={t('session.canvasAgents')}>
      <header className="session-agent-tree-header">
        <span className="session-agent-tree-heading-icon" aria-hidden="true">
          <PersonIcon />
        </span>
        <span>
          <strong>{t('session.agents.title')}</strong>
          <small>{t('session.agents.description')}</small>
        </span>
        <Badge color="cyan" variant="soft">
          {t('session.agents.total', { count: model.summary.total })}
        </Badge>
      </header>

      <div className="session-agent-tree-summary" aria-label={t('session.agents.summary')}>
        <AgentSummaryMetric status="running" count={model.summary.running} />
        <AgentSummaryMetric status="completed" count={model.summary.completed} />
        <AgentSummaryMetric status="failed" count={model.summary.failed} />
        <AgentSummaryMetric status="stopped" count={model.summary.stopped} />
      </div>

      <div className="session-agent-tree" role="tree" aria-label={t('session.agents.hierarchy')}>
        {model.roots.map((node) => (
          <SessionAgentTreeNode
            node={node}
            depth={1}
            expandedNodes={expandedNodes}
            onExpandedChange={setExpanded}
            onOpenSession={onOpenSession}
            key={node.key}
          />
        ))}
      </div>

      {model.communications.length > 0 ? (
        <section
          className="session-agent-communications"
          aria-label={t('session.agents.communications')}
        >
          <header>
            <ChatBubbleIcon aria-hidden="true" />
            <strong>{t('session.agents.communications')}</strong>
            <span>{model.summary.communications}</span>
          </header>
          <ol>
            {model.communications.slice(-12).map((communication) => (
              <li key={communication.id}>
                <span aria-hidden="true">{communication.type === 'sent' ? '↗' : '↙'}</span>
                <p>
                  <strong>
                    {communication.fromLabel} → {communication.toLabel}
                  </strong>
                  <small>{communication.preview}</small>
                </p>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </section>
  );
}

function SessionAgentTreeNode({
  node,
  depth,
  expandedNodes,
  onExpandedChange,
  onOpenSession,
}: {
  node: SessionAgentNode;
  depth: number;
  expandedNodes: Readonly<Record<string, boolean>>;
  onExpandedChange: (key: string, expanded: boolean) => void;
  onOpenSession?: (sessionId: string) => void;
}) {
  const { t } = useI18n();
  const hasChildren = node.children.length > 0;
  const expanded = expandedNodes[node.key] ?? true;
  const label = node.name ?? node.agentId;
  const detail = node.result ?? node.stopReason ?? node.taskSummary;
  const sessionId = node.sessionId;

  return (
    <article
      className={`session-agent-tree-node status-${node.status}`}
      role="treeitem"
      aria-level={depth}
      aria-expanded={hasChildren ? expanded : undefined}
    >
      <div
        className="session-agent-tree-row"
        style={{ '--agent-tree-indent': `${Math.max(0, depth - 1) * 14}px` } as CSSProperties}
      >
        {hasChildren ? (
          <button
            type="button"
            className="session-agent-tree-toggle"
            aria-label={t(expanded ? 'session.agents.collapseChildren' : 'session.agents.expandChildren', {
              agent: label,
            })}
            aria-expanded={expanded}
            onClick={() => onExpandedChange(node.key, !expanded)}
          >
            {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
          </button>
        ) : (
          <span className="session-agent-tree-leaf" aria-hidden="true" />
        )}
        <span className="session-agent-tree-node-icon" aria-hidden="true">
          <AgentStatusIcon status={node.status} />
        </span>
        <span className="session-agent-tree-copy">
          <span>
            <strong>{label}</strong>
            <em>{t(`session.agents.status.${node.status}`)}</em>
          </span>
          {node.taskSummary ? <small>{node.taskSummary}</small> : null}
          {detail && detail !== node.taskSummary ? <p>{detail}</p> : null}
          {node.artifacts.length ? (
            <small>{t('session.agents.artifacts', { count: node.artifacts.length })}</small>
          ) : null}
        </span>
        {sessionId && onOpenSession ? (
          <button
            type="button"
            className="session-agent-open-session"
            aria-label={t('session.agents.openSessionFor', { agent: label })}
            onClick={() => onOpenSession(sessionId)}
          >
            <ExternalLinkIcon aria-hidden="true" />
            {t('session.agents.openSession')}
          </button>
        ) : null}
      </div>
      {hasChildren && expanded ? (
        <div className="session-agent-tree-children" role="group">
          {node.children.map((child) => (
            <SessionAgentTreeNode
              node={child}
              depth={depth + 1}
              expandedNodes={expandedNodes}
              onExpandedChange={onExpandedChange}
              onOpenSession={onOpenSession}
              key={child.key}
            />
          ))}
        </div>
      ) : null}
    </article>
  );
}

function AgentSummaryMetric({ status, count }: { status: SessionAgentStatus; count: number }) {
  const { t } = useI18n();
  return (
    <span className={`status-${status}`}>
      <AgentStatusIcon status={status} />
      <strong>{count}</strong>
      <small>{t(`session.agents.status.${status}`)}</small>
    </span>
  );
}

function AgentStatusIcon({ status }: { status: SessionAgentStatus }) {
  if (status === 'running') return <UpdateIcon />;
  if (status === 'completed') return <CheckCircledIcon />;
  if (status === 'failed') return <CrossCircledIcon />;
  return <StopIcon />;
}
