/**
 * CytoscapeGraph Configuration
 *
 * Default configurations and constants for the CytoscapeGraph component.
 */

import type {
    GraphConfig,
    GraphDataConfig,
    GraphFeatureConfig,
    GraphLayoutConfig,
    CytoscapeStyle
} from './types'

// ========================================
// Default Configurations
// ========================================

/**
 * Default data configuration
 */
export const DEFAULT_DATA_CONFIG: GraphDataConfig = {
    projectId: undefined,
    tenantId: undefined,
    includeCommunities: true,
    minConnections: 0,
    subgraphNodeIds: undefined
}

/**
 * Default feature configuration
 */
export const DEFAULT_FEATURE_CONFIG: GraphFeatureConfig = {
    showToolbar: true,
    showLegend: true,
    showStats: true,
    enableExport: true,
    enableRelayout: true
}

/**
 * Default layout configuration
 */
export const DEFAULT_LAYOUT_CONFIG: GraphLayoutConfig = {
    type: 'cose',
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
    minTemp: 1.0
}

/**
 * Merge user config with defaults
 */
export function createGraphConfig(userConfig?: Partial<GraphConfig>): GraphConfig {
    return {
        data: { ...DEFAULT_DATA_CONFIG, ...userConfig?.data },
        features: { ...DEFAULT_FEATURE_CONFIG, ...userConfig?.features },
        layout: { ...DEFAULT_LAYOUT_CONFIG, ...userConfig?.layout },
        theme: userConfig?.theme
    }
}

/**
 * Merge legacy props into GraphConfig
 */
export function legacyPropsToConfig(props: {
    projectId?: string
    tenantId?: string
    includeCommunities?: boolean
    minConnections?: number
}): GraphConfig {
    return {
        data: {
            ...DEFAULT_DATA_CONFIG,
            projectId: props.projectId,
            tenantId: props.tenantId,
            includeCommunities: props.includeCommunities,
            minConnections: props.minConnections
        },
        features: DEFAULT_FEATURE_CONFIG,
        layout: DEFAULT_LAYOUT_CONFIG
    }
}

// ========================================
// Theme Colors
// ========================================

/**
 * Light theme colors
 */
export const LIGHT_THEME = {
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
}

/**
 * Dark theme colors
 */
export const DARK_THEME = {
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

export const THEME_COLORS = {
    light: LIGHT_THEME,
    dark: DARK_THEME
}

// ========================================
// Cytoscape Layout Options
// ========================================

/**
 * Convert GraphLayoutConfig to Cytoscape layout options
 */
export function toCytoscapeLayoutOptions(config: GraphLayoutConfig = DEFAULT_LAYOUT_CONFIG) {
    return {
        name: config.type || 'cose',
        animate: config.animate !== false,
        animationDuration: config.animationDuration || 500,
        animationEasing: config.animationEasing || 'ease-out',
        idealEdgeLength: config.idealEdgeLength || 120,
        nodeOverlap: config.nodeOverlap || 40,
        componentSpacing: config.componentSpacing || 150,
        gravity: config.gravity || 0.8,
        numIter: config.numIter || 1000,
        initialTemp: config.initialTemp || 200,
        coolingFactor: config.coolingFactor || 0.95,
        minTemp: config.minTemp || 1.0,
    }
}

// ========================================
// Cytoscape Style Generators
// ========================================

/**
 * Generate Cytoscape styles based on theme
 */
export function generateCytoscapeStyles(
    theme: typeof LIGHT_THEME,
    isDark: boolean
): CytoscapeStyle[] {
    return [
        {
            selector: 'node',
            style: {
                'background-color': (ele: any) => {
                    const type = ele.data('type')
                    const entityType = ele.data('entity_type')

                    if (type === 'Episodic') return theme.colors.episodic
                    if (type === 'Community') return theme.colors.community

                    switch (entityType) {
                        case 'Person': return theme.colors.person
                        case 'Organization': return theme.colors.organization
                        case 'Location': return theme.colors.location
                        case 'Event': return theme.colors.event
                        case 'Product': return theme.colors.product
                        default: return theme.colors.default
                    }
                },
                'label': (ele: any) => {
                    const name = ele.data('name') || ''
                    return name.length > 20 ? name.substring(0, 20) + '...' : name
                },
                'color': isDark ? '#e2e8f0' : '#1e293b',
                'width': (ele: any) => ele.data('type') === 'Community' ? 70 : 50,
                'height': (ele: any) => ele.data('type') === 'Community' ? 70 : 50,
                'font-size': '5px',
                'font-weight': '600',
                'font-family': 'Inter, "Noto Sans SC", sans-serif',
                'text-valign': 'bottom',
                'text-halign': 'center',
                'text-margin-y': 6,
                'border-width': 2,
                'border-color': theme.nodeBorder,
                'border-opacity': isDark ? 0.2 : 0.6,
                'shadow-blur': 20,
                'shadow-color': (ele: any) => {
                    const type = ele.data('type')
                    const entityType = ele.data('entity_type')
                    let color = theme.colors.default

                    if (type === 'Episodic') color = theme.colors.episodic
                    else if (type === 'Community') color = theme.colors.community
                    else {
                        switch (entityType) {
                            case 'Person': color = theme.colors.person; break;
                            case 'Organization': color = theme.colors.organization; break;
                            default: color = theme.colors.default;
                        }
                    }
                    return color
                },
                'shadow-opacity': isDark ? 0.6 : 0.3,
                'z-index': 10,
            },
        },
        {
            selector: 'node:selected',
            style: {
                'border-width': 4,
                'border-color': isDark ? '#ffffff' : '#000000',
                'border-opacity': 1,
            },
        },
        {
            selector: 'edge',
            style: {
                'width': 1.5,
                'line-color': theme.edgeLine,
                'target-arrow-color': theme.edgeLine,
                'target-arrow-shape': 'triangle',
                'curve-style': 'bezier',
                'arrow-scale': 0.8,
                'opacity': isDark ? 0.5 : 0.6,
                'label': (ele: any) => {
                    const label = ele.data('label') || ''
                    return label.length > 15 ? label.substring(0, 15) + '...' : label
                },
                'font-size': '5px',
                'font-family': 'Inter, "Noto Sans SC", sans-serif',
                'color': theme.edgeLabel,
                'text-background-color': isDark ? '#1e293b' : '#ffffff',
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
                'line-color': isDark ? '#94a3b8' : '#475569',
                'target-arrow-color': isDark ? '#94a3b8' : '#475569',
                'z-index': 999,
            },
        },
    ]
}
