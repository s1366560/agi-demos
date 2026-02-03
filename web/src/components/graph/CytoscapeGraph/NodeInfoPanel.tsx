/**
 * CytoscapeGraph NodeInfoPanel Component
 *
 * Displays details about the selected graph node.
 */

import React from 'react'
import { useTranslation } from 'react-i18next'
import { useGraphContext } from './CytoscapeGraph'
import type { NodeData } from './types'

// ========================================
// Props
// ========================================

interface NodeInfoPanelProps {
    node?: NodeData | null
    onClose?: () => void
}

// ========================================
// Main NodeInfoPanel Component
// ========================================

export function CytoscapeGraphNodeInfoPanel({ node: propNode, onClose }: NodeInfoPanelProps) {
    const { t } = useTranslation()
    const context = useGraphContext()

    // Use prop node if provided (explicitly passed), otherwise use context
    const node = propNode !== undefined ? propNode : context.selectedNode

    const handleClose = () => {
        context.setSelectedNode(null)
        context.actions.clearSelection()
        onClose?.()
    }

    return (
        <div className={`absolute top-6 right-6 bottom-6 w-80 bg-white dark:bg-[#1e2332] border border-slate-200 dark:border-[#2b324a] shadow-2xl rounded-xl z-20 flex flex-col overflow-hidden transition-transform duration-300 ${node ? 'translate-x-0' : 'translate-x-[120%]'}`}>
            {node ? (
                <>
                    <div className="p-5 border-b border-slate-200 dark:border-[#2b324a] bg-gradient-to-r from-blue-50 to-transparent dark:from-blue-900/10 dark:to-transparent">
                        <div className="flex justify-between items-start mb-2">
                            <div className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide border ${
                                node.type === 'Entity'
                                    ? 'bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-500/20 dark:text-blue-300 dark:border-blue-500/30'
                                    : node.type === 'Episodic'
                                        ? 'bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-500/30'
                                        : node.type === 'Community'
                                            ? 'bg-purple-100 text-purple-700 border-purple-200 dark:bg-purple-500/20 dark:text-purple-300 dark:border-purple-500/30'
                                            : 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-500/20 dark:text-slate-300 dark:border-slate-500/30'
                            }`}>
                                {node.type}
                            </div>
                            <button
                                onClick={handleClose}
                                className="text-slate-400 hover:text-slate-600 dark:hover:text-white transition-colors"
                            >
                                <span className="material-symbols-outlined text-[20px]">close</span>
                            </button>
                        </div>
                        <h2 className="text-xl font-bold text-slate-900 dark:text-white leading-tight">
                            {node.name}
                        </h2>
                        {node.uuid && (
                            <div className="flex items-center gap-2 mt-2 text-xs text-slate-400">
                                <span className="material-symbols-outlined text-[14px]">fingerprint</span>
                                <span className="font-mono text-slate-500">{node.uuid.slice(0, 8)}...</span>
                            </div>
                        )}
                    </div>

                    <div className="flex-1 overflow-y-auto p-5 space-y-6">
                        {/* Impact Score / Stats Placeholder */}
                        <div>
                            <div className="flex justify-between items-end mb-1">
                                <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase">
                                    {t('project.graph.node_detail.relevance', 'Relevance')}
                                </label>
                                <span className="text-emerald-600 dark:text-emerald-400 font-bold text-sm">
                                    {t('project.graph.node_detail.high', 'High')}
                                </span>
                            </div>
                            <div className="w-full bg-slate-100 dark:bg-[#111521] rounded-full h-1.5 overflow-hidden">
                                <div className="bg-gradient-to-r from-emerald-500 to-blue-600 h-full rounded-full" style={{ width: '85%' }}></div>
                            </div>
                        </div>

                        {/* Entity Type */}
                        {node.entity_type && (
                            <div>
                                <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase mb-2 block">
                                    {t('project.graph.node_detail.type', 'Type')}
                                </label>
                                <p className="text-sm text-slate-700 dark:text-slate-300">{node.entity_type}</p>
                            </div>
                        )}

                        {/* Summary */}
                        {node.summary && (
                            <div>
                                <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase mb-2 block">
                                    {t('project.graph.node_detail.description', 'Description')}
                                </label>
                                <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
                                    {node.summary}
                                </p>
                            </div>
                        )}

                        {/* Member Count */}
                        {node.member_count !== undefined && (
                            <div>
                                <label className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase mb-2 block">
                                    {t('project.graph.node_detail.members', 'Members')}
                                </label>
                                <p className="text-sm text-slate-700 dark:text-slate-300">{node.member_count} entities</p>
                            </div>
                        )}

                        {/* Context Info */}
                        {node.tenant_id && (
                            <div className="pt-4 border-t border-slate-200 dark:border-[#2b324a]">
                                <div className="space-y-2 text-xs text-slate-500">
                                    <div className="flex items-center gap-2">
                                        <span className="material-symbols-outlined text-[16px]">domain</span>
                                        <span>
                                            {t('project.graph.node_detail.tenant', 'Tenant')}: {node.tenant_id}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>

                    <div className="p-4 border-t border-slate-200 dark:border-[#2b324a] bg-slate-50 dark:bg-[#111521] flex gap-2">
                        <button className="flex-1 py-2 rounded-lg border border-slate-200 dark:border-[#2b324a] bg-white dark:bg-[#1e2332] text-slate-600 dark:text-slate-300 text-sm font-medium hover:bg-slate-50 dark:hover:bg-[#2b324a] hover:text-slate-900 dark:hover:text-white transition-colors">
                            {t('project.graph.node_detail.expand', 'Expand')}
                        </button>
                        <button className="flex-1 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 shadow-lg shadow-blue-600/20 transition-colors">
                            {t('project.graph.node_detail.edit', 'Edit')}
                        </button>
                    </div>
                </>
            ) : (
                <div className="flex items-center justify-center h-full text-slate-500">
                    {t('project.graph.node_detail.select_prompt', 'Select a node to view details')}
                </div>
            )}
        </div>
    )
}

CytoscapeGraphNodeInfoPanel.displayName = 'CytoscapeGraphNodeInfoPanel'
