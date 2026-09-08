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
    return { list, editor, sync, conflicts };
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
  useLayoutEffect(() => {
    controllers.editor.activate();
    controllers.sync.activate();
    controllers.conflicts.activate();
    void controllers.sync.refresh();
    if (controllers.editor.getSnapshot().allowedActions.includes('list'))
      void controllers.list.load(binding.authority.scope);
    return () => {
      controllers.editor.stop();
      controllers.list.stop();
      controllers.sync.stop();
      controllers.conflicts.stop();
    };
  }, [binding, controllers]);
  const editorLocked = editor.phase === 'saving' || editor.phase === 'uncertain';
  const syncLocked = sync.phase === 'syncing' || sync.recoveryRequired;
  const conflictLocked = ['checking', 'saving', 'uncertain'].includes(conflict.phase);
  return (
    <>
      <fieldset className="native-knowledge-route-boundary" disabled={syncLocked || conflictLocked}>
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
        disabled={editorLocked || conflictLocked}
      />
      <NativeKnowledgeConflictEditor
        model={conflict}
        controller={controllers.conflicts}
        disabled={editorLocked || syncLocked}
      />
    </>
  );
}
