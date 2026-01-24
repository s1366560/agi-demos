import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import cytoscape, { Core, ElementDefinition } from 'cytoscape'
import { graphService } from '../services/graphService'
import { useThemeStore } from '../stores/theme'

// Theme configuration
const THEME_COLORS = {
    light: {
        background: '#f8fafc', // slate-50
        nodeBorder: '#ffffff',
        edgeLine: '#cbd5e1', // slate-300
        edgeLabel: '#64748b', // slate-500
        colors: {
            episodic: '#10B981', // emerald-500
            community: '#7C3AED', // violet-600
            person: '#E11D48', // rose-600
            organization: '#9333EA', // purple-600
            location: '#0891B2', // cyan-600
            event: '#D97706', // amber-600
            product: '#2563EB', // blue-600
            default: '#3B82F6', // blue-500
        }
    },
    dark: {
        background: '#111521', // dark background
        nodeBorder: '#ffffff',
        edgeLine: '#475569', // slate-600
        edgeLabel: '#94A3B8', // slate-400
        colors: {
            episodic: '#34D399', // emerald-400
            community: '#A78BFA', // violet-400
            person: '#FB7185', // rose-400
            organization: '#C084FC', // purple-400
            location: '#22D3EE', // cyan-400
            event: '#FBBF24', // amber-400
            product: '#60A5FA', // blue-400
            default: '#60A5FA', // blue-400
        }
    }
}

interface CytoscapeGraphProps {
    projectId?: string
    tenantId?: string
    includeCommunities?: boolean
    minConnections?: number
    onNodeClick?: (node: any) => void
    highlightNodeIds?: string[]
    subgraphNodeIds?: string[]
}

// Cytoscape Layout Configuration
const layoutOptions = {
    name: 'cose' as const,
    animate: true,
    animationDuration: 500,
    animationEasing: 'ease-out',
    idealEdgeLength: 120,
    nodeOverlap: 40,
    componentSpacing: 150,
    gravity: 0.8,
    numIter: 1000,
    initialTemp: 200,
    coolingFactor: 0.95,
    minTemp: 1.0,
}

export const CytoscapeGraph: React.FC<CytoscapeGraphProps> = ({
    projectId,
    tenantId,
    includeCommunities = true,
    minConnections = 0,
    onNodeClick,
    subgraphNodeIds,
}) => {
    const containerRef = useRef<HTMLDivElement>(null)
    const cyRef = useRef<Core | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [nodeCount, setNodeCount] = useState(0)
    const [edgeCount, setEdgeCount] = useState(0)
    const onNodeClickRef = useRef(onNodeClick)

    // Get current theme
    const { computedTheme } = useThemeStore()
    const currentTheme = THEME_COLORS[computedTheme]

    useEffect(() => {
        onNodeClickRef.current = onNodeClick
    }, [onNodeClick])

    // Generate styles based on theme
    const cytoscapeStyles = useMemo(() => [
        {
            selector: 'node',
            style: {
                'background-color': (ele: any) => {
                    const type = ele.data('type')
                    const entityType = ele.data('entity_type')

                    if (type === 'Episodic') return currentTheme.colors.episodic
                    if (type === 'Community') return currentTheme.colors.community

                    switch (entityType) {
                        case 'Person': return currentTheme.colors.person
                        case 'Organization': return currentTheme.colors.organization
                        case 'Location': return currentTheme.colors.location
                        case 'Event': return currentTheme.colors.event
                        case 'Product': return currentTheme.colors.product
                        default: return currentTheme.colors.default
                    }
                },
                'label': (ele: any) => {
                    const name = ele.data('name') || ''
                    return name.length > 20 ? name.substring(0, 20) + '...' : name
                },
                'color': computedTheme === 'dark' ? '#e2e8f0' : '#1e293b', // Label color
                'width': (ele: any) => ele.data('type') === 'Community' ? 70 : 50,
                'height': (ele: any) => ele.data('type') === 'Community' ? 70 : 50,
                'font-size': '5px',
                'font-weight': '600',
                'font-family': 'Inter, "Noto Sans SC", sans-serif',
                'text-valign': 'bottom',
                'text-halign': 'center',
                'text-margin-y': 6,
                'border-width': 2,
                'border-color': currentTheme.nodeBorder,
                'border-opacity': computedTheme === 'dark' ? 0.2 : 0.6,
                'shadow-blur': 20,
                'shadow-color': (ele: any) => {
                    const type = ele.data('type')
                    const entityType = ele.data('entity_type')
                    let color = currentTheme.colors.default

                    if (type === 'Episodic') color = currentTheme.colors.episodic
                    else if (type === 'Community') color = currentTheme.colors.community
                    else {
                        switch (entityType) {
                            case 'Person': color = currentTheme.colors.person; break;
                            case 'Organization': color = currentTheme.colors.organization; break;
                            default: color = currentTheme.colors.default;
                        }
                    }
                    return color
                },
                'shadow-opacity': computedTheme === 'dark' ? 0.6 : 0.3,
                'z-index': 10,
            } as any,
        },
        {
            selector: 'node:selected',
            style: {
                'border-width': 4,
                'border-color': computedTheme === 'dark' ? '#ffffff' : '#000000',
                'border-opacity': 1,
            },
        },
        {
            selector: 'edge',
            style: {
                'width': 1.5,
                'line-color': currentTheme.edgeLine,
                'target-arrow-color': currentTheme.edgeLine,
                'target-arrow-shape': 'triangle',
                'curve-style': 'bezier',
                'arrow-scale': 0.8,
                'opacity': computedTheme === 'dark' ? 0.5 : 0.6,
                'label': (ele: any) => {
                    const label = ele.data('label') || ''
                    return label.length > 15 ? label.substring(0, 15) + '...' : label
                },
                'font-size': '5px',
                'font-family': 'Inter, "Noto Sans SC", sans-serif',
                'color': currentTheme.edgeLabel,
                'text-background-color': computedTheme === 'dark' ? '#1e293b' : '#ffffff',
                'text-background-opacity': 0.8,
                'text-background-padding': '2px',
                'text-background-shape': 'roundrectangle',
            },
        },
        {
            selector: 'edge:selected',
            style: {
                'width': 2,
                'opacity': 1,
                'line-color': computedTheme === 'dark' ? '#94a3b8' : '#475569',
                'target-arrow-color': computedTheme === 'dark' ? '#94a3b8' : '#475569',
                'z-index': 999,
            },
        },
    ], [computedTheme, currentTheme])

    // Load Graph Data
    const loadGraphData = useCallback(async () => {
        if (!cyRef.current) return

        setLoading(true)
        setError(null)

        try {
            let data;
            if (subgraphNodeIds && subgraphNodeIds.length > 0) {
                data = await graphService.getSubgraph({
                    node_uuids: subgraphNodeIds,
                    include_neighbors: true,
                    limit: 500,
                    tenant_id: tenantId,
                    project_id: projectId
                })
            } else {
                data = await graphService.getGraphData({
                    tenant_id: tenantId,
                    project_id: projectId,
                    limit: 500,
                })
            }

            const elements: ElementDefinition[] = []

            // Nodes
            data.elements.nodes.forEach((node: any) => {
                const nodeType = node.data.label

                if (!includeCommunities && nodeType === 'Community') return
                if (minConnections > 0) {
                    const connections = data.elements.edges.filter(
                        (e: any) => e.data.source === node.data.id || e.data.target === node.data.id
                    ).length
                    if (connections < minConnections) return
                }

                elements.push({
                    group: 'nodes',
                    data: {
                        id: node.data.id,
                        label: nodeType,
                        name: node.data.name || node.data.label,
                        type: nodeType,
                        uuid: node.data.uuid,
                        summary: node.data.summary,
                        entity_type: node.data.entity_type,
                        member_count: node.data.member_count,
                        tenant_id: node.data.tenant_id,
                        project_id: node.data.project_id,
                    },
                })
            })

            // Edges
            data.elements.edges.forEach((edge: any) => {
                elements.push({
                    group: 'edges',
                    data: {
                        id: edge.data.id,
                        source: edge.data.source,
                        target: edge.data.target,
                        label: edge.data.label || '',
                    },
                })
            })

            // Clear existing elements and add new ones to ensure clean state
            cyRef.current.elements().remove()
            cyRef.current.add(elements)

            cyRef.current.layout(layoutOptions).run()

            setNodeCount(elements.filter(e => e.group === 'nodes').length)
            setEdgeCount(elements.filter(e => e.group === 'edges').length)

        } catch (err) {
            console.error('Failed to load graph data:', err)
            setError('Failed to load graph data')
        } finally {
            setLoading(false)
        }
    }, [projectId, tenantId, includeCommunities, minConnections, subgraphNodeIds])

    // Initialize Cytoscape
    useEffect(() => {
        if (!containerRef.current) return

        const cy = cytoscape({
            container: containerRef.current,
            style: cytoscapeStyles,
            minZoom: 0.1,
            maxZoom: 3,
            wheelSensitivity: 0.2,
        })

        cyRef.current = cy

        cy.on('tap', 'node', (evt) => {
            const node = evt.target
            console.log('Node clicked:', node.data())
            onNodeClick?.(node.data())
        })

        cy.on('tap', 'edge', (evt) => {
            const edge = evt.target
            console.log('Edge clicked:', edge.data())
        })

        cy.on('tap', (evt) => {
            if (evt.target === cy) {
                onNodeClick?.(null)
            }
        })

        cy.boxSelectionEnabled(true)

        return () => {
            cy.destroy()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []) // Initialize once

    // Update styles when theme changes
    useEffect(() => {
        if (cyRef.current) {
            cyRef.current.style(cytoscapeStyles)
        }
    }, [cytoscapeStyles])

    // Load data
    useEffect(() => {
        if (cyRef.current) {
            loadGraphData()
        }
    }, [loadGraphData])

    // Export Image
    const exportImage = () => {
        if (!cyRef.current) return

        const png = cyRef.current.png({
            full: true,
            scale: 2,
            bg: computedTheme === 'dark' ? '#111521' : '#ffffff'
        })

        const link = document.createElement('a')
        link.href = png
        link.download = `graph-${Date.now()}.png`
        link.click()
    }

    const relayout = () => {
        if (!cyRef.current) return
        cyRef.current.layout(layoutOptions).run()
    }

    const fitView = () => {
        if (!cyRef.current) return
        cyRef.current.fit(undefined, 50)
    }

    return (
        <div className="flex flex-col h-full">
            {/* Toolbar */}
            <div className="flex items-center justify-between p-4 bg-white dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700">
                <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
                        <span>Nodes:</span>
                        <span className="font-semibold text-slate-900 dark:text-white">{nodeCount}</span>
                    </div>
                    <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
                        <span>Edges:</span>
                        <span className="font-semibold text-slate-900 dark:text-white">{edgeCount}</span>
                    </div>
                </div>

                <div className="flex items-center gap-2">
                    <button
                        onClick={relayout}
                        className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                        title="Relayout"
                    >
                        <span className="material-symbols-outlined">refresh</span>
                    </button>
                    <button
                        onClick={fitView}
                        className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                        title="Fit to View"
                    >
                        <span className="material-symbols-outlined">center_focus_strong</span>
                    </button>
                    <button
                        onClick={loadGraphData}
                        className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                        title="Reload Data"
                    >
                        <span className="material-symbols-outlined">sync</span>
                    </button>
                    <button
                        onClick={exportImage}
                        className="p-2 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white rounded-md hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                        title="Export as PNG"
                    >
                        <span className="material-symbols-outlined">download</span>
                    </button>
                </div>
            </div>

            {/* Cytoscape Container */}
            <div className="flex-1 relative">
                {loading && (
                    <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm">
                        <div className="text-center">
                            <span className="material-symbols-outlined text-4xl text-blue-600 animate-spin">
                                progress_activity
                            </span>
                            <p className="text-slate-600 dark:text-slate-400 mt-2">Loading graph...</p>
                        </div>
                    </div>
                )}

                {error && (
                    <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm">
                        <div className="text-center">
                            <span className="material-symbols-outlined text-4xl text-red-600">error</span>
                            <p className="text-slate-600 dark:text-slate-400 mt-2">{error}</p>
                            <button
                                onClick={loadGraphData}
                                className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-500"
                            >
                                Retry
                            </button>
                        </div>
                    </div>
                )}

                <div
                    ref={containerRef}
                    className="w-full h-full bg-slate-50 dark:bg-[#111521]"
                />
            </div>

            {/* Legend */}
            <div className="p-4 bg-white dark:bg-slate-800 border-t border-slate-200 dark:border-slate-700">
                <div className="flex items-center gap-6 text-sm">
                    <div className="flex items-center gap-2">
                        <div className="w-4 h-4 rounded-full" style={{ backgroundColor: currentTheme.colors.default }}></div>
                        <span className="text-slate-600 dark:text-slate-400">Entity</span>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="w-4 h-4 rounded-full" style={{ backgroundColor: currentTheme.colors.episodic }}></div>
                        <span className="text-slate-600 dark:text-slate-400">Episode</span>
                    </div>
                    {includeCommunities && (
                        <div className="flex items-center gap-2">
                            <div className="w-6 h-6 rounded-full" style={{ backgroundColor: currentTheme.colors.community }}></div>
                            <span className="text-slate-600 dark:text-slate-400">Community</span>
                        </div>
                    )}
                    <div className="ml-auto text-slate-500 text-xs">
                        🖱️ Drag to pan • Scroll to zoom • Click to select
                    </div>
                </div>
            </div>
        </div>
    )
}

export default CytoscapeGraph
