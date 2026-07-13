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

export function getTenant(tenantId) {
  return tenantCatalog.find((tenant) => tenant.id === tenantId) ?? tenantCatalog[0];
}

export function getProject(tenantId, projectId) {
  const tenant = getTenant(tenantId);
  return tenant.projects.find((project) => project.id === projectId) ?? tenant.projects[0];
}
