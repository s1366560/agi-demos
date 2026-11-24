/**
 * CytoscapeGraph NodeInfoPanel Component
 *
 * Displays details about the selected graph node.
 */

import { useTranslation } from 'react-i18next';

import { X, Fingerprint, Building2 } from 'lucide-react';

import { useGraphContext } from './CytoscapeGraph';
import { getNodeConnectionCount } from './nodeDetails';

import type { NodeData } from './types';

// ========================================
// Props
// ========================================

interface NodeInfoPanelProps {
  node?: NodeData | null | undefined;
  onClose?: (() => void) | undefined;
}

// ========================================
// Main NodeInfoPanel Component
// ========================================

export function CytoscapeGraphNodeInfoPanel({ node: propNode, onClose }: NodeInfoPanelProps) {
  const { t } = useTranslation();
  const context = useGraphContext();

  // Use prop node if provided (explicitly passed), otherwise use context
  const node = propNode !== undefined ? propNode : context.selectedNode;
  const connectionCount = node ? getNodeConnectionCount(node) : null;

  const handleClose = () => {
    context.setSelectedNode(null);
    context.actions.clearSelection();
    onClose?.();
  };

  return (
    <div
      aria-hidden={!node}
      className={`absolute top-6 right-6 bottom-6 w-80 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark shadow-lg rounded-lg z-20 flex flex-col overflow-hidden transition-transform duration-300 ${node ? 'translate-x-0' : 'translate-x-[120%]'}`}
    >
      {node ? (
        <>
          <div className="p-5 border-b border-slate-200 dark:border-border-dark bg-slate-50 dark:bg-slate-900/30">
            <div className="flex justify-between items-start mb-2">
              <div
                className={`px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wide border ${
                  node.type === 'Entity'
                    ? 'bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-500/20 dark:text-blue-300 dark:border-blue-500/30'
                    : node.type === 'Episodic'
                      ? 'bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-500/30'
                      : 'bg-purple-100 text-purple-700 border-purple-200 dark:bg-purple-500/20 dark:text-purple-300 dark:border-purple-500/30'
                }`}
              >
                {node.type}
              </div>
              <button
                type="button"
                onClick={handleClose}
                aria-label={t('graph.nodeInfo.close', 'Close node details')}
                title={t('graph.nodeInfo.close', 'Close node details')}
                className="rounded text-slate-400 transition-colors hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:hover:text-white"
              >
                <X aria-hidden="true" size={20} />
              </button>
            </div>
            <h2 className="text-xl font-bold break-words text-slate-900 dark:text-white leading-tight">
              {node.name}
            </h2>
            {node.uuid && (
              <div className="flex items-center gap-2 mt-2 text-xs text-slate-400">
                <Fingerprint aria-hidden="true" size={14} />
                <span className="font-mono text-slate-500">{node.uuid.slice(0, 8)}…</span>
              </div>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-5 space-y-6">
            {connectionCount !== null && (
              <div>
                <div className="flex justify-between items-end mb-1">
                  <div className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">
                    {t('project.graph.node_detail.connections', 'Connections')}
                  </div>
                  <span className="text-slate-900 dark:text-white font-bold text-sm">
                    {connectionCount}
                  </span>
                </div>
              </div>
            )}

            {/* Entity Type */}
            {node.entity_type && (
              <div>
                <div className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase mb-2 block">
                  {t('project.graph.node_detail.type', 'Type')}
                </div>
                <p className="text-sm text-slate-700 dark:text-slate-300">{node.entity_type}</p>
              </div>
            )}

            {/* Summary */}
            {node.summary && (
              <div>
                <div className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase mb-2 block">
                  {t('project.graph.node_detail.description', 'Description')}
                </div>
                <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                  {node.summary}
                </p>
              </div>
            )}

            {/* Member Count */}
            {node.member_count !== undefined && (
              <div>
                <div className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase mb-2 block">
                  {t('project.graph.node_detail.members', 'Members')}
                </div>
                <p className="text-sm text-slate-700 dark:text-slate-300">
                  {t('project.graph.node_detail.entities_count', {
                    count: node.member_count,
                  })}
                </p>
              </div>
            )}

            {/* Context Info */}
            {node.tenant_id && (
              <div className="pt-4 border-t border-slate-200 dark:border-border-dark">
                <div className="space-y-2 text-xs text-slate-500">
                  <div className="flex items-center gap-2">
                    <Building2 size={16} />
                    <span>
                      {t('project.graph.node_detail.tenant', 'Tenant')}: {node.tenant_id}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </>
      ) : (
        <div className="flex items-center justify-center h-full text-slate-500">
          {t('project.graph.node_detail.select_prompt', 'Select a node to view details')}
        </div>
      )}
    </div>
  );
}

CytoscapeGraphNodeInfoPanel.displayName = 'CytoscapeGraphNodeInfoPanel';
