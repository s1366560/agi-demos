/**
 * CytoscapeGraph Root Component
 *
 * Main container component that supports:
 * - Config object API
 * - Composite component pattern
 * - Legacy props API (backward compatible)
 */

import React, { useState, createContext, useContext, useCallback } from 'react'

import { useThemeStore } from '@/stores/theme'

import { createGraphConfig, legacyPropsToConfig, THEME_COLORS } from './Config'
import { CytoscapeGraphControls as ControlsComponent } from './Controls'
import { CytoscapeGraphNodeInfoPanel as NodeInfoPanelComponent } from './NodeInfoPanel'
import { CytoscapeGraphViewport } from './Viewport'

import type { GraphConfig, NodeData, GraphActions } from './types'

// ========================================
// Context for Composite Pattern
// ========================================

interface GraphContextValue {
    config: GraphConfig
    nodeCount: number
    edgeCount: number
    loading: boolean
    error: string | null
    selectedNode: NodeData | null
    setSelectedNode: (node: NodeData | null) => void
    actions: GraphActions
}

const GraphContext = createContext<GraphContextValue | null>(null)

export const useGraphContext = () => {
    const context = useContext(GraphContext)
    if (!context) {
        throw new Error('useGraphContext must be used within CytoscapeGraph')
    }
    return context
}

// ========================================
// Sub-Components (Composite Pattern)
// ========================================

// These are marker components that get detected and rendered properly
// When used in composite mode, they need to render the actual implementation

const VIEWPORT_SYMBOL = Symbol('CytoscapeGraphViewport')
const CONTROLS_SYMBOL = Symbol('CytoscapeGraphControls')
const NODE_INFO_PANEL_SYMBOL = Symbol('CytoscapeGraphNodeInfoPanel')

interface ViewportMarkerProps {
    projectId?: string
    tenantId?: string
    includeCommunities?: boolean
    minConnections?: number
    subgraphNodeIds?: string[]
    onNodeClick?: (node: NodeData | null) => void
    highlightNodeIds?: string[]
}

interface ControlsMarkerProps {
    className?: string
    renderCustom?: React.ReactNode
}

interface NodeInfoPanelMarkerProps {
    node?: NodeData | null
    onClose?: () => void
    position?: 'right' | 'left' | 'float'
    className?: string
}

CytoscapeGraph.Viewport = function CytoscapeGraphViewportMarker(_props: ViewportMarkerProps) {
    // This is a marker component - actual rendering happens in parent
    return null
}
;(CytoscapeGraph.Viewport as any)[VIEWPORT_SYMBOL] = true

CytoscapeGraph.Controls = function CytoscapeGraphControlsMarker(_props: ControlsMarkerProps) {
    // This is a marker component - actual rendering happens in parent
    return null
}
;(CytoscapeGraph.Controls as any)[CONTROLS_SYMBOL] = true

CytoscapeGraph.NodeInfoPanel = function CytoscapeGraphNodeInfoPanelMarker(_props: NodeInfoPanelMarkerProps) {
    // This is a marker component - actual rendering happens in parent
    return null
}
;(CytoscapeGraph.NodeInfoPanel as any)[NODE_INFO_PANEL_SYMBOL] = true

// Set display names for testing
;(CytoscapeGraph.Viewport as any).displayName = 'CytoscapeGraphViewport'
;(CytoscapeGraph.Controls as any).displayName = 'CytoscapeGraphControls'
;(CytoscapeGraph.NodeInfoPanel as any).displayName = 'CytoscapeGraphNodeInfoPanel'

// ========================================
// Main Component
// ========================================

interface CytoscapeGraphProps {
    /** Configuration object (new API) */
    config?: Partial<GraphConfig>
    /** Children for composite component pattern */
    children?: React.ReactNode
    /** Legacy props for backward compatibility */
    projectId?: string
    tenantId?: string
    includeCommunities?: boolean
    minConnections?: number
    onNodeClick?: (node: NodeData | null) => void
    highlightNodeIds?: string[]
    subgraphNodeIds?: string[]
}

export function CytoscapeGraph(props: CytoscapeGraphProps) {
    const { computedTheme } = useThemeStore()

    // Parse children FIRST to detect sub-components
    const childrenArray = React.Children.toArray(props.children)
    const viewportChild = childrenArray.find((child: any) => child?.type?.[VIEWPORT_SYMBOL]) as any
    const controlsChild = childrenArray.find((child: any) => child?.type?.[CONTROLS_SYMBOL]) as any
    const nodeInfoPanelChild = childrenArray.find((child: any) => child?.type?.[NODE_INFO_PANEL_SYMBOL]) as any

    const hasSubComponents = viewportChild || controlsChild || nodeInfoPanelChild

    // Determine if using legacy API - only legacy if NO sub-components AND has legacy props
    const isLegacy = !hasSubComponents && (props.projectId !== undefined || props.config === undefined)

    // Create config from either source
    const config: GraphConfig = isLegacy
        ? legacyPropsToConfig({
            projectId: props.projectId,
            tenantId: props.tenantId,
            includeCommunities: props.includeCommunities,
            minConnections: props.minConnections
        })
        : createGraphConfig(props.config)

    // Add subgraphNodeIds from legacy API if provided
    if (props.subgraphNodeIds) {
        config.data.subgraphNodeIds = props.subgraphNodeIds
    }

    // Internal state
    const [nodeCount, setNodeCount] = useState(0)
    const [edgeCount, setEdgeCount] = useState(0)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [selectedNode, setSelectedNode] = useState<NodeData | null>(null)
    const [cyInstance, setCyInstance] = useState<any>(null)

    // Handle node selection
    const handleNodeClick = useCallback((node: NodeData | null) => {
        setSelectedNode(node)
        if (props.onNodeClick) {
            props.onNodeClick(node)
        }
    }, [props.onNodeClick])

    // Actions
    const actions: GraphActions = {
        relayout: useCallback(() => {
            if (cyInstance) {
                cyInstance.layout({
                    name: config.layout?.type || 'cose',
                    animate: config.layout?.animate !== false,
                    animationDuration: config.layout?.animationDuration || 500,
                }).run()
            }
        }, [cyInstance, config.layout]),

        fitView: useCallback(() => {
            if (cyInstance) {
                cyInstance.fit(undefined, 50)
            }
        }, [cyInstance]),

        exportImage: useCallback(() => {
            if (cyInstance) {
                const png = cyInstance.png({
                    full: true,
                    scale: 2,
                    bg: computedTheme === 'dark' ? THEME_COLORS.dark.background : THEME_COLORS.light.background
                })
                const link = document.createElement('a')
                link.href = png
                link.download = `graph-${Date.now()}.png`
                link.click()
            }
        }, [cyInstance, computedTheme]),

        reloadData: useCallback(() => {
            setLoading(true)
            setError(null)
            // Trigger reload through viewport
            window.dispatchEvent(new CustomEvent('cytoscape-reload'))
        }, []),

        clearSelection: useCallback(() => {
            setSelectedNode(null)
            if (cyInstance) {
                cyInstance.$(':selected').unselect()
            }
        }, [cyInstance])
    }

    // Extract props from sub-components
    const viewportProps = viewportChild?.props || {}
    const nodeInfoPanelProps = nodeInfoPanelChild?.props || {}

    // Merge viewport props with config
    const mergedConfig: GraphConfig = {
        ...config,
        data: {
            ...config.data,
            projectId: viewportProps.projectId ?? config.data.projectId,
            tenantId: viewportProps.tenantId ?? config.data.tenantId,
            includeCommunities: viewportProps.includeCommunities ?? config.data.includeCommunities,
            minConnections: viewportProps.minConnections ?? config.data.minConnections,
            subgraphNodeIds: viewportProps.subgraphNodeIds ?? config.data.subgraphNodeIds,
        }
    }

    // Context value
    const contextValue: GraphContextValue = {
        config: mergedConfig,
        nodeCount,
        edgeCount,
        loading,
        error,
        selectedNode: nodeInfoPanelProps.node ?? selectedNode,
        setSelectedNode: (node) => {
            setSelectedNode(node)
            const handler = nodeInfoPanelProps.onClose || viewportProps.onNodeClick
            if (node === null && handler) {
                handler()
            }
        },
        actions
    }

    // Composite component pattern - detect and render sub-components
    if (hasSubComponents && !isLegacy) {
        return (
            <GraphContext.Provider value={contextValue}>
                <div className="flex flex-col h-full relative">
                    {controlsChild && (
                        <ControlsComponent
                            setCyInstance={setCyInstance}
                        />
                    )}
                    {viewportChild && (
                        <CytoscapeGraphViewport
                            config={mergedConfig}
                            onNodeClick={viewportProps.onNodeClick || handleNodeClick}
                            onStateChange={(state) => {
                                setNodeCount(state.nodeCount)
                                setEdgeCount(state.edgeCount)
                                setLoading(state.loading)
                                setError(state.error)
                            }}
                            setCyInstance={setCyInstance}
                        />
                    )}
                    {nodeInfoPanelChild && (
                        <NodeInfoPanelComponent
                            node={nodeInfoPanelProps.node ?? selectedNode}
                            onClose={nodeInfoPanelProps.onClose || (() => setSelectedNode(null))}
                        />
                    )}
                    {!controlsChild && config.features?.showToolbar !== false && (
                        <ControlsComponent
                            setCyInstance={setCyInstance}
                        />
                    )}
                    {config.features?.showLegend !== false && (
                        <GraphLegend includeCommunities={mergedConfig.data.includeCommunities} />
                    )}
                </div>
            </GraphContext.Provider>
        )
    }

    // Default render - all sub-components included
    return (
        <GraphContext.Provider value={contextValue}>
            <div className="flex flex-col h-full">
                {config.features?.showToolbar !== false && (
                    <ControlsComponent
                        setCyInstance={setCyInstance}
                    />
                )}
                <CytoscapeGraphViewport
                    config={config}
                    onNodeClick={handleNodeClick}
                    onStateChange={(state) => {
                        setNodeCount(state.nodeCount)
                        setEdgeCount(state.edgeCount)
                        setLoading(state.loading)
                        setError(state.error)
                    }}
                    setCyInstance={setCyInstance}
                />
                {config.features?.showLegend !== false && (
                    <GraphLegend includeCommunities={config.data.includeCommunities} />
                )}
                <NodeInfoPanelComponent
                    node={selectedNode}
                    onClose={() => setSelectedNode(null)}
                />
            </div>
        </GraphContext.Provider>
    )
}

// ========================================
// Internal Components
// ========================================

interface GraphLegendProps {
    includeCommunities?: boolean
}

function GraphLegend({ includeCommunities }: GraphLegendProps) {
    const { computedTheme } = useThemeStore()
    const theme = THEME_COLORS[computedTheme]

    return (
        <div className="p-4 bg-white dark:bg-slate-800 border-t border-slate-200 dark:border-slate-700">
            <div className="flex items-center gap-6 text-sm">
                <div className="flex items-center gap-2">
                    <div className="w-4 h-4 rounded-full" style={{ backgroundColor: theme.colors.default }}></div>
                    <span className="text-slate-600 dark:text-slate-400">Entity</span>
                </div>
                <div className="flex items-center gap-2">
                    <div className="w-4 h-4 rounded-full" style={{ backgroundColor: theme.colors.episodic }}></div>
                    <span className="text-slate-600 dark:text-slate-400">Episode</span>
                </div>
                {includeCommunities !== false && (
                    <div className="flex items-center gap-2">
                        <div className="w-6 h-6 rounded-full" style={{ backgroundColor: theme.colors.community }}></div>
                        <span className="text-slate-600 dark:text-slate-400">Community</span>
                    </div>
                )}
                <div className="ml-auto text-slate-500 text-xs">
                    Drag to pan - Scroll to zoom - Click to select
                </div>
            </div>
        </div>
    )
}

// Export with display name for testing
CytoscapeGraph.displayName = 'CytoscapeGraph'
