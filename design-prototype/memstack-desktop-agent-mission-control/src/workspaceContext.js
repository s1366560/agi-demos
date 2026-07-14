export const tenantCatalog = [
  {
    id: 'northstar',
    name: 'Northstar Labs',
    shortName: 'Northstar',
    initials: 'NL',
    role: 'Workspace admin',
    plan: 'Enterprise',
    domain: 'northstar.ai',
    projects: [
      { id: 'product-strategy', name: 'Product Strategy', description: 'Research, planning, and leadership artifacts', icon: 'strategy', members: 12, activeTasks: 5 },
      { id: 'desktop-client', name: 'Desktop Client', description: 'Application UX, frontend, and Rust runtime', icon: 'code', members: 8, activeTasks: 3 },
      { id: 'customer-insights', name: 'Customer Insights', description: 'Interviews, feedback, and opportunity signals', icon: 'archive', members: 6, activeTasks: 2 },
    ],
  },
  {
    id: 'orbital',
    name: 'Orbital Research',
    shortName: 'Orbital',
    initials: 'OR',
    role: 'Member',
    plan: 'Team',
    domain: 'orbital-research.org',
    projects: [
      { id: 'agent-evals', name: 'Agent Evaluations', description: 'Benchmark suites and quality reviews', icon: 'strategy', members: 9, activeTasks: 4 },
      { id: 'open-models', name: 'Open Models', description: 'Model experiments and inference reports', icon: 'archive', members: 14, activeTasks: 7 },
    ],
  },
  {
    id: 'personal',
    name: "Alex's Sandbox",
    shortName: 'Sandbox',
    initials: 'AS',
    role: 'Workspace owner',
    plan: 'Personal',
    domain: 'Private workspace',
    projects: [
      { id: 'prototypes', name: 'Prototypes', description: 'Private experiments and scratch work', icon: 'code', members: 1, activeTasks: 1 },
    ],
  },
];

const workspaceCatalog = {
  'product-strategy': [
    {
      id: 'strategy-room',
      name: 'Strategy Room',
      description: 'Leadership research, planning, and evidence-backed decisions.',
      goal: 'Turn market and customer evidence into reviewable product decisions.',
      status: 'active',
      officeStatus: 'online',
      conversationMode: 'multi_agent_shared',
      members: 12,
      agents: 4,
      memories: 328,
      graphNodes: 2148,
      storage: '384 MB',
      updated: '4 min ago',
      sessions: [
        { id: 'strategy-brief', taskId: 'strategy-brief', mode: 'work', title: 'Q3 product strategy brief', status: 'input', meta: 'Needs your input' },
        { id: 'competitor-watch', taskId: 'competitor-watch', mode: 'work', title: 'Competitor launch watch', status: 'running', meta: 'Live · 5 sources' },
        { id: 'weekly-brief', taskId: 'weekly-brief', mode: 'work', title: 'Weekly leadership digest', status: 'ready', meta: 'Ready 12 min ago' },
      ],
      activity: [
        { type: 'artifact', title: 'Strategy brief draft updated', meta: 'Agent · 4 min ago' },
        { type: 'memory', title: '12 interview episodes indexed', meta: 'Memory service · 18 min ago' },
        { type: 'member', title: 'Maya joined as reviewer', meta: 'Alex Chen · Today' },
      ],
    },
    {
      id: 'customer-review',
      name: 'Customer Review',
      description: 'Escalations, service decisions, and customer evidence.',
      goal: 'Resolve customer-impacting decisions with complete evidence and audit trails.',
      status: 'attention',
      officeStatus: 'online',
      conversationMode: 'single_agent',
      members: 6,
      agents: 2,
      memories: 146,
      graphNodes: 829,
      storage: '172 MB',
      updated: '9 min ago',
      sessions: [
        { id: 'customer-risk', taskId: 'customer-risk', mode: 'work', title: 'Review customer escalation', status: 'ready', meta: 'Decision ready' },
      ],
      activity: [
        { type: 'task', title: 'Service-credit recommendation completed', meta: 'Support analyst · 9 min ago' },
        { type: 'artifact', title: 'Escalation evidence packet created', meta: 'Agent · 14 min ago' },
      ],
    },
  ],
  'desktop-client': [
    {
      id: 'desktop-client-main',
      name: 'Desktop Client',
      description: 'Application experience, frontend, and Rust runtime delivery.',
      goal: 'Ship a dependable desktop agent workspace across Work and Code.',
      status: 'active',
      officeStatus: 'online',
      conversationMode: 'multi_agent_shared',
      members: 8,
      agents: 4,
      memories: 248,
      graphNodes: 1842,
      storage: '612 MB',
      updated: '2 min ago',
      sessions: [
        { id: 'flaky-test', taskId: 'flaky-test', mode: 'code', title: 'Fix flaky data-pipeline test', status: 'running', meta: 'Worktree · 72%' },
        { id: 'auth-review', taskId: 'auth-review', mode: 'code', title: 'Review auth middleware refactor', status: 'input', meta: 'Approval required' },
        { id: 'desktop-search', taskId: 'desktop-search', mode: 'code', title: 'Add task search shortcuts', status: 'ready', meta: '7 files ready' },
      ],
      activity: [
        { type: 'verification', title: 'Targeted test suite passed', meta: 'Code agent · 2 min ago' },
        { type: 'artifact', title: 'Desktop navigation prototype updated', meta: 'Design agent · 11 min ago' },
        { type: 'memory', title: 'Rust runtime decision captured', meta: 'Memory service · 24 min ago' },
      ],
    },
    {
      id: 'release-reliability',
      name: 'Release Reliability',
      description: 'SDK upgrades, CI health, release plans, and verification evidence.',
      goal: 'Keep desktop releases recoverable, observable, and independently verifiable.',
      status: 'active',
      officeStatus: 'online',
      conversationMode: 'single_agent',
      members: 5,
      agents: 2,
      memories: 96,
      graphNodes: 506,
      storage: '208 MB',
      updated: '1 hr ago',
      sessions: [
        { id: 'sdk-upgrade', taskId: 'sdk-upgrade', mode: 'code', title: 'Plan agent SDK upgrade', status: 'ready', meta: 'Plan ready' },
      ],
      activity: [
        { type: 'artifact', title: 'SDK migration plan ready', meta: 'Code agent · 1 hr ago' },
        { type: 'task', title: 'Release checklist refreshed', meta: 'Alex Chen · Yesterday' },
      ],
    },
  ],
  'customer-insights': [
    {
      id: 'insight-lab',
      name: 'Insight Lab',
      description: 'Interviews, feedback synthesis, and opportunity signals.',
      goal: 'Keep customer evidence connected to product decisions and deliverables.',
      status: 'active',
      officeStatus: 'online',
      conversationMode: 'multi_agent_shared',
      members: 6,
      agents: 3,
      memories: 412,
      graphNodes: 2671,
      storage: '446 MB',
      updated: '18 min ago',
      sessions: [
        { id: 'customer-risk', taskId: 'customer-risk', mode: 'work', title: 'Review customer escalation', status: 'ready', meta: 'Decision ready' },
        { id: 'weekly-brief', taskId: 'weekly-brief', mode: 'work', title: 'Weekly insight digest', status: 'ready', meta: 'Artifact ready' },
      ],
      activity: [
        { type: 'memory', title: '28 feedback episodes indexed', meta: 'Memory service · 18 min ago' },
        { type: 'artifact', title: 'Opportunity map refreshed', meta: 'Research agent · 31 min ago' },
      ],
    },
  ],
};

export function getTenant(tenantId) {
  return tenantCatalog.find((tenant) => tenant.id === tenantId) ?? tenantCatalog[0];
}

export function getProject(tenantId, projectId) {
  const tenant = getTenant(tenantId);
  return tenant.projects.find((project) => project.id === projectId) ?? tenant.projects[0];
}

export function getProjectWorkspaces(tenantId, projectId) {
  const project = getProject(tenantId, projectId);
  return workspaceCatalog[project.id] ?? [
    {
      id: `${project.id}-workspace`,
      name: project.name,
      description: project.description,
      goal: 'Coordinate agent work, shared context, and reviewable outcomes.',
      status: 'active',
      officeStatus: 'online',
      conversationMode: 'single_agent',
      members: project.members,
      agents: 2,
      memories: 124,
      graphNodes: 718,
      storage: '196 MB',
      updated: 'Today',
      sessions: [
        { id: 'strategy-brief', taskId: 'strategy-brief', mode: 'work', title: 'Workspace research brief', status: 'input', meta: 'Needs your input' },
        { id: 'weekly-brief', taskId: 'weekly-brief', mode: 'work', title: 'Weekly workspace digest', status: 'ready', meta: 'Artifact ready' },
      ],
      activity: [
        { type: 'task', title: 'Workspace initialized', meta: 'Alex Chen · Today' },
        { type: 'memory', title: 'Project context connected', meta: 'Memory service · Today' },
      ],
    },
  ];
}

export function getWorkspace(tenantId, projectId, workspaceId) {
  const workspaces = getProjectWorkspaces(tenantId, projectId);
  return workspaces.find((workspace) => workspace.id === workspaceId) ?? workspaces[0];
}
