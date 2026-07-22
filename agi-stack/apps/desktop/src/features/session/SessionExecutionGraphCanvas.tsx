import { useState } from 'react';
import { Badge } from '@radix-ui/themes';
import {
  ArrowRightIcon,
  CheckCircledIcon,
  CrossCircledIcon,
  ExternalLinkIcon,
  FileTextIcon,
  MinusCircledIcon,
  Share2Icon,
  UpdateIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  SessionExecutionGraphModel,
  SessionExecutionGraphNode,
  SessionExecutionGraphNodeStatus,
  SessionExecutionGraphRun,
  SessionExecutionGraphRunStatus,
} from './sessionExecutionGraphModel';
import './SessionExecutionGraphCanvas.css';

export function SessionExecutionGraphCanvas({
  model,
  onOpenSession,
}: {
  model: SessionExecutionGraphModel;
  onOpenSession?: (sessionId: string) => void;
}) {
  const { t } = useI18n();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const run = model.activeRun;

  if (!run) {
    return (
      <section
        className="session-execution-graph-canvas is-empty"
        aria-label={t('session.canvasGraph')}
      >
        <Share2Icon aria-hidden="true" />
        <strong>{t('session.graph.emptyTitle')}</strong>
        <p>{t('session.graph.emptyDescription')}</p>
      </section>
    );
  }

  const selectedNode = run.nodes.find((node) => node.nodeId === selectedNodeId) ?? null;
  const runDetail = run.errorMessage ?? run.cancelReason;

  return (
    <section className="session-execution-graph-canvas" aria-label={t('session.canvasGraph')}>
      <header className="session-execution-graph-header">
        <span className="session-execution-graph-heading-icon" aria-hidden="true">
          <Share2Icon />
        </span>
        <span>
          <small>{t('session.graph.title')}</small>
          <strong>{run.graphName}</strong>
          {run.pattern ? <em>{run.pattern}</em> : null}
        </span>
        <span className={`session-execution-graph-run-status status-${run.status}`}>
          <GraphRunStatusIcon status={run.status} />
          <strong>{t(`session.graph.runStatus.${run.status}`)}</strong>
          <small>{formatDuration(run.durationSeconds, t('session.graph.durationUnknown'))}</small>
        </span>
      </header>

      {runDetail ? (
        <p className={`session-execution-graph-run-detail status-${run.status}`}>{runDetail}</p>
      ) : null}

      <div className="session-execution-graph-summary" aria-label={t('session.graph.summary')}>
        <GraphSummaryMetric status="running" count={model.summary.running} />
        <GraphSummaryMetric status="completed" count={model.summary.completed} />
        <GraphSummaryMetric status="failed" count={model.summary.failed} />
        <GraphSummaryMetric status="skipped" count={model.summary.skipped} />
      </div>

      <div className="session-execution-graph-flow" aria-label={t('session.graph.nodes')}>
        <div className={`session-execution-graph-root status-${run.status}`}>
          <Share2Icon aria-hidden="true" />
          <span>
            <strong>{run.graphName}</strong>
            <small>
              {t('session.graph.rootSummary', {
                nodes: run.nodes.length,
                handoffs: run.handoffs.length,
              })}
            </small>
          </span>
        </div>
        {run.layers.map((layer, layerIndex) => (
          <GraphLayer
            run={run}
            layer={layer}
            layerIndex={layerIndex}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            onOpenSession={onOpenSession}
            key={`${run.graphRunId}:layer:${String(layerIndex)}`}
          />
        ))}
      </div>

      {selectedNode ? (
        <GraphNodeDetail node={selectedNode} onOpenSession={onOpenSession} />
      ) : null}

      {run.handoffs.length ? (
        <section className="session-execution-graph-handoffs" aria-label={t('session.graph.handoffs')}>
          <header>
            <Share2Icon aria-hidden="true" />
            <strong>{t('session.graph.handoffs')}</strong>
            <Badge color="cyan" variant="soft">
              {run.handoffs.length}
            </Badge>
          </header>
          <ol>
            {run.handoffs.map((handoff) => (
              <li key={handoff.id}>
                <span>
                  <strong>{handoff.fromLabel}</strong>
                  <ArrowRightIcon aria-hidden="true" />
                  <strong>{handoff.toLabel}</strong>
                </span>
                {handoff.contextSummary ? <small>{handoff.contextSummary}</small> : null}
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </section>
  );
}

function GraphLayer({
  run,
  layer,
  layerIndex,
  selectedNodeId,
  onSelectNode,
  onOpenSession,
}: {
  run: SessionExecutionGraphRun;
  layer: SessionExecutionGraphNode[];
  layerIndex: number;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
  onOpenSession?: (sessionId: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="session-execution-graph-layer">
      <span className="session-execution-graph-connector" aria-hidden="true">
        <ArrowRightIcon />
      </span>
      <div
        className="session-execution-graph-layer-nodes"
        role="list"
        aria-label={t('session.graph.layer', { count: layerIndex + 1 })}
      >
        {layer.map((node) => {
          const selected = selectedNodeId === node.nodeId;
          const sessionId = node.agentSessionId;
          const isEntry = run.entryNodeIds.includes(node.nodeId);
          return (
            <article
              className={`session-execution-graph-node status-${node.status}${selected ? ' is-selected' : ''}`}
              role="listitem"
              key={node.nodeId}
            >
              <button
                type="button"
                className="session-execution-graph-node-select"
                aria-pressed={selected}
                onClick={() => onSelectNode(node.nodeId)}
              >
                <span className="session-execution-graph-node-icon" aria-hidden="true">
                  <GraphNodeStatusIcon status={node.status} />
                </span>
                <span className="session-execution-graph-node-copy">
                  <span>
                    <strong>{node.label}</strong>
                    {isEntry ? <em>{t('session.graph.entry')}</em> : null}
                  </span>
                  <small>{node.agentDefinitionId}</small>
                  <span>
                    {t(`session.graph.nodeStatus.${node.status}`)}
                    {node.durationSeconds == null
                      ? ''
                      : ` · ${formatDuration(node.durationSeconds, '')}`}
                  </span>
                </span>
              </button>
              {sessionId && onOpenSession ? (
                <button
                  type="button"
                  className="session-execution-graph-open-session"
                  aria-label={t('session.graph.openSessionFor', { node: node.label })}
                  onClick={() => onOpenSession(sessionId)}
                >
                  <ExternalLinkIcon aria-hidden="true" />
                </button>
              ) : null}
            </article>
          );
        })}
      </div>
    </div>
  );
}

function GraphNodeDetail({
  node,
  onOpenSession,
}: {
  node: SessionExecutionGraphNode;
  onOpenSession?: (sessionId: string) => void;
}) {
  const { t } = useI18n();
  const detail = node.errorMessage ?? node.skipReason;
  const sessionId = node.agentSessionId;
  return (
    <section className={`session-execution-graph-node-detail status-${node.status}`}>
      <header>
        <GraphNodeStatusIcon status={node.status} />
        <span>
          <strong>{node.label}</strong>
          <small>{node.agentDefinitionId}</small>
        </span>
        {sessionId && onOpenSession ? (
          <button type="button" onClick={() => onOpenSession(sessionId)}>
            <ExternalLinkIcon aria-hidden="true" />
            {t('session.graph.openSession')}
          </button>
        ) : null}
      </header>
      {detail ? <p>{detail}</p> : null}
      {node.outputKeys.length ? (
        <ul aria-label={t('session.graph.outputs')}>
          {node.outputKeys.map((outputKey) => (
            <li key={outputKey}>
              <FileTextIcon aria-hidden="true" />
              {outputKey}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function GraphSummaryMetric({
  status,
  count,
}: {
  status: SessionExecutionGraphNodeStatus;
  count: number;
}) {
  const { t } = useI18n();
  return (
    <span className={`status-${status}`}>
      <GraphNodeStatusIcon status={status} />
      <strong>{count}</strong>
      <small>{t(`session.graph.nodeStatus.${status}`)}</small>
    </span>
  );
}

function GraphRunStatusIcon({ status }: { status: SessionExecutionGraphRunStatus }) {
  if (status === 'running') return <UpdateIcon />;
  if (status === 'completed') return <CheckCircledIcon />;
  if (status === 'failed') return <CrossCircledIcon />;
  return <MinusCircledIcon />;
}

function GraphNodeStatusIcon({ status }: { status: SessionExecutionGraphNodeStatus }) {
  if (status === 'running') return <UpdateIcon />;
  if (status === 'completed') return <CheckCircledIcon />;
  if (status === 'failed') return <CrossCircledIcon />;
  return <MinusCircledIcon />;
}

function formatDuration(seconds: number | null, fallback: string): string {
  if (seconds == null) return fallback;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${String(Math.floor(seconds / 60))}m ${String(Math.round(seconds % 60))}s`;
}
