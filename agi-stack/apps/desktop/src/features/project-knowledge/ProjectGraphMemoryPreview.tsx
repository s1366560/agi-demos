import { useLayoutEffect, useMemo, useSyncExternalStore } from 'react';
import { useI18n } from '../../i18n';
import { useCloudMemoryRouteBinding } from './CloudMemoryRouteContext';
import { createProjectGraphMemoryReader } from './projectGraphMemoryReader';
import type { ProjectKnowledgeScope } from './projectKnowledgeClient';

export function ProjectGraphMemoryPreview({
  scope,
  contextRevision,
  memoryId,
}: Readonly<{
  scope: ProjectKnowledgeScope;
  contextRevision: number | null;
  memoryId: string;
}>) {
  const { t } = useI18n();
  const binding = useCloudMemoryRouteBinding();
  const reader = useMemo(
    () => createProjectGraphMemoryReader({ binding, scope, contextRevision, memoryId }),
    [binding, scope.authority, scope.tenantId, scope.projectId, contextRevision, memoryId],
  );
  const model = useSyncExternalStore(reader.subscribe, reader.getSnapshot, reader.getSnapshot);
  useLayoutEffect(() => {
    reader.activate();
    return reader.stop;
  }, [reader]);
  return (
    <section className="project-graph-current-memory" aria-label={t('projectGraph.currentMemory')}>
      <h4>{t('projectGraph.currentMemory')}</h4>
      <p>{t('projectGraph.currentMemoryHelp')}</p>
      <code>{memoryId}</code>
      {model.state === 'unavailable' ? (
        <p role="status">{t('projectGraph.memoryUnavailable')}</p>
      ) : (
        <button
          type="button"
          onClick={() => void reader.load()}
          disabled={model.state === 'loading'}
        >
          {t('projectGraph.readCurrentMemory')}
        </button>
      )}
      {model.state === 'loading' ? <p role="status">{t('projectGraph.loadingSource')}</p> : null}
      {model.memory ? (
        <article>
          <h5>{model.memory.title}</h5>
          <p>
            {t('cloudMemories.revision')}: {model.memory.version}
          </p>
          <div className="project-graph-content">{model.memory.content}</div>
        </article>
      ) : null}
    </section>
  );
}
