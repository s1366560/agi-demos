import { memo, useState, useCallback } from 'react';
import type { FC } from 'react';

import { Bot, ChevronRight, ChevronDown, Circle } from 'lucide-react';

import type { AgentNode } from '../../../types/multiAgent';

interface MultiAgentPanelProps {
  agentNodes: Map<string, AgentNode> | undefined;
}

const STATUS_STYLES: Record<AgentNode['status'], { color: string; bg: string; label: string }> = {
  pending: {
    color: 'text-slate-500 dark:text-slate-400',
    bg: 'bg-slate-100 dark:bg-slate-800',
    label: 'Pending',
  },
  running: {
    color: 'text-blue-600 dark:text-blue-400',
    bg: 'bg-blue-50 dark:bg-blue-900/30',
    label: 'Running',
  },
  completed: {
    color: 'text-green-600 dark:text-green-400',
    bg: 'bg-green-50 dark:bg-green-900/30',
    label: 'Completed',
  },
  failed: {
    color: 'text-red-600 dark:text-red-400',
    bg: 'bg-red-50 dark:bg-red-900/30',
    label: 'Failed',
  },
  stopped: {
    color: 'text-amber-600 dark:text-amber-400',
    bg: 'bg-amber-50 dark:bg-amber-900/30',
    label: 'Stopped',
  },
};

interface AgentNodeItemProps {
  node: AgentNode;
  agentNodes: Map<string, AgentNode>;
  depth: number;
}

const AgentNodeItem: FC<AgentNodeItemProps> = memo(({ node, agentNodes, depth }) => {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;
  const style = STATUS_STYLES[node.status];

  const toggleExpand = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  return (
    <div>
      <div
        className={`flex items-start gap-2 rounded-lg p-2 transition-colors
            hover:bg-slate-50 dark:hover:bg-slate-800/50`}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={toggleExpand}
            className="mt-0.5 flex-shrink-0 p-0.5 rounded hover:bg-slate-200
                dark:hover:bg-slate-700 transition-colors"
          >
            {expanded ? (
              <ChevronDown size={14} className="text-slate-500" />
            ) : (
              <ChevronRight size={14} className="text-slate-500" />
            )}
          </button>
        ) : (
          <span className="mt-0.5 flex-shrink-0 w-5 flex items-center justify-center">
            <Circle size={6} className="text-slate-300 dark:text-slate-600" />
          </span>
        )}

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Bot size={14} className={style.color} />
            <span className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
              {node.name ?? node.agentId.slice(0, 8)}
            </span>
            <span
              className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px]
                  font-medium ${style.color} ${style.bg}`}
            >
              {style.label}
            </span>
          </div>

          {node.taskSummary ? (
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
              {node.taskSummary}
            </p>
          ) : null}

          {node.result && node.status === 'completed' ? (
            <p className="mt-0.5 text-xs text-green-600 dark:text-green-400 line-clamp-1">
              {node.result}
            </p>
          ) : null}

          {node.result && node.status === 'failed' ? (
            <p className="mt-0.5 text-xs text-red-600 dark:text-red-400 line-clamp-1">
              {node.result}
            </p>
          ) : null}
        </div>
      </div>

      {expanded && hasChildren
        ? node.children.map((childId) => {
            const child = agentNodes.get(childId);
            return child ? (
              <AgentNodeItem key={childId} node={child} agentNodes={agentNodes} depth={depth + 1} />
            ) : null;
          })
        : null}
    </div>
  );
});

AgentNodeItem.displayName = 'AgentNodeItem';

const EmptyAgentState: FC = memo(() => (
  <div className="flex flex-col items-center justify-center p-8 text-center">
    <div className="w-12 h-12 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-3">
      <Bot size={24} className="text-slate-400 dark:text-slate-500" />
    </div>
    <p className="text-sm text-slate-500 dark:text-slate-400">No agents spawned yet</p>
    <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
      Multi-agent activity will appear here when agents are spawned during a conversation.
    </p>
  </div>
));

EmptyAgentState.displayName = 'EmptyAgentState';

export const MultiAgentPanel: FC<MultiAgentPanelProps> = memo(({ agentNodes }) => {
  if (!agentNodes || agentNodes.size === 0) {
    return <EmptyAgentState />;
  }

  const roots: AgentNode[] = [];
  agentNodes.forEach((node) => {
    if (node.parentAgentId === null || !agentNodes.has(node.parentAgentId)) {
      roots.push(node);
    }
  });

  const sortedRoots = [...roots].sort((a, b) => a.createdAt - b.createdAt);

  return (
    <div className="p-2 space-y-1">
      {sortedRoots.map((root) => (
        <AgentNodeItem key={root.agentId} node={root} agentNodes={agentNodes} depth={0} />
      ))}
    </div>
  );
});

MultiAgentPanel.displayName = 'MultiAgentPanel';
