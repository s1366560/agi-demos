import { useWorkspaceAgents, useWorkspaceMembers } from '@/stores/workspace';

export function MemberPanel() {
  const members = useWorkspaceMembers();
  const agents = useWorkspaceAgents();

  return (
    <section className="rounded-lg border border-slate-200 p-4 bg-white">
      <h3 className="font-semibold text-slate-900 mb-3">Members & Agents</h3>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <h4 className="text-sm font-medium mb-2">Members ({members.length})</h4>
          <ul className="space-y-1">
            {members.map((member) => (
              <li key={member.id} className="text-sm border rounded px-2 py-1">
                {member.user_id} · {member.role}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-sm font-medium mb-2">Agents ({agents.length})</h4>
          <ul className="space-y-1">
            {agents.map((agent) => (
              <li key={agent.id} className="text-sm border rounded px-2 py-1">
                {agent.display_name || agent.agent_id}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
