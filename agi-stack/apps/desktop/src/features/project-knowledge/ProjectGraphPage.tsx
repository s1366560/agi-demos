import { useMemo, useState } from 'react';
import { useI18n } from '../../i18n';
import type { ProjectGraphController } from './projectGraphController';
import type { ProjectGraphViewModel } from './projectGraphPresentationModel';
import { projectGraphAdjacentEdges, projectGraphSourceUuids } from './projectGraphNavigation';
import { ProjectGraphMemoryPreview } from './ProjectGraphMemoryPreview';
import type { ProjectGraphNode } from './projectGraphClient';

export function ProjectGraphPage({
  model,
  controller,
}: Readonly<{
  model: ProjectGraphViewModel;
  controller: ProjectGraphController;
}>) {
  const { t } = useI18n();
  const [filter, setFilter] = useState('');
  const nodes = model.nodes ?? [];
  const edges = model.edges ?? [];
  const byId = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const selectedNode = model.selection?.kind === 'node' ? byId.get(model.selection.id) : undefined;
  const selectedEdge =
    model.selection?.kind === 'edge'
      ? edges.find((edge) => edge.id === model.selection!.id)
      : undefined;
  const adjacent = selectedNode ? projectGraphAdjacentEdges(model, selectedNode.id) : edges;
  const sourceUuids = projectGraphSourceUuids(model, model.selection ?? null);
  const query = filter.toLocaleLowerCase();
  const visibleNodes = nodes.filter((node) =>
    [node.name, node.id, node.uuid ?? ''].some((value) =>
      value.toLocaleLowerCase().includes(query),
    ),
  );
  const readable = model.scope.authority === 'cloud' && model.allowedActions.includes('view');
  const endpoint = (id: string) => (
    <button type="button" onClick={() => controller.selectNode(id)}>
      {byId.get(id)?.name ?? id}
      <small>{byId.get(id)?.uuid ?? id}</small>
    </button>
  );
  return (
    <section
      className="project-graph-page"
      data-route-id={model.routeId}
      data-authority={model.scope.authority}
      data-state={model.state}
      data-reason-code={model.reasonCode ?? undefined}
    >
      <header>
        <div>
          <h1>{t('projectGraph.title')}</h1>
          <p>{t('projectGraph.subtitle')}</p>
        </div>
        <button
          type="button"
          onClick={() => void controller.retry()}
          disabled={model.state === 'loading' || model.state === 'scope_switch'}
        >
          {t('common.refresh')}
        </button>
      </header>
      {model.state === 'loading' || model.state === 'scope_switch' ? (
        <p role="status">{t('projectGraph.loading')}</p>
      ) : null}
      {!readable && !['loading', 'scope_switch'].includes(model.state) ? (
        <p role="alert">
          {t(
            model.reasonCode === 'project_graph_context_changed'
              ? 'projectGraph.contextChanged'
              : 'projectGraph.unavailable',
          )}
        </p>
      ) : null}
      {readable ? (
        <>
          <div className="project-graph-summary">
            <span>
              {t('projectGraph.nodes')}: <strong>{nodes.length}</strong>
            </span>
            <span>
              {t('projectGraph.relationships')}: <strong>{edges.length}</strong>
            </span>
          </div>
          <p className="project-graph-scope-note">{t('projectGraph.partial')}</p>
          {nodes.length === 0 ? (
            <p>{t('projectGraph.empty')}</p>
          ) : (
            <div className="project-graph-layout">
              <aside className="project-graph-nodes" aria-label={t('projectGraph.nodes')}>
                <label>
                  {t('projectGraph.findNode')}
                  <input
                    type="search"
                    value={filter}
                    onChange={(event) => setFilter(event.target.value)}
                  />
                </label>
                <ul>
                  {visibleNodes.map((node) => (
                    <li key={node.id}>
                      <button
                        type="button"
                        aria-pressed={selectedNode?.id === node.id}
                        onClick={() => controller.selectNode(node.id)}
                      >
                        <strong>{node.name}</strong>
                        <span>{node.entity_type ?? node.type}</span>
                        <small>{node.uuid ?? node.id}</small>
                      </button>
                    </li>
                  ))}
                </ul>
                {visibleNodes.length === 0 ? <p>{t('projectGraph.noMatches')}</p> : null}
              </aside>
              <div className="project-graph-detail">
                {selectedNode ? (
                  <article className="project-graph-selected">
                    <h2>{selectedNode.name}</h2>
                    <p>{selectedNode.entity_type ?? selectedNode.type}</p>
                    <code>{selectedNode.uuid ?? selectedNode.id}</code>
                    {selectedNode.summary ? <p>{selectedNode.summary}</p> : null}
                    {selectedNode.type === 'Episodic' && selectedNode.content != null ? (
                      <>
                        <h3>{t('projectGraph.capturedContent')}</h3>
                        <div className="project-graph-content">{selectedNode.content}</div>
                      </>
                    ) : null}
                  </article>
                ) : selectedEdge ? (
                  <article className="project-graph-selected">
                    <h2>{selectedEdge.relationship_type ?? selectedEdge.label}</h2>
                    <div className="project-graph-edge-endpoints">
                      {endpoint(selectedEdge.source)}
                      <span aria-hidden="true">→</span>
                      {endpoint(selectedEdge.target)}
                    </div>
                    {selectedEdge.fact ? <p>{selectedEdge.fact}</p> : null}
                    <dl>
                      <dt>{t('projectGraph.relationshipId')}</dt>
                      <dd>
                        <code>{selectedEdge.uuid ?? selectedEdge.id}</code>
                      </dd>
                      {selectedEdge.valid_at ? (
                        <>
                          <dt>{t('projectGraph.validAt')}</dt>
                          <dd>{selectedEdge.valid_at}</dd>
                        </>
                      ) : null}
                      {selectedEdge.invalid_at ? (
                        <>
                          <dt>{t('projectGraph.invalidAt')}</dt>
                          <dd>{selectedEdge.invalid_at}</dd>
                        </>
                      ) : null}
                      {selectedEdge.expired_at ? (
                        <>
                          <dt>{t('projectGraph.expiredAt')}</dt>
                          <dd>{selectedEdge.expired_at}</dd>
                        </>
                      ) : null}
                    </dl>
                  </article>
                ) : (
                  <p>{t('projectGraph.selectHelp')}</p>
                )}
                <section aria-label={t('projectGraph.relationships')}>
                  <h2>
                    {selectedNode ? t('projectGraph.adjacent') : t('projectGraph.relationships')}
                  </h2>
                  {adjacent.length === 0 ? (
                    <p>{t('projectGraph.noRelationships')}</p>
                  ) : (
                    <div className="project-graph-edge-list">
                      <table>
                        <thead>
                          <tr>
                            <th>{t('projectGraph.from')}</th>
                            <th>{t('projectGraph.relationship')}</th>
                            <th>{t('projectGraph.to')}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {adjacent.map((edge) => (
                            <tr key={edge.id} aria-selected={selectedEdge?.id === edge.id}>
                              <td>{endpoint(edge.source)}</td>
                              <td>
                                <button
                                  type="button"
                                  onClick={() => controller.selectEdge(edge.id)}
                                >
                                  {edge.relationship_type ?? edge.label}
                                  <small>{edge.fact ?? edge.uuid ?? edge.id}</small>
                                </button>
                              </td>
                              <td>{endpoint(edge.target)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
                {model.selection ? (
                  <section className="project-graph-sources" aria-label={t('projectGraph.sources')}>
                    <h2>{t('projectGraph.sources')}</h2>
                    <p>{t('projectGraph.sourceHelp')}</p>
                    {sourceUuids.length === 0 ? (
                      <p>{t('projectGraph.noSources')}</p>
                    ) : (
                      <ul>
                        {sourceUuids.map((uuid) => (
                          <li key={uuid}>
                            <button
                              type="button"
                              aria-pressed={model.sourceUuid === uuid}
                              onClick={() => void controller.openSource(uuid)}
                            >
                              {nodes.find((node) => node.uuid === uuid)?.name ??
                                t('projectGraph.episode')}
                              <small>{uuid}</small>
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                    {model.sourceState === 'loading' ? (
                      <p role="status">{t('projectGraph.loadingSource')}</p>
                    ) : null}
                    {model.sourceState === 'error' ||
                    (model.sourceState === 'ready' && !model.source) ? (
                      <p role="status">{t('projectGraph.sourceUnavailable')}</p>
                    ) : null}
                    {model.source ? (
                      <ProjectGraphSourceDetails
                        key={model.sourceUuid}
                        source={model.source}
                        model={model}
                      />
                    ) : null}
                  </section>
                ) : null}
              </div>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
function ProjectGraphSourceDetails({
  source,
  model,
}: Readonly<{ source: ProjectGraphNode; model: ProjectGraphViewModel }>) {
  const { t } = useI18n();
  return (
    <article className="project-graph-source">
      <h3>{source.name}</h3>
      <code>{source.uuid}</code>
      <dl>
        {source.source_description ? (
          <>
            <dt>{t('projectGraph.sourceType')}</dt>
            <dd>{source.source_description}</dd>
          </>
        ) : null}
        {source.created_at ? (
          <>
            <dt>{t('projectGraph.createdAt')}</dt>
            <dd>{source.created_at}</dd>
          </>
        ) : null}
        {source.valid_at ? (
          <>
            <dt>{t('projectGraph.validAt')}</dt>
            <dd>{source.valid_at}</dd>
          </>
        ) : null}
      </dl>
      <h4>{t('projectGraph.capturedContent')}</h4>
      <p>{t('projectGraph.capturedHelp')}</p>
      <div className="project-graph-content">
        {source.content ?? t('projectGraph.noCapturedContent')}
      </div>
      {source.memory_id ? (
        <ProjectGraphMemoryPreview
          scope={model.scope}
          contextRevision={model.scopeRevision}
          memoryId={source.memory_id}
        />
      ) : (
        <p>{t('projectGraph.noMemory')}</p>
      )}
    </article>
  );
}
