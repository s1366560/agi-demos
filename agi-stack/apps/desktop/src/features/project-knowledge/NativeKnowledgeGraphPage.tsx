import { nativeKnowledgeGraphPresentation } from './nativeKnowledgeGraphPresentation';
import { useId, useLayoutEffect, useRef, useState } from 'react';
import { useI18n } from '../../i18n';
import type {
  NativeKnowledgeGraphController,
  NativeKnowledgeGraphModel,
} from './nativeKnowledgeGraphController';

export function NativeKnowledgeGraphPage({
  model,
  controller,
}: Readonly<{
  model: NativeKnowledgeGraphModel;
  controller: NativeKnowledgeGraphController;
}>) {
  const { t } = useI18n();
  const graph = model.graph;
  const arrowId = useId();
  const [literal, setLiteral] = useState('');
  const nodeElements = useRef(new Map<number, SVGGElement>());
  useLayoutEffect(() => {
    if (model.selectedNode !== null)
      nodeElements.current
        .get(model.selectedNode)
        ?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [model.selectedNode]);
  const locate = (index: number) => {
    controller.selectNode(index);
    nodeElements.current.get(index)?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    nodeElements.current.get(index)?.focus();
  };
  const { visibleNodes, visibleEdges, visibleIndexes } = nativeKnowledgeGraphPresentation(
    graph,
    literal,
    model.selectedNode,
  );
  const positions = new Map(
    visibleIndexes.map((index, position) => [
      index,
      { x: 90 + (position % 5) * 175, y: 65 + Math.floor(position / 5) * 110 },
    ]),
  );
  const busy = model.phase === 'loading';
  const sourceKeys = new Set<string>();
  const sources = model.sources.filter((row) => {
    const source = row.reference.source;
    const key = JSON.stringify([
      source.tenant_id,
      source.project_id,
      source.memory_id,
      source.revision,
      source.change_sequence,
      row.audit_attempt,
    ]);
    if (sourceKeys.has(key)) return false;
    sourceKeys.add(key);
    return true;
  });
  return (
    <section className="project-graph-page" data-native-knowledge-graph="true" aria-busy={busy}>
      <h1>{t('nativeGraph.title')}</h1>
      <p>{t('nativeGraph.explanation')}</p>
      <button
        disabled={busy || model.phase === 'unavailable'}
        onClick={() => void controller.refresh()}
      >
        {t('nativeGraph.refresh')}
      </button>
      {model.phase === 'unavailable' && <p role="status">{t('nativeGraph.unavailable')}</p>}
      {model.error && <p role="alert">{t(`nativeGraph.error.${model.error}`)}</p>}
      <h2>{t('nativeGraph.sources')}</h2>
      <p>{t('nativeGraph.catalog')}</p>
      {!sources.length && model.phase === 'ready' && <p>{t('nativeGraph.noSources')}</p>}
      <ul>
        {sources.map((row) => (
          <li key={JSON.stringify([row.reference.source, row.audit_attempt])}>
            <button disabled={busy} onClick={() => void controller.open(row)}>
              {row.reference.source.memory_id} · {t('nativeGraph.revision')}{' '}
              {row.reference.source.revision} · {t('nativeGraph.attempt')} {row.audit_attempt}
            </button>
          </li>
        ))}
      </ul>
      {model.nextCursor && (
        <button disabled={busy} onClick={() => void controller.nextPage()}>
          {t('nativeGraph.more')}
        </button>
      )}
      {graph && (
        <article>
          <h2>{graph.title}</h2>
          <p>
            {t('nativeGraph.complete')} · {t('nativeGraph.revision')} {graph.source.revision} ·{' '}
            {t('nativeGraph.attempt')} {graph.audit_attempt}
          </p>
          <label>
            {t('nativeGraph.filter')}
            <input value={literal} onChange={(event) => setLiteral(event.target.value)} />
          </label>
          <p>
            {t('nativeGraph.filtered')} {visibleIndexes.length} / {graph.entities.length}
          </p>
          <div style={{ overflow: 'auto', maxHeight: 480, border: '1px solid currentColor' }}>
            <svg
              role="group"
              aria-label={t('nativeGraph.diagram')}
              width="900"
              height={Math.max(140, Math.ceil(visibleIndexes.length / 5) * 110)}
            >
              <defs>
                <marker
                  id={arrowId}
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
                </marker>
              </defs>
              {visibleEdges.map(({ edge, index }) => {
                const from = positions.get(edge.source_index)!;
                const to = positions.get(edge.target_index)!;
                const dx = to.x - from.x,
                  dy = to.y - from.y;
                const boundary = Math.min(
                  dx ? 75 / Math.abs(dx) : Infinity,
                  dy ? 25 / Math.abs(dy) : Infinity,
                );
                return (
                  <g key={index}>
                    {edge.source_index === edge.target_index ? (
                      <path
                        d={`M ${from.x - 20} ${from.y - 25} C ${from.x - 70} ${from.y - 70}, ${from.x + 70} ${from.y - 70}, ${from.x + 20} ${from.y - 25}`}
                        fill="none"
                        markerEnd={`url(#${arrowId})`}
                        stroke="currentColor"
                      />
                    ) : (
                      <line
                        x1={from.x}
                        y1={from.y}
                        x2={to.x - dx * boundary}
                        y2={to.y - dy * boundary}
                        markerEnd={`url(#${arrowId})`}
                        stroke="currentColor"
                        opacity="0.3"
                      />
                    )}
                    <title>{`${edge.relation_type}: ${edge.fact}`}</title>
                  </g>
                );
              })}
              {visibleIndexes.map((index) => {
                const position = positions.get(index)!;
                const entity = graph.entities[index]!;
                return (
                  <g
                    key={JSON.stringify([graph.source, graph.audit_attempt, index])}
                    ref={(element) => {
                      if (element) nodeElements.current.set(index, element);
                      else nodeElements.current.delete(index);
                    }}
                    role="button"
                    tabIndex={0}
                    aria-label={`#${index} ${entity.name}`}
                    aria-pressed={model.selectedNode === index}
                    onClick={() => controller.selectNode(index)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        controller.selectNode(index);
                      }
                    }}
                  >
                    <rect
                      x={position.x - 75}
                      y={position.y - 25}
                      width="150"
                      height="50"
                      rx="8"
                      fill={model.selectedNode === index ? '#dbeafe' : '#f8fafc'}
                      stroke="#475569"
                      strokeWidth={model.selectedNode === index ? 3 : 1}
                    />
                    <text
                      x={position.x}
                      y={position.y}
                      textAnchor="middle"
                      fill="#0f172a"
                      fontSize="12"
                    >
                      #{index} {entity.name.slice(0, 16)}
                    </text>
                    <title>{`${entity.name} (${entity.kind})`}</title>
                  </g>
                );
              })}
            </svg>
          </div>
          <h3>
            {t('nativeGraph.nodes')} ({graph.entities.length})
          </h3>
          {!graph.entities.length && <p>{t('nativeGraph.empty')}</p>}
          <button onClick={() => controller.selectNode(null)}>{t('nativeGraph.allEdges')}</button>
          <ul>
            {graph.entities.map(
              (entity, index) =>
                visibleNodes.has(index) && (
                  <li key={index}>
                    <button
                      aria-pressed={model.selectedNode === index}
                      onClick={() => controller.selectNode(index)}
                    >
                      #{index} {entity.name} ({entity.kind})
                    </button>
                  </li>
                ),
            )}
          </ul>
          <h3>
            {t('nativeGraph.edges')} ({graph.relationships.length})
          </h3>
          <table>
            <thead>
              <tr>
                <th>{t('nativeGraph.from')}</th>
                <th>{t('nativeGraph.relation')}</th>
                <th>{t('nativeGraph.to')}</th>
                <th>{t('nativeGraph.fact')}</th>
              </tr>
            </thead>
            <tbody>
              {visibleEdges.map(({ edge, index }) => (
                <tr key={index}>
                  <td>
                    <button onClick={() => locate(edge.source_index)}>
                      #{edge.source_index} {graph.entities[edge.source_index]?.name}
                    </button>
                  </td>
                  <td>{edge.relation_type}</td>
                  <td>
                    <button onClick={() => locate(edge.target_index)}>
                      #{edge.target_index} {graph.entities[edge.target_index]?.name}
                    </button>
                  </td>
                  <td>{edge.fact}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <details>
            <summary>{t('nativeGraph.source')}</summary>
            <p style={{ whiteSpace: 'pre-wrap' }}>{graph.content}</p>
          </details>
        </article>
      )}
    </section>
  );
}
