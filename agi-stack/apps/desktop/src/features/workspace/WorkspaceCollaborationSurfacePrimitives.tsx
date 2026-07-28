import {
  type FormEvent,
  type ReactNode,
  useEffect,
  useState,
} from 'react';

export type WorkspaceCollaborationTranslate = (
  key: string,
  values?: Record<string, string | number>,
) => string;
export type WorkspaceCollaborationDataRecord = Record<string, unknown>;
export type WorkspaceCollaborationMutationHandler = (
  action: string,
  payload: WorkspaceCollaborationDataRecord,
) => Promise<boolean>;

export type WorkspaceCollaborationSurfaceProps = {
  data: unknown;
  busy: boolean;
  onMutate: WorkspaceCollaborationMutationHandler;
  t: WorkspaceCollaborationTranslate;
};

export type WorkspaceCollaborationReadonlySurfaceProps = Pick<
  WorkspaceCollaborationSurfaceProps,
  'data' | 't'
>;

export function WorkspaceCollaborationTopologySurface({
  data,
  busy,
  onMutate,
  t,
}: WorkspaceCollaborationSurfaceProps) {
  const nodes = workspaceCollaborationRows(data, 'nodes');
  const edges = workspaceCollaborationRows(data, 'edges');
  const [nodeLabel, setNodeLabel] = useState('');
  const [sourceId, setSourceId] = useState('');
  const [targetId, setTargetId] = useState('');

  return (
    <div className="workspace-collaboration-surface">
      <WorkspaceCollaborationSurfaceHeading
        title={t('workspaceCollaboration.topology.title')}
      />
      <div className="workspace-collaboration-split">
        <WorkspaceCollaborationCollection
          title={t('workspaceCollaboration.topology.nodes')}
          items={nodes}
          t={t}
          actions={(node, index) => (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void onMutate('delete_node', {
                  node_id: workspaceCollaborationItemId(node, index, 'node'),
                })
              }
            >
              {t('workspaceCollaboration.topology.deleteNode')}
            </button>
          )}
        />
        <WorkspaceCollaborationCollection
          title={t('workspaceCollaboration.topology.edges')}
          items={edges}
          t={t}
          actions={(edge, index) => (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void onMutate('delete_edge', {
                  edge_id: workspaceCollaborationItemId(edge, index, 'edge'),
                })
              }
            >
              {t('workspaceCollaboration.topology.deleteEdge')}
            </button>
          )}
        />
      </div>
      <div className="workspace-collaboration-action-grid">
        <WorkspaceCollaborationInlineCreate
          value={nodeLabel}
          setValue={setNodeLabel}
          label={t('workspaceCollaboration.topology.nodeLabel')}
          actionLabel={t('workspaceCollaboration.topology.createNode')}
          busy={busy}
          onSubmit={async () => {
            const succeeded = await onMutate('create_node', {
              title: nodeLabel.trim(),
              node_type: 'workspace',
            });
            if (!succeeded) return;
            setNodeLabel('');
          }}
        />
        <form
          className="workspace-collaboration-inline-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (!sourceId.trim() || !targetId.trim()) return;
            void onMutate('create_edge', {
              source_node_id: sourceId.trim(),
              target_node_id: targetId.trim(),
            }).then((succeeded) => {
              if (!succeeded) return;
              setSourceId('');
              setTargetId('');
            });
          }}
        >
          <input
            value={sourceId}
            onChange={(event) => setSourceId(event.target.value)}
            placeholder={t('workspaceCollaboration.topology.sourceNode')}
            required
          />
          <input
            value={targetId}
            onChange={(event) => setTargetId(event.target.value)}
            placeholder={t('workspaceCollaboration.topology.targetNode')}
            required
          />
          <button
            type="submit"
            disabled={busy || !sourceId.trim() || !targetId.trim()}
          >
            {t('workspaceCollaboration.topology.createEdge')}
          </button>
        </form>
      </div>
    </div>
  );
}

export function WorkspaceCollaborationSettingsSurface({
  data,
  busy,
  onMutate,
  t,
}: WorkspaceCollaborationSurfaceProps) {
  const root = workspaceCollaborationRecord(data) ?? {};
  const settings = workspaceCollaborationRecord(root.workspace) ?? root;
  const [name, setName] = useState(workspaceCollaborationText(settings, 'name') ?? '');
  const [description, setDescription] = useState(
    workspaceCollaborationText(settings, 'description') ?? '',
  );

  useEffect(() => {
    setName(workspaceCollaborationText(settings, 'name') ?? '');
    setDescription(workspaceCollaborationText(settings, 'description') ?? '');
  }, [data]);

  return (
    <div className="workspace-collaboration-surface">
      <WorkspaceCollaborationSurfaceHeading
        title={t('workspaceCollaboration.settings.title')}
      />
      <form
        className="workspace-collaboration-settings"
        onSubmit={(event) => {
          event.preventDefault();
          void onMutate('update_workspace', {
            name: name.trim(),
            description: description.trim(),
          });
        }}
      >
        <label>
          <span>{t('workspaceCollaboration.settings.name')}</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
        </label>
        <label>
          <span>{t('workspaceCollaboration.settings.description')}</span>
          <textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <button type="submit" disabled={busy || !name.trim()}>
          {t('workspaceCollaboration.settings.save')}
        </button>
      </form>
    </div>
  );
}

export function WorkspaceCollaborationReadonlyCollectionSurface({
  title,
  items,
  t,
}: {
  title: string;
  items: WorkspaceCollaborationDataRecord[];
  t: WorkspaceCollaborationTranslate;
}) {
  return (
    <div className="workspace-collaboration-surface">
      <WorkspaceCollaborationSurfaceHeading title={title} />
      <WorkspaceCollaborationCollection items={items} t={t} />
    </div>
  );
}

export function WorkspaceCollaborationSurfaceHeading({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <header className="workspace-collaboration-surface-heading">
      <h2>{title}</h2>
      {children}
    </header>
  );
}

export function WorkspaceCollaborationCollection({
  title,
  items,
  t,
  compact = false,
  actions,
}: {
  title?: string;
  items: WorkspaceCollaborationDataRecord[];
  t: WorkspaceCollaborationTranslate;
  compact?: boolean;
  actions?: (item: WorkspaceCollaborationDataRecord, index: number) => ReactNode;
}) {
  return (
    <section
      className={`workspace-collaboration-collection${compact ? ' is-compact' : ''}`}
    >
      {title ? <h3>{title}</h3> : null}
      <div>
        {items.map((item, index) => (
          <article key={workspaceCollaborationItemId(item, index, 'item')}>
            <div>
              <strong>
                {workspaceCollaborationItemTitle(item) ??
                  t('workspaceCollaboration.unknown')}
              </strong>
              <p>
                {workspaceCollaborationItemDetail(item) ??
                  t('workspaceCollaboration.empty')}
              </p>
            </div>
            {actions ? <aside>{actions(item, index)}</aside> : null}
          </article>
        ))}
        {items.length === 0 ? <WorkspaceCollaborationEmptyState t={t} /> : null}
      </div>
    </section>
  );
}

export function WorkspaceCollaborationInlineCreate({
  value,
  setValue,
  label,
  actionLabel,
  busy,
  onSubmit,
}: {
  value: string;
  setValue: (value: string) => void;
  label: string;
  actionLabel: string;
  busy: boolean;
  onSubmit: () => Promise<boolean>;
}) {
  return (
    <form
      className="workspace-collaboration-inline-form"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        if (!value.trim()) return;
        void onSubmit();
      }}
    >
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={label}
        aria-label={label}
        required
      />
      <button type="submit" disabled={busy || !value.trim()}>
        {actionLabel}
      </button>
    </form>
  );
}

export function WorkspaceCollaborationEmptyState({
  t,
}: {
  t: WorkspaceCollaborationTranslate;
}) {
  return (
    <div className="workspace-collaboration-empty">
      {t('workspaceCollaboration.empty')}
    </div>
  );
}

export function workspaceCollaborationRows(
  data: unknown,
  ...keys: string[]
): WorkspaceCollaborationDataRecord[] {
  const root = workspaceCollaborationRecord(data);
  for (const key of keys) {
    const value = root?.[key];
    if (Array.isArray(value)) return recordsFromArray(value);
  }
  return Array.isArray(data) ? recordsFromArray(data) : [];
}

export function workspaceCollaborationRecord(
  value: unknown,
): WorkspaceCollaborationDataRecord | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as WorkspaceCollaborationDataRecord)
    : null;
}

export function workspaceCollaborationText(
  value: WorkspaceCollaborationDataRecord,
  ...keys: string[]
): string | null {
  for (const key of keys) {
    const candidate = value[key];
    if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
  }
  return null;
}

export function workspaceCollaborationBoolean(
  value: WorkspaceCollaborationDataRecord,
  ...keys: string[]
): boolean {
  for (const key of keys) {
    if (typeof value[key] === 'boolean') return value[key] as boolean;
  }
  return false;
}

export function workspaceCollaborationItemId(
  value: WorkspaceCollaborationDataRecord,
  index: number,
  prefix: string,
): string {
  return (
    workspaceCollaborationText(
      value,
      'id',
      'task_id',
      'objective_id',
      'node_id',
      'edge_id',
    ) ?? `${prefix}-${index}`
  );
}

function recordsFromArray(values: unknown[]): WorkspaceCollaborationDataRecord[] {
  const records: WorkspaceCollaborationDataRecord[] = [];
  for (const value of values) {
    const candidate = workspaceCollaborationRecord(value);
    if (candidate) records.push(candidate);
  }
  return records;
}

function workspaceCollaborationItemTitle(
  value: WorkspaceCollaborationDataRecord,
): string | null {
  return workspaceCollaborationText(
    value,
    'title',
    'name',
    'label',
    'filename',
    'display_name',
    'value',
  );
}

function workspaceCollaborationItemDetail(
  value: WorkspaceCollaborationDataRecord,
): string | null {
  return workspaceCollaborationText(
    value,
    'description',
    'summary',
    'content',
    'body',
    'status',
    'role',
    'path',
    'detail',
  );
}
