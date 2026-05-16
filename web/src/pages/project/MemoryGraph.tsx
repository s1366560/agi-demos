import React, { useCallback, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { Building2, Fingerprint, X } from 'lucide-react';

import { CytoscapeGraph } from '@/components/graph/CytoscapeGraph';
import { getNodeConnectionCount } from '@/components/graph/CytoscapeGraph/nodeDetails';
import type { NodeData } from '@/components/graph/CytoscapeGraph/types';

const NODE_TYPE_CLASSES: Record<NodeData['type'], string> = {
  Entity:
    'bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-500/20 dark:text-blue-300 dark:border-blue-500/30',
  Episodic:
    'bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-500/30',
  Community:
    'bg-purple-100 text-purple-700 border-purple-200 dark:bg-purple-500/20 dark:text-purple-300 dark:border-purple-500/30',
};

export const MemoryGraph: React.FC = () => {
  const { t } = useTranslation();
  const { projectId } = useParams();
  const [selectedNode, setSelectedNode] = useState<NodeData | null>(null);
  const connectionCount = selectedNode ? getNodeConnectionCount(selectedNode) : null;

  const handleNodeClick = useCallback((node: NodeData | null) => {
    setSelectedNode(node);
  }, []);

  return (
    <div
      data-testid="memory-graph-page"
      className="relative h-[calc(100vh-8rem)] min-h-[680px] overflow-hidden font-display"
    >
      <CytoscapeGraph>
        <CytoscapeGraph.Viewport
          projectId={projectId}
          includeCommunities={true}
          minConnections={0}
          onNodeClick={handleNodeClick}
        />
      </CytoscapeGraph>

      {/* Node Detail Panel - Fixed to right side */}
      <div
        data-testid="graph-node-detail-panel"
        className={`absolute inset-x-4 bottom-4 top-auto z-20 flex max-h-[70%] w-auto flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl transition-transform duration-300 dark:border-[#2b324a] dark:bg-[#1e2332] sm:bottom-6 sm:left-auto sm:right-6 sm:top-6 sm:max-h-none sm:w-80 ${selectedNode ? 'translate-y-0 sm:translate-x-0' : 'translate-y-[120%] sm:translate-x-[120%] sm:translate-y-0'}`}
      >
        {selectedNode ? (
          <>
            <div className="p-5 border-b border-slate-200 dark:border-[#2b324a] bg-gradient-to-r from-blue-50 to-transparent dark:from-blue-900/10 dark:to-transparent">
              <div className="flex justify-between items-start mb-2">
                <div
                  className={`px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wide border ${NODE_TYPE_CLASSES[selectedNode.type]}`}
                >
                  {selectedNode.type}
                </div>
                <button
                  type="button"
                  aria-label={t('common.close', { defaultValue: 'Close' })}
                  onClick={() => {
                    setSelectedNode(null);
                  }}
                  className="text-slate-400 hover:text-slate-600 dark:hover:text-white transition-colors"
                >
                  <X size={20} />
                </button>
              </div>
              <h2 className="text-xl font-bold text-slate-900 dark:text-white leading-tight">
                {selectedNode.name}
              </h2>
              {selectedNode.uuid && (
                <div className="flex items-center gap-2 mt-2 text-xs text-slate-400">
                  <Fingerprint size={14} />
                  <span className="font-mono text-slate-500">
                    {selectedNode.uuid.slice(0, 8)}...
                  </span>
                </div>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-6">
              {connectionCount !== null && (
                <div>
                  <div className="flex justify-between items-end mb-1">
                    <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">
                      {t('project.graph.node_detail.connections')}
                    </span>
                    <span className="text-slate-900 dark:text-white font-bold text-sm">
                      {connectionCount}
                    </span>
                  </div>
                </div>
              )}

              {/* Entity Type */}
              {selectedNode.entity_type && (
                <div>
                  <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase mb-2 block">
                    {t('project.graph.node_detail.type')}
                  </span>
                  <p className="text-sm text-slate-700 dark:text-slate-300">
                    {selectedNode.entity_type}
                  </p>
                </div>
              )}

              {/* Summary */}
              {selectedNode.summary && (
                <div>
                  <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase mb-2 block">
                    {t('project.graph.node_detail.description')}
                  </span>
                  <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                    {selectedNode.summary}
                  </p>
                </div>
              )}

              {/* Member Count */}
              {selectedNode.member_count !== undefined && (
                <div>
                  <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase mb-2 block">
                    {t('project.graph.node_detail.members')}
                  </span>
                  <p className="text-sm text-slate-700 dark:text-slate-300">
                    {t('project.graph.node_detail.entities_count', {
                      count: selectedNode.member_count,
                    })}
                  </p>
                </div>
              )}

              {/* Context Info */}
              {selectedNode.tenant_id && (
                <div className="pt-4 border-t border-slate-200 dark:border-[#2b324a]">
                  <div className="space-y-2 text-xs text-slate-500">
                    <div className="flex items-center gap-2">
                      <Building2 size={16} />
                      <span>
                        {t('project.graph.node_detail.tenant')}: {selectedNode.tenant_id}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex items-center justify-center h-full text-slate-500">
            {t('project.graph.node_detail.select_prompt')}
          </div>
        )}
      </div>
    </div>
  );
};

export default MemoryGraph;
