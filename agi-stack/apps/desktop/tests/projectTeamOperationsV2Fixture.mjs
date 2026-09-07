export function projectTeamOperationsV2Fixture(overrides = {}) {
  return Object.freeze({
    async loadProjectTeam({ scope, signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        scopeRevision: 61,
        authority: 'cloud',
        availability: 'degraded',
        reasonCode: 'desktop_project_team_actions_partial',
        allowedActions: Object.freeze(['view', 'list-members', 'list-agent-teammates']),
        members: Object.freeze([]),
        agents: Object.freeze([]),
        currentUserRole: 'member',
        ...overrides,
      });
    },
  });
}
