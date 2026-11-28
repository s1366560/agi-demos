/** Signed command and page scopes taken from the six business contributions. */
export type SignedCommandScope = 'project' | 'tenant' | 'shared';
export type SignedPageScope = 'project' | 'tenant';

export type SignedPluginSurface = Readonly<{
  commands: Readonly<Record<string, SignedCommandScope>>;
  pages: Readonly<Record<string, SignedPageScope>>;
}>;

const SCOPES = new Set<SignedCommandScope>(['project', 'tenant', 'shared']);
const PAGE_SCOPES = new Set<SignedPageScope>(['project', 'tenant']);

function freezeSurface(value: unknown): Readonly<Record<string, SignedPluginSurface>> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('signed contribution surface is invalid');
  }
  const plugins: Record<string, SignedPluginSurface> = {};
  for (const [pluginId, plugin] of Object.entries(value)) {
    if (!plugin || typeof plugin !== 'object' || Array.isArray(plugin)) {
      throw new Error('signed contribution surface is invalid');
    }
    const record = plugin as { commands?: unknown; pages?: unknown };
    const commands: Record<string, SignedCommandScope> = {};
    const pages: Record<string, SignedPageScope> = {};
    if (!record.commands || typeof record.commands !== 'object' || Array.isArray(record.commands)) {
      throw new Error('signed contribution surface is invalid');
    }
    for (const [commandId, scope] of Object.entries(record.commands)) {
      if (!SCOPES.has(scope as SignedCommandScope)) throw new Error('signed contribution surface is invalid');
      commands[commandId] = scope as SignedCommandScope;
    }
    if (!record.pages || typeof record.pages !== 'object' || Array.isArray(record.pages)) {
      throw new Error('signed contribution surface is invalid');
    }
    for (const [pageId, scope] of Object.entries(record.pages)) {
      if (!PAGE_SCOPES.has(scope as SignedPageScope)) throw new Error('signed contribution surface is invalid');
      pages[pageId] = scope as SignedPageScope;
    }
    plugins[pluginId] = Object.freeze({
      commands: Object.freeze(commands),
      pages: Object.freeze(pages),
    });
  }
  return Object.freeze(plugins);
}

export const signedContributionSurface = freezeSurface({"memstack-agent":{"commands":{"validate-skill":"shared","chat-list":"shared","chat-create":"shared","chat-history":"shared","chat-turn":"shared","chat-cancel":"shared","chat-rename":"shared","chat-interactions":"shared","chat-respond":"shared","chat-upload":"shared","chat-attached-turn":"shared","activity-list":"shared","activity-mark":"shared","review-latest":"shared","review-details":"shared","dashboard-read":"tenant","dashboard-trace":"tenant","dashboard-configure":"tenant","chat-composer-read":"project","chat-composer-save":"project","chat-models":"project","chat-project-context":"project","chat-welcome":"project","chat-lifecycle-control":"project","chat-voice-authorize":"project","tenant-session-list":"tenant","tenant-session-create":"tenant","tenant-session-open":"tenant"},"pages":{"skill":"project","chat":"project","tenant-chat":"tenant","dashboard":"tenant"}},"memstack-workspace":{"commands":{"export-csv":"shared","list-directory":"shared","read-workspace":"shared","create-workspace":"shared","update-workspace":"shared","list-members":"shared","change-members":"shared","list-posts":"shared","change-posts":"shared","list-tasks":"shared","change-tasks":"shared","blackboard-read":"shared","blackboard-change":"shared","read-project-overview":"shared","read-group-chat":"shared","send-group-message":"shared"},"pages":{"directory":"project","tenant-directory":"tenant","directory-export":"project","overview":"project","create":"project","tenant-create":"tenant","settings":"project","workspace-members":"project","workspace-posts":"project","workspace-tasks":"project","workspace-task-detail":"project","detail":"project","agent-collab":"project"}},"memstack-knowledge":{"commands":{"project-graph":"shared","list-memories":"shared","read-memory":"shared","save-memory":"shared","list-entities":"shared","entity-types":"shared","entity-relationships":"shared","delete-memory":"shared","reindex-memory":"shared","index-status":"shared","optimize-content":"shared","read-graph":"shared","read-subgraph":"shared","search-project":"shared"},"pages":{"knowledge":"project","graph":"project","memories":"project","desktop-memory-editor":"project","memory-detail":"project","recent-memories":"project","entities":"project","memory-editor":"project","project-search":"project"}},"memstack-automation":{"commands":{"next-scheduled-run":"shared","run-workflow":"shared","list-playbooks":"shared","list-schedules":"shared","save-schedule":"shared","run-schedule":"shared","save-workflow":"shared","list-workflows":"shared","execute-workflow":"shared","delete-schedule":"shared","list-patterns":"shared","delete-pattern":"shared","list-verdicts":"shared","read-events":"shared","event-types":"shared","list-webhooks":"shared","create-webhook":"shared","update-webhook":"shared","delete-webhook":"shared","schedule-conversations":"shared"},"pages":{"workflow":"project","playbooks":"project","schedules":"project","workflow-patterns":"tenant","events":"tenant","webhooks":"tenant"}},"memstack-environments":{"commands":{"cluster-health":"shared","patch-text":"shared","sandbox-status":"shared","prepare-sandbox":"shared","authorize-run-terminal":"shared","environment-inventory":"shared","write-cluster":"shared","delete-cluster":"shared","restart-sandbox":"shared","terminate-sandbox":"shared","project-terminal":"shared","project-desktop":"shared","list-runner-pools":"shared","create-runner-pool":"shared","register-runner":"shared","read-deploys":"shared","change-deploy":"shared","read-instance-templates":"shared","change-instance-template":"shared","create-runtime-instance":"shared","read-runtime-pool":"shared","control-runtime-pool":"shared","set-runtime-pool-tier":"shared"},"pages":{"sandbox":"project","patch":"project","tenant-instances":"tenant","tenant-clusters":"tenant","org-clusters":"tenant","cluster-details":"tenant","sandbox-runtime":"project","sandbox-interaction":"project","deployments":"tenant","instance-templates":"tenant","create-instance":"tenant","runtime-pool":"tenant","agent-code":"project"}},"memstack-billing":{"commands":{"quote-free":"shared","quote-pro":"shared","quote-enterprise":"shared","tenant-account":"shared","change-plan":"shared","billing-details":"shared"},"pages":{"account":"project","tenant-account":"tenant"}}});

export function signedCommandScope(
  pluginId: string,
  commandId: string,
): SignedCommandScope | null {
  return signedContributionSurface[pluginId]?.commands[commandId] ?? null;
}

export function signedPageScope(pluginId: string, pageId: string): SignedPageScope | null {
  return signedContributionSurface[pluginId]?.pages[pageId] ?? null;
}

export function signedPluginHasPage(pluginId: string, scope: SignedPageScope): boolean {
  const pages = signedContributionSurface[pluginId]?.pages;
  return Boolean(pages && Object.values(pages).includes(scope));
}

/** A declared command may run only on the installation scope its contribution names. */
export function signedCommandAdmits(
  pluginId: string,
  commandId: unknown,
  tenantPath: boolean,
): boolean {
  if (typeof commandId !== 'string') return false;
  const scope = signedCommandScope(pluginId, commandId);
  if (scope === null) return false;
  return tenantPath ? scope !== 'project' : scope !== 'tenant';
}

/** Rich-page bytes follow the same declared page scope as the signed package. */
export function signedPageAdmits(
  pluginId: string,
  pageId: unknown,
  tenantPath: boolean,
): boolean {
  const wanted: SignedPageScope = tenantPath ? 'tenant' : 'project';
  if (pageId === undefined) return signedPluginHasPage(pluginId, wanted);
  return typeof pageId === 'string' && signedPageScope(pluginId, pageId) === wanted;
}
