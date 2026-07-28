import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';

import { useI18n } from '../../i18n';
import type {
  WorkspaceCollaborationClient,
  WorkspaceCollaborationSurface,
  WorkspaceSurfaceState,
} from './workspaceCollaborationClient';
import {
  WORKSPACE_COLLABORATION_TABS,
  beginWorkspaceSurfaceLoad,
  buildWorkspaceSurfaceMutation,
  createWorkspaceCollaborationCanvasState,
  failWorkspaceSurfaceLoad,
  invalidateWorkspaceSurfaceAuthority,
  resolveWorkspaceSurfaceLoad,
  selectWorkspaceCollaborationTab,
  type WorkspaceCollaborationCanvasState,
} from './workspaceCollaborationModel';
import {
  WorkspaceCollaborationCollection as Collection,
  WorkspaceCollaborationEmptyState as EmptyState,
  WorkspaceCollaborationInlineCreate as InlineCreate,
  WorkspaceCollaborationReadonlyCollectionSurface as ReadonlyCollectionSurface,
  WorkspaceCollaborationSettingsSurface as SettingsSurface,
  WorkspaceCollaborationSurfaceHeading as SurfaceHeading,
  WorkspaceCollaborationTopologySurface as TopologySurface,
  workspaceCollaborationBoolean as boolean,
  workspaceCollaborationItemId as itemId,
  workspaceCollaborationRows as rows,
  workspaceCollaborationText as text,
  type WorkspaceCollaborationMutationHandler as MutationHandler,
  type WorkspaceCollaborationReadonlySurfaceProps as ReadonlySurfaceProps,
  type WorkspaceCollaborationSurfaceProps as SurfaceProps,
  type WorkspaceCollaborationTranslate as Translate,
} from './WorkspaceCollaborationSurfacePrimitives';
import './WorkspaceCollaborationCanvas.css';

export type WorkspaceCollaborationCanvasProps = {
  workspaceId: string;
  client: WorkspaceCollaborationClient;
  initialSurface?: WorkspaceCollaborationSurface;
  createIdempotencyKey?: (
    surface: WorkspaceCollaborationSurface,
    action: string,
  ) => string;
};

const AUTHORITY_STATES = ['loading', 'empty', 'stale', 'error', 'unavailable'] as const;

export function WorkspaceCollaborationCanvas({
  workspaceId,
  client,
  initialSurface = 'goals',
  createIdempotencyKey,
}: WorkspaceCollaborationCanvasProps) {
  const { t } = useI18n();
  const [state, setState] = useState<WorkspaceCollaborationCanvasState>(() =>
    initialCanvasState(workspaceId, initialSurface),
  );
  const stateRef = useRef(state);
  const controllersRef = useRef<
    Partial<Record<WorkspaceCollaborationSurface, AbortController>>
  >({});
  const mutationCounterRef = useRef(0);
  const tabRefs = useRef<Partial<Record<WorkspaceCollaborationSurface, HTMLButtonElement>>>({});
  const [pendingMutation, setPendingMutation] = useState<string | null>(null);
  const [mutationFailed, setMutationFailed] = useState(false);

  const commit = useCallback(
    (
      update:
        | WorkspaceCollaborationCanvasState
        | ((current: WorkspaceCollaborationCanvasState) => WorkspaceCollaborationCanvasState),
    ) => {
      const next = typeof update === 'function' ? update(stateRef.current) : update;
      stateRef.current = next;
      setState(next);
      return next;
    },
    [],
  );

  const abortSurface = useCallback((surface: WorkspaceCollaborationSurface) => {
    controllersRef.current[surface]?.abort();
    delete controllersRef.current[surface];
  }, []);

  const abortAll = useCallback(() => {
    for (const controller of Object.values(controllersRef.current)) controller?.abort();
    controllersRef.current = {};
  }, []);

  const loadSurface = useCallback(
    (
      surface: WorkspaceCollaborationSurface,
      mode: 'initial' | 'canonical',
    ): AbortController => {
      abortSurface(surface);
      const controller = new AbortController();
      controllersRef.current[surface] = controller;
      const begun = commit((current) => beginWorkspaceSurfaceLoad(current, surface));
      const generation = begun.requestGenerations[surface] ?? 0;
      const request =
        mode === 'canonical'
          ? client.refetchAuthority(workspaceId, surface, controller.signal)
          : client.getSurface(workspaceId, surface, null, controller.signal);

      void request
        .then((snapshot) => {
          if (controller.signal.aborted || controllersRef.current[surface] !== controller) return;
          commit((current) =>
            resolveWorkspaceSurfaceLoad(current, surface, generation, snapshot),
          );
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted || isAbortError(error)) return;
          commit((current) =>
            failWorkspaceSurfaceLoad(
              current,
              surface,
              generation,
              'workspace_surface_load_failed',
            ),
          );
        })
        .finally(() => {
          if (controllersRef.current[surface] === controller) {
            delete controllersRef.current[surface];
          }
        });
      return controller;
    },
    [abortSurface, client, commit, workspaceId],
  );

  useEffect(() => {
    abortAll();
    const current =
      stateRef.current.workspaceId === workspaceId
        ? stateRef.current
        : initialCanvasState(workspaceId, initialSurface);
    if (current !== stateRef.current) commit(current);
    const controller = loadSurface(current.activeSurface, 'initial');
    return () => {
      controller.abort();
    };
  }, [abortAll, commit, initialSurface, loadSurface, workspaceId, state.activeSurface]);

  useEffect(() => abortAll, [abortAll]);

  const selectSurface = useCallback(
    (surface: WorkspaceCollaborationSurface) => {
      const current = stateRef.current;
      if (current.activeSurface === surface) return;
      abortSurface(current.activeSurface);
      commit(selectWorkspaceCollaborationTab(current, surface));
      setMutationFailed(false);
    },
    [abortSurface, commit],
  );

  const refresh = useCallback(() => {
    setMutationFailed(false);
    loadSurface(stateRef.current.activeSurface, 'canonical');
  }, [loadSurface]);

  const mutate: MutationHandler = useCallback(
    async (action, payload) => {
      const surface = stateRef.current.activeSurface;
      mutationCounterRef.current += 1;
      const idempotencyKey =
        createIdempotencyKey?.(surface, action) ??
        [
          workspaceId,
          surface,
          action,
          Date.now().toString(36),
          mutationCounterRef.current,
        ].join(':');
      const built = buildWorkspaceSurfaceMutation(
        stateRef.current,
        surface,
        action,
        idempotencyKey,
        payload,
      );
      if (!built.ok) {
        setMutationFailed(true);
        return;
      }

      abortSurface(surface);
      const controller = new AbortController();
      controllersRef.current[surface] = controller;
      setPendingMutation(action);
      setMutationFailed(false);
      try {
        await client.mutateSurface(
          workspaceId,
          surface,
          built.mutation,
          controller.signal,
        );
        if (controller.signal.aborted || controllersRef.current[surface] !== controller) return;
        commit((current) =>
          invalidateWorkspaceSurfaceAuthority(current, surface, 'mutation_ack'),
        );
        const begun = commit((current) => beginWorkspaceSurfaceLoad(current, surface));
        const generation = begun.requestGenerations[surface] ?? 0;
        const canonical = await client.refetchAuthority(
          workspaceId,
          surface,
          controller.signal,
        );
        if (controller.signal.aborted || controllersRef.current[surface] !== controller) return;
        commit((current) =>
          resolveWorkspaceSurfaceLoad(current, surface, generation, canonical),
        );
      } catch (error: unknown) {
        if (controller.signal.aborted || isAbortError(error)) return;
        const generation = stateRef.current.requestGenerations[surface] ?? 0;
        commit((current) =>
          failWorkspaceSurfaceLoad(
            current,
            surface,
            generation,
            'workspace_surface_mutation_refetch_failed',
          ),
        );
        setMutationFailed(true);
      } finally {
        if (controllersRef.current[surface] === controller) {
          delete controllersRef.current[surface];
        }
        setPendingMutation(null);
      }
    },
    [abortSurface, client, commit, createIdempotencyKey, workspaceId],
  );

  const activeSurface = state.activeSurface;
  const snapshot = state.surfaces[activeSurface];
  const status = snapshot?.status ?? 'loading';
  const hasData = snapshot?.data !== null && snapshot?.data !== undefined;
  const showStateOnly =
    !hasData ||
    status === 'loading' ||
    status === 'empty' ||
    status === 'unavailable';

  const onTabKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const currentIndex = WORKSPACE_COLLABORATION_TABS.findIndex(
      ({ id }) => id === activeSurface,
    );
    let nextIndex = currentIndex;
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % 10;
    else if (event.key === 'ArrowLeft') nextIndex = (currentIndex + 9) % 10;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = 9;
    else return;
    event.preventDefault();
    const next = WORKSPACE_COLLABORATION_TABS[nextIndex]?.id;
    if (!next) return;
    selectSurface(next);
    tabRefs.current[next]?.focus();
  };

  return (
    <section
      className="workspace-collaboration-canvas"
      aria-label={t('workspaceCollaboration.title')}
    >
      <header className="workspace-collaboration-header">
        <div>
          <span>{t('workspaceCollaboration.eyebrow')}</span>
          <h1>{t('workspaceCollaboration.title')}</h1>
          <p>{t('workspaceCollaboration.description', { workspaceId })}</p>
        </div>
        <button type="button" onClick={refresh} disabled={status === 'loading'}>
          {t('workspaceCollaboration.actions.refresh')}
        </button>
      </header>

      <div
        className="workspace-collaboration-tabs"
        role="tablist"
        aria-label={t('workspaceCollaboration.tabs.label')}
        onKeyDown={onTabKeyDown}
      >
        {WORKSPACE_COLLABORATION_TABS.map((tab) => (
          <button
            key={tab.id}
            ref={(node) => {
              if (node) tabRefs.current[tab.id] = node;
            }}
            id={`workspace-collaboration-tab-${tab.id}`}
            type="button"
            role="tab"
            aria-selected={activeSurface === tab.id}
            aria-controls={`workspace-collaboration-panel-${tab.id}`}
            tabIndex={activeSurface === tab.id ? 0 : -1}
            onClick={() => selectSurface(tab.id)}
          >
            {t(tab.labelKey)}
          </button>
        ))}
      </div>

      <div
        id={`workspace-collaboration-panel-${activeSurface}`}
        className="workspace-collaboration-panel"
        role="tabpanel"
        aria-labelledby={`workspace-collaboration-tab-${activeSurface}`}
        tabIndex={0}
      >
        {AUTHORITY_STATES.includes(status as (typeof AUTHORITY_STATES)[number]) &&
        (status === 'stale' || status === 'error') &&
        hasData ? (
          <AuthorityNotice status={status} snapshot={snapshot} t={t} compact />
        ) : null}
        {mutationFailed ? (
          <div className="workspace-collaboration-mutation-error" role="alert">
            {t('workspaceCollaboration.mutation.error')}
          </div>
        ) : null}
        {showStateOnly ? (
          <AuthorityNotice status={status} snapshot={snapshot} t={t} />
        ) : (
          <SurfaceContent
            surface={activeSurface}
            data={snapshot?.data}
            busy={pendingMutation !== null}
            onMutate={mutate}
            t={t}
          />
        )}
      </div>
    </section>
  );
}

function AuthorityNotice({
  status,
  snapshot,
  t,
  compact = false,
}: {
  status: WorkspaceSurfaceState['status'];
  snapshot: WorkspaceSurfaceState | undefined;
  t: Translate;
  compact?: boolean;
}) {
  return (
    <div
      className={`workspace-collaboration-state is-${status}${compact ? ' is-compact' : ''}`}
      role={status === 'error' ? 'alert' : 'status'}
      data-reason-code={snapshot?.reason_code ?? undefined}
    >
      <strong>{t(`workspaceCollaboration.state.${status}.title`)}</strong>
      <p>{t(`workspaceCollaboration.state.${status}.description`)}</p>
    </div>
  );
}

function SurfaceContent({
  surface,
  data,
  busy,
  onMutate,
  t,
}: {
  surface: WorkspaceCollaborationSurface;
  data: unknown;
  busy: boolean;
  onMutate: MutationHandler;
  t: Translate;
}) {
  switch (surface) {
    case 'goals':
      return <GoalsSurface data={data} busy={busy} onMutate={onMutate} t={t} />;
    case 'discussion':
      return <DiscussionSurface data={data} busy={busy} onMutate={onMutate} t={t} />;
    case 'status':
      return <StatusSurface data={data} t={t} />;
    case 'collaboration':
      return <CollaborationSurface data={data} t={t} />;
    case 'members':
      return <MembersSurface data={data} busy={busy} onMutate={onMutate} t={t} />;
    case 'genes':
      return <GenesSurface data={data} busy={busy} onMutate={onMutate} t={t} />;
    case 'files':
      return <FilesSurface data={data} t={t} />;
    case 'notes':
      return <NotesSurface data={data} t={t} />;
    case 'topology':
      return <TopologySurface data={data} busy={busy} onMutate={onMutate} t={t} />;
    case 'settings':
      return <SettingsSurface data={data} busy={busy} onMutate={onMutate} t={t} />;
  }
}

function GoalsSurface(props: SurfaceProps) {
  const { data, busy, onMutate, t } = props;
  const [layout, setLayout] = useState<'flat' | 'lanes'>('flat');
  const [objective, setObjective] = useState('');
  const [task, setTask] = useState('');
  const objectives = rows(data, 'objectives', 'goals');
  const tasks = rows(data, 'tasks');
  const lanes = ['pending', 'in_progress', 'review', 'blocked', 'completed'];
  return (
    <div className="workspace-collaboration-surface">
      <SurfaceHeading title={t('workspaceCollaboration.goals.title')}>
        <div className="workspace-collaboration-layout-toggle" role="group">
          {(['flat', 'lanes'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              aria-pressed={layout === mode}
              onClick={() => setLayout(mode)}
            >
              {t(`workspaceCollaboration.goals.layout.${mode}`)}
            </button>
          ))}
        </div>
      </SurfaceHeading>
      <div className="workspace-collaboration-split">
        <Collection title={t('workspaceCollaboration.goals.objectives')} items={objectives} t={t} />
        {layout === 'flat' ? (
          <Collection title={t('workspaceCollaboration.goals.tasks')} items={tasks} t={t} />
        ) : (
          <div className="workspace-collaboration-lanes">
            {lanes.map((lane) => (
              <section key={lane}>
                <h3>{t(`workspaceCollaboration.goals.lanes.${lane}`)}</h3>
                <Collection
                  items={tasks.filter((item) => text(item, 'status') === lane)}
                  t={t}
                  compact
                />
              </section>
            ))}
          </div>
        )}
      </div>
      <div className="workspace-collaboration-action-grid">
        <InlineCreate
          value={objective}
          setValue={setObjective}
          label={t('workspaceCollaboration.goals.newObjective')}
          actionLabel={t('workspaceCollaboration.goals.createObjective')}
          busy={busy}
          onSubmit={async () => {
            await onMutate('create_objective', { title: objective.trim() });
            setObjective('');
          }}
        />
        <InlineCreate
          value={task}
          setValue={setTask}
          label={t('workspaceCollaboration.goals.newTask')}
          actionLabel={t('workspaceCollaboration.goals.createTask')}
          busy={busy}
          onSubmit={async () => {
            await onMutate('create_task', { title: task.trim() });
            setTask('');
          }}
        />
      </div>
    </div>
  );
}

function DiscussionSurface({ data, busy, onMutate, t }: SurfaceProps) {
  const posts = rows(data, 'posts');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [replyTo, setReplyTo] = useState<string | null>(null);
  const [reply, setReply] = useState('');
  return (
    <div className="workspace-collaboration-surface">
      <SurfaceHeading title={t('workspaceCollaboration.discussion.title')} />
      <form
        className="workspace-collaboration-composer"
        onSubmit={(event) => {
          event.preventDefault();
          if (!body.trim()) return;
          void onMutate('create_post', { title: title.trim(), content: body.trim() }).then(() => {
            setTitle('');
            setBody('');
          });
        }}
      >
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder={t('workspaceCollaboration.discussion.postTitle')}
        />
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          placeholder={t('workspaceCollaboration.discussion.postBody')}
          required
        />
        <button type="submit" disabled={busy || !body.trim()}>
          {t('workspaceCollaboration.discussion.publish')}
        </button>
      </form>
      <div className="workspace-collaboration-feed">
        {posts.map((post, index) => {
          const id = itemId(post, index, 'post');
          const pinned = boolean(post, 'is_pinned', 'pinned');
          return (
            <article key={id}>
              <header>
                <div>
                  <strong>
                    {text(post, 'title') ??
                      t('workspaceCollaboration.discussion.untitled')}
                  </strong>
                  <small>
                    {text(post, 'author_name', 'author') ??
                      t('workspaceCollaboration.unknown')}
                  </small>
                </div>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void onMutate(pinned ? 'unpin_post' : 'pin_post', { post_id: id })
                  }
                >
                  {t(
                    pinned
                      ? 'workspaceCollaboration.discussion.unpin'
                      : 'workspaceCollaboration.discussion.pin',
                  )}
                </button>
              </header>
              <p>{text(post, 'content', 'body', 'summary') ?? t('workspaceCollaboration.empty')}</p>
              <Collection items={rows(post, 'replies')} t={t} compact />
              {replyTo === id ? (
                <form
                  className="workspace-collaboration-reply"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (!reply.trim()) return;
                    void onMutate('create_reply', { post_id: id, content: reply.trim() }).then(
                      () => {
                        setReply('');
                        setReplyTo(null);
                      },
                    );
                  }}
                >
                  <textarea
                    value={reply}
                    onChange={(event) => setReply(event.target.value)}
                    placeholder={t('workspaceCollaboration.discussion.replyBody')}
                    required
                  />
                  <button type="submit" disabled={busy || !reply.trim()}>
                    {t('workspaceCollaboration.discussion.reply')}
                  </button>
                </form>
              ) : (
                <button type="button" onClick={() => setReplyTo(id)}>
                  {t('workspaceCollaboration.discussion.reply')}
                </button>
              )}
            </article>
          );
        })}
        {posts.length === 0 ? <EmptyState t={t} /> : null}
      </div>
    </div>
  );
}

function StatusSurface({ data, t }: ReadonlySurfaceProps) {
  const diagnostics = recordAt(data, 'diagnostics');
  const items = [
    ...(diagnostics ? [diagnostics] : []),
    ...rows(data, 'metrics', 'status_items'),
    ...rows(data, 'tasks'),
  ];
  return (
    <ReadonlyCollectionSurface
      title={t('workspaceCollaboration.status.title')}
      items={items}
      t={t}
    />
  );
}

function CollaborationSurface({ data, t }: ReadonlySurfaceProps) {
  const items = [
    ...rows(data, 'agents'),
    ...rows(data, 'members'),
    ...rows(data, 'tasks'),
    ...rows(data, 'sessions'),
    ...rows(data, 'activity'),
  ];
  return (
    <ReadonlyCollectionSurface
      title={t('workspaceCollaboration.collaboration.title')}
      items={items}
      t={t}
    />
  );
}

function MembersSurface({ data, busy, onMutate, t }: SurfaceProps) {
  const members = rows(data, 'members');
  const [userId, setUserId] = useState('');
  const [role, setRole] = useState('member');
  return (
    <div className="workspace-collaboration-surface">
      <SurfaceHeading title={t('workspaceCollaboration.members.title')} />
      <Collection
        items={members}
        t={t}
        actions={(member, index) => {
          const id = text(member, 'user_id', 'id') ?? itemId(member, index, 'member');
          return (
            <button
              type="button"
              disabled={busy}
              onClick={() => void onMutate('remove_member', { user_id: id })}
            >
              {t('workspaceCollaboration.members.remove')}
            </button>
          );
        }}
      />
      <form
        className="workspace-collaboration-inline-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!userId.trim()) return;
          void onMutate('add_member', { user_id: userId.trim(), role }).then(() =>
            setUserId(''),
          );
        }}
      >
        <input
          value={userId}
          onChange={(event) => setUserId(event.target.value)}
          placeholder={t('workspaceCollaboration.members.userId')}
          required
        />
        <select value={role} onChange={(event) => setRole(event.target.value)}>
          {['owner', 'admin', 'member', 'viewer'].map((value) => (
            <option key={value} value={value}>
              {t(`workspaceCollaboration.members.roles.${value}`)}
            </option>
          ))}
        </select>
        <button type="submit" disabled={busy || !userId.trim()}>
          {t('workspaceCollaboration.members.add')}
        </button>
      </form>
    </div>
  );
}

function GenesSurface({ data, busy, onMutate, t }: SurfaceProps) {
  const genes = rows(data, 'genes');
  return (
    <div className="workspace-collaboration-surface">
      <SurfaceHeading title={t('workspaceCollaboration.genes.title')} />
      <Collection
        items={genes}
        t={t}
        actions={(gene, index) => {
          const id = itemId(gene, index, 'gene');
          const active = boolean(gene, 'is_active', 'enabled');
          return (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void onMutate('toggle_gene', { gene_id: id, is_active: !active })
              }
            >
              {t(
                active
                  ? 'workspaceCollaboration.genes.disable'
                  : 'workspaceCollaboration.genes.enable',
              )}
            </button>
          );
        }}
      />
    </div>
  );
}

function FilesSurface({ data, t }: ReadonlySurfaceProps) {
  return (
    <ReadonlyCollectionSurface
      title={t('workspaceCollaboration.files.title')}
      items={rows(data, 'files')}
      t={t}
    />
  );
}

function NotesSurface({ data, t }: ReadonlySurfaceProps) {
  const workspace = recordAt(data, 'workspace');
  const workspaceDescription = workspace
    ? text(workspace, 'description')
    : null;
  const workspaceName = workspace ? text(workspace, 'name') : null;
  const derived = [
    ...(workspaceDescription
      ? [
          {
            id: 'workspace-description',
            title: workspaceName,
            content: workspaceDescription,
          },
        ]
      : []),
    ...rows(data, 'objectives'),
    ...rows(data, 'pinned_posts'),
  ];
  return (
    <div className="workspace-collaboration-surface" aria-readonly="true">
      <SurfaceHeading title={t('workspaceCollaboration.notes.title')}>
        <span className="workspace-collaboration-derived">
          {t('workspaceCollaboration.notes.derived')}
        </span>
      </SurfaceHeading>
      <Collection items={derived} t={t} />
    </div>
  );
}

function recordAt(data: unknown, key: string): Record<string, unknown> | null {
  if (data === null || typeof data !== 'object' || Array.isArray(data)) return null;
  const value = (data as Record<string, unknown>)[key];
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function initialCanvasState(
  workspaceId: string,
  surface: WorkspaceCollaborationSurface,
): WorkspaceCollaborationCanvasState {
  return selectWorkspaceCollaborationTab(
    createWorkspaceCollaborationCanvasState(workspaceId),
    surface,
  );
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError';
}
