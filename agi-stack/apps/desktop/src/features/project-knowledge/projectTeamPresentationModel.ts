import type { ProjectKnowledgePresentationInput } from './projectKnowledgePresentationModel';
import { buildProjectKnowledgePresentation } from './projectKnowledgePresentationModel';
import { PROJECT_TEAM_ROUTE_ID, type ProjectTeamSnapshot } from './projectTeamClient';

export function buildProjectTeamPresentation(
  input: ProjectKnowledgePresentationInput<ProjectTeamSnapshot>,
) {
  return buildProjectKnowledgePresentation(PROJECT_TEAM_ROUTE_ID, input, (snapshot) => {
    const members = snapshot.members.map((member) =>
      Object.freeze({
        id: member.userId,
        title: member.name ?? member.email,
        detail: member.email,
        kind: member.role,
      }),
    );
    const agents = snapshot.agents.map((agent) =>
      Object.freeze({
        id: agent.id,
        title: agent.name,
        detail: agent.model,
        kind: agent.enabled ? 'agent-enabled' : 'agent-disabled',
      }),
    );
    return Object.freeze({
      items: Object.freeze([...members, ...agents]),
      total: members.length + agents.length,
    });
  });
}
