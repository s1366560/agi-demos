import { useLayoutEffect, useMemo, useSyncExternalStore } from 'react';

import type { DesktopRouteSurfaceProps } from '../navigation/desktopRouteModule';
import { NativeMemoriesPage, NativeMemoriesUnavailable } from './NativeMemoriesPage';
import {
  useNativeMemoriesRouteBinding,
  type NativeMemoriesRouteBinding,
} from './NativeMemoriesRouteContext';
import { createNativeMemoriesController } from './nativeMemoriesController';
import { createProjectMemoriesController } from './projectMemoriesController';
import { createNativeKnowledgeSyncController } from './nativeKnowledgeSyncController';
import { createNativeKnowledgeConflictController } from './nativeKnowledgeConflictController';
import { NativeKnowledgeSyncPanel } from './NativeKnowledgeSyncPanel';
import { NativeKnowledgeConflictEditor } from './NativeKnowledgeConflictEditor';
import { createNativeKnowledgeRetrievalController } from './nativeKnowledgeRetrievalController';
import { NativeKnowledgeConfigurationPanel } from './NativeKnowledgeConfigurationPanel';
import { createNativeKnowledgeProcessingController } from './nativeKnowledgeProcessingController';
import { NativeKnowledgeProcessingPanel } from './NativeKnowledgeProcessingPanel';
import {
  NativeKnowledgeRetrievalPanel,
  NativeKnowledgeRetrievalUnavailable,
} from './NativeKnowledgeRetrievalPanel';

export function NativeMemoriesRouteSurface({ context }: DesktopRouteSurfaceProps) {
  const binding = useNativeMemoriesRouteBinding();
  if (
    !binding ||
    !binding.authority.available ||
    binding.authority.scope.authority !== 'local' ||
    context.tenantId !== binding.authority.scope.tenantId ||
    context.projectId !== binding.authority.scope.projectId
  )
    return <NativeMemoriesUnavailable />;
  return <BoundNativeMemoriesRoute binding={binding} />;
}

function BoundNativeMemoriesRoute({ binding }: Readonly<{ binding: NativeMemoriesRouteBinding }>) {
  const controllers = useMemo(() => {
    const list = createProjectMemoriesController({
      authority: 'local',
      client: binding.listClient,
      initialScope: binding.authority.scope,
    });
    const editor = createNativeMemoriesController({
      client: binding.client,
      authority: binding.authority,
      onAccepted: () => {
        if (binding.authority.allowedActions.includes('list')) void list.retry();
      },
    });
    const sync = createNativeKnowledgeSyncController({
      client: binding.client,
      authority: binding.authority,
      onAccepted: () => {
        if (binding.authority.allowedActions.includes('list')) void list.retry();
      },
    });
    const conflicts = createNativeKnowledgeConflictController({
      client: binding.client,
      authority: binding.authority,
      onAccepted: () => {
        void sync.refresh();
        if (binding.authority.allowedActions.includes('list')) void list.retry();
      },
    });
    const retrieval = createNativeKnowledgeRetrievalController({
      client: binding.processingClient,
      sourceClient: binding.client,
      authority: binding.authority,
    });
    const processing = createNativeKnowledgeProcessingController({
      queryClient: binding.processingClient,
      commandClient: binding.processingCommandClient,
      authority: binding.authority,
      onAccepted: () => retrieval.refreshConfiguration(),
    });
    return { list, editor, sync, conflicts, retrieval, processing };
  }, [binding]);
  const list = useSyncExternalStore(
    controllers.list.subscribe,
    controllers.list.getSnapshot,
    controllers.list.getSnapshot,
  );
  const editor = useSyncExternalStore(
    controllers.editor.subscribe,
    controllers.editor.getSnapshot,
    controllers.editor.getSnapshot,
  );
  const sync = useSyncExternalStore(
    controllers.sync.subscribe,
    controllers.sync.getSnapshot,
    controllers.sync.getSnapshot,
  );
  const conflict = useSyncExternalStore(
    controllers.conflicts.subscribe,
    controllers.conflicts.getSnapshot,
    controllers.conflicts.getSnapshot,
  );
  const retrieval = useSyncExternalStore(
    controllers.retrieval.subscribe,
    controllers.retrieval.getSnapshot,
    controllers.retrieval.getSnapshot,
  );
  const processing = useSyncExternalStore(
    controllers.processing.subscribe,
    controllers.processing.getSnapshot,
    controllers.processing.getSnapshot,
  );
  useLayoutEffect(() => {
    controllers.editor.activate();
    controllers.sync.activate();
    controllers.conflicts.activate();
    controllers.retrieval.activate();
    controllers.processing.activate();
    void controllers.retrieval.refreshConfiguration();
    void controllers.sync.refresh();
    if (controllers.editor.getSnapshot().allowedActions.includes('list'))
      void controllers.list.load(binding.authority.scope);
    return () => {
      controllers.editor.stop();
      controllers.list.stop();
      controllers.sync.stop();
      controllers.conflicts.stop();
      controllers.retrieval.stop();
      controllers.processing.stop();
    };
  }, [binding, controllers]);
  const editorLocked = editor.phase === 'saving' || editor.phase === 'uncertain';
  const processingLocked = processing.phase === 'executing' || processing.recoveryRequired;
  const syncLocked = sync.phase === 'syncing' || sync.recoveryRequired;
  const conflictLocked = ['checking', 'saving', 'uncertain'].includes(conflict.phase);
  return (
    <>
      <fieldset
        className="native-knowledge-route-boundary"
        disabled={syncLocked || conflictLocked || processingLocked}
      >
        <NativeMemoriesPage
          list={list}
          editor={editor}
          controller={controllers.editor}
          onReload={() => {
            if (controllers.editor.getSnapshot().allowedActions.includes('list'))
              void controllers.list.retry();
          }}
          onPageChange={(page) => {
            if (controllers.editor.getSnapshot().allowedActions.includes('list'))
              void controllers.list.goToPage(page);
          }}
        />
      </fieldset>
      <NativeKnowledgeSyncPanel
        model={sync}
        controller={controllers.sync}
        conflicts={controllers.conflicts}
        disabled={editorLocked || conflictLocked || processingLocked}
      />
      <NativeKnowledgeConflictEditor
        model={conflict}
        controller={controllers.conflicts}
        disabled={editorLocked || syncLocked || processingLocked}
      />
      {!binding.processingClient &&
      ['configuration', 'text', 'semantic', 'entities', 'relationships'].some((operation) =>
        binding.authority.allowedActions.includes(operation),
      ) ? (
        <NativeKnowledgeRetrievalUnavailable />
      ) : (
        <>
          <NativeKnowledgeConfigurationPanel
            model={retrieval}
            controller={controllers.retrieval}
            disabled={editorLocked || syncLocked || conflictLocked || processingLocked}
          />
          <NativeKnowledgeRetrievalPanel
            model={retrieval}
            controller={controllers.retrieval}
            disabled={editorLocked || syncLocked || conflictLocked || processingLocked}
          />
        </>
      )}
      <NativeKnowledgeProcessingPanel
        model={processing}
        controller={controllers.processing}
        disabled={editorLocked || syncLocked || conflictLocked}
      />
    </>
  );
}
