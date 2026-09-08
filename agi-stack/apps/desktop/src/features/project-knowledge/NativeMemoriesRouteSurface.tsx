import { createNativeMemoriesRouteControllers } from './nativeMemoriesRouteControllers';
import { NativeKnowledgeDiagnosticsPanel } from './NativeKnowledgeDiagnosticsPanel';
import { NativeKnowledgeCloudConnectionPanel } from './NativeKnowledgeCloudConnectionPanel';
import { useLayoutEffect, useMemo, useSyncExternalStore } from 'react';

import type { DesktopRouteSurfaceProps } from '../navigation/desktopRouteModule';
import { NativeMemoriesPage, NativeMemoriesUnavailable } from './NativeMemoriesPage';
import {
  useNativeMemoriesRouteBinding,
  type NativeMemoriesRouteBinding,
} from './NativeMemoriesRouteContext';
import { NativeKnowledgeSyncPanel } from './NativeKnowledgeSyncPanel';
import { NativeKnowledgeConflictEditor } from './NativeKnowledgeConflictEditor';
import { NativeKnowledgeConfigurationPanel } from './NativeKnowledgeConfigurationPanel';
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
  const controllers = useMemo(() => createNativeMemoriesRouteControllers(binding), [binding]);
  const diagnostics = useSyncExternalStore(
    controllers.diagnostics.subscribe,
    controllers.diagnostics.getSnapshot,
    controllers.diagnostics.getSnapshot,
  );
  const connection = useSyncExternalStore(
    controllers.connection.subscribe,
    controllers.connection.getSnapshot,
    controllers.connection.getSnapshot,
  );
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
    controllers.connection.activate();
    void controllers.connection.refresh();
    controllers.editor.activate();
    controllers.sync.activate();
    controllers.conflicts.activate();
    controllers.retrieval.activate();
    controllers.processing.activate();
    controllers.diagnostics.activate();
    void controllers.diagnostics.refresh();
    void controllers.retrieval.refreshConfiguration();
    void controllers.sync.refresh();
    if (controllers.editor.getSnapshot().allowedActions.includes('list'))
      void controllers.list.load(binding.authority.scope);
    return () => {
      controllers.connection.stop();
      controllers.editor.stop();
      controllers.list.stop();
      controllers.sync.stop();
      controllers.conflicts.stop();
      controllers.retrieval.stop();
      controllers.processing.stop();
      controllers.diagnostics.stop();
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
      {binding.connectionClient && binding.authority.allowedActions.includes('sync_status') ? (
        <NativeKnowledgeCloudConnectionPanel
          model={connection}
          controller={controllers.connection}
          disabled={editorLocked || conflictLocked || processingLocked || syncLocked}
        />
      ) : null}
      <NativeKnowledgeSyncPanel
        connectionReady={connection.bound}
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
            diagnosticsAvailable={diagnostics.phase !== 'unavailable'}
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
      <NativeKnowledgeDiagnosticsPanel
        model={diagnostics}
        controller={controllers.diagnostics}
        onSelectIndexFailure={controllers.processing.selectDiagnosticFailure}
        disabled={
          editorLocked ||
          syncLocked ||
          conflictLocked ||
          processingLocked ||
          processing.phase === 'loading'
        }
      />
      <NativeKnowledgeProcessingPanel
        model={processing}
        controller={controllers.processing}
        disabled={editorLocked || syncLocked || conflictLocked}
      />
    </>
  );
}
