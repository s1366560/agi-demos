import { useWorkspaceTopology } from '@/stores/workspace';

interface TopologyBoardProps {
  workspaceId: string;
}

export function TopologyBoard({ workspaceId }: TopologyBoardProps) {
  const { nodes, edges } = useWorkspaceTopology();

  return (
    <section className="rounded-lg border border-slate-200 p-4 bg-white">
      <h3 className="font-semibold text-slate-900 mb-3">Topology</h3>
      <div className="text-xs text-slate-500 mb-2">workspace: {workspaceId}</div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <h4 className="text-sm font-medium mb-2">Nodes ({nodes.length})</h4>
          <ul className="space-y-1">
            {nodes.map((node) => (
              <li key={node.id} className="text-sm border rounded px-2 py-1">
                {node.title || node.id} · {node.node_type}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className="text-sm font-medium mb-2">Edges ({edges.length})</h4>
          <ul className="space-y-1">
            {edges.map((edge) => (
              <li key={edge.id} className="text-sm border rounded px-2 py-1">
                {edge.source_node_id} → {edge.target_node_id}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
