import React, { useState, useMemo, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { graphService } from '../../services/graphService'
import { CytoscapeGraph } from '../../components/CytoscapeGraph'
import { useProjectStore } from '../../stores/project'

// Type declarations for Web Speech API
declare global {
    interface Window {
        SpeechRecognition: any
        webkitSpeechRecognition: any
    }
}
import {
    Search,
    Mic,
    ArrowRight,
    Sliders,
    Info,
    HelpCircle,
    Network,
    Plus,
    Minus,
    Target,
    Maximize,
    Grid,
    List,
    ArrowUpDown,
    FileText,
    MessageSquare,
    Image as ImageIcon,
    Link as LinkIcon,
    ChevronDown,
    AlertCircle,
    Folder,
    X,
    Filter,
    PanelRightClose,
    PanelRightOpen,
    Copy,
    Check,
    Download
} from 'lucide-react'

interface SearchResult {
    content: string
    score: number
    metadata: {
        type: string
        name?: string
        uuid?: string
        depth?: number
        created_at?: string
        [key: string]: any
    }
    source: string
}

export const EnhancedSearch: React.FC = () => {
    const { t } = useTranslation()
    const { projectId } = useParams()
    const { currentProject } = useProjectStore()

    // State
    const [query, setQuery] = useState('')
    const [results, setResults] = useState<SearchResult[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [isSearchFocused, setIsSearchFocused] = useState(false)

    // Search Mode: 'semantic' | 'graphTraversal' | 'temporal' | 'faceted' | 'community'
    const [searchMode, setSearchMode] = useState<'semantic' | 'graphTraversal' | 'temporal' | 'faceted' | 'community'>('semantic')

    // Configuration State
    const [retrievalMode, setRetrievalMode] = useState<'hybrid' | 'nodeDistance'>('hybrid')
    const [strategy, setStrategy] = useState('COMBINED_HYBRID_SEARCH_RRF')
    const [focalNode, setFocalNode] = useState('')
    const [crossEncoder, setCrossEncoder] = useState('bge')
    const [timeRange, setTimeRange] = useState('last30')
    const [customTimeRange, setCustomTimeRange] = useState<{ since?: string; until?: string }>({})
    const [configTab, setConfigTab] = useState<'params' | 'filters'>('params')
    const [showMobileConfig, setShowMobileConfig] = useState(false)
    const [isConfigOpen, setIsConfigOpen] = useState(true)
    const [isResultsCollapsed, setIsResultsCollapsed] = useState(false)
    const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')
    const [copiedId, setCopiedId] = useState<string | null>(null)
    const [isSubgraphMode, setIsSubgraphMode] = useState(false)
    const [selectedSubgraphIds, setSelectedSubgraphIds] = useState<string[]>([])

    // Graph Traversal State
    const [startEntityUuid, setStartEntityUuid] = useState('')
    const [maxDepth, setMaxDepth] = useState(2)
    const [relationshipTypes, setRelationshipTypes] = useState<string[]>([])

    // Faceted Search State
    const [selectedEntityTypes, setSelectedEntityTypes] = useState<string[]>([])
    const [selectedTags, setSelectedTags] = useState<string[]>([])
    const [availableTags] = useState<string[]>(['architecture', 'meeting', 'decisions', 'Q3'])

    // Community Search State
    const [communityUuid, setCommunityUuid] = useState('')
    const [includeEpisodes, setIncludeEpisodes] = useState(true)

    // Voice Search State
    const [isListening, setIsListening] = useState(false)

    // Search History
    const [searchHistory, setSearchHistory] = useState<Array<{ query: string; mode: string; timestamp: number }>>([])
    const [showHistory, setShowHistory] = useState(false)

    // Help Tooltip State
    const [showTooltip, setShowTooltip] = useState<string | null>(null)

    const handleCopyId = useCallback((id: string, e: React.MouseEvent) => {
        e.stopPropagation()
        navigator.clipboard.writeText(id)
        setCopiedId(id)
        setTimeout(() => setCopiedId(null), 2000)
    }, [])

    const handleResultClick = useCallback((result: SearchResult) => {
        if (result.metadata.uuid) {
            setSelectedSubgraphIds([result.metadata.uuid])
            setIsSubgraphMode(true)
        }
    }, [])

    const handleSearch = useCallback(async () => {
        // Validate based on search mode
        if (searchMode === 'graphTraversal' && !startEntityUuid) {
            setError(t('project.search.errors.enter_start_uuid'))
            return
        }
        if (searchMode === 'community' && !communityUuid) {
            setError(t('project.search.errors.enter_community_uuid'))
            return
        }
        if ((searchMode === 'semantic' || searchMode === 'temporal' || searchMode === 'faceted') && !query) {
            setError(t('project.search.errors.enter_query'))
            return
        }

        setLoading(true)
        setError(null)

        try {
            let data: any

            switch (searchMode) {
                case 'semantic': {
                    let since = undefined
                    if (timeRange === 'last30') {
                        const date = new Date()
                        date.setDate(date.getDate() - 30)
                        since = date.toISOString()
                    } else if (timeRange === 'custom' && customTimeRange.since) {
                        since = customTimeRange.since
                    }

                    data = await graphService.advancedSearch({
                        query,
                        strategy,
                        project_id: projectId,
                        focal_node_uuid: retrievalMode === 'nodeDistance' ? focalNode : undefined,
                        reranker: crossEncoder,
                        since,
                    })
                    break
                }

                case 'graphTraversal':
                    data = await graphService.searchByGraphTraversal({
                        start_entity_uuid: startEntityUuid,
                        max_depth: maxDepth,
                        relationship_types: relationshipTypes.length > 0 ? relationshipTypes : undefined,
                        limit: 50,
                    })
                    break

                case 'temporal':
                    data = await graphService.searchTemporal({
                        query,
                        since: timeRange === 'custom' ? customTimeRange.since : undefined,
                        until: timeRange === 'custom' ? customTimeRange.until : undefined,
                        limit: 50,
                    })
                    break

                case 'faceted':
                    data = await graphService.searchWithFacets({
                        query,
                        entity_types: selectedEntityTypes.length > 0 ? selectedEntityTypes : undefined,
                        tags: selectedTags.length > 0 ? selectedTags : undefined,
                        since: timeRange === 'custom' ? customTimeRange.since : undefined,
                        limit: 50,
                    })
                    break

                case 'community':
                    data = await graphService.searchByCommunity({
                        community_uuid: communityUuid,
                        limit: 50,
                        include_episodes: includeEpisodes,
                    })
                    break
            }

            // Map the raw results to our display format
            const mappedResults = (data.results || []).map((item: any) => ({
                content: item.content || item.summary || item.text || t('project.search.results.no_content'),
                score: item.score || 0,
                metadata: {
                    ...item.metadata,  // Spread original metadata first
                    type: item.type || item.entity_type || 'Result',  // Then override with explicit type
                    uuid: item.uuid || item.metadata?.uuid,
                    name: item.name || item.metadata?.name,
                    depth: item.depth,
                    created_at: item.created_at || item.metadata?.created_at,
                    tags: item.tags || item.metadata?.tags || [],
                },
                source: item.source || 'unknown'
            }))

            setResults(mappedResults)

            // Add to search history
            if (query || startEntityUuid || communityUuid) {
                const historyItem = {
                    query: query || startEntityUuid || communityUuid || '',
                    mode: searchMode,
                    timestamp: Date.now()
                }
                setSearchHistory(prev => [historyItem, ...prev.slice(0, 9)]) // Keep last 10
            }

            // Expand results by default when search is done
            if (mappedResults.length > 0) {
                setIsResultsCollapsed(false)
                setIsSubgraphMode(true)
                // Default to the first result for subgraph
                if (mappedResults[0].metadata.uuid) {
                    setSelectedSubgraphIds([mappedResults[0].metadata.uuid])
                }
            }
        } catch (err) {
            console.error('Search failed:', err)
            setError(t('project.search.errors.search_failed'))
        } finally {
            setLoading(false)
        }
    }, [searchMode, startEntityUuid, communityUuid, query, timeRange, customTimeRange, strategy, projectId, retrievalMode, focalNode, crossEncoder, maxDepth, relationshipTypes, selectedEntityTypes, selectedTags, includeEpisodes, t])

    // Extract node IDs for graph highlighting
    const highlightNodeIds = useMemo(() => {
        const ids = new Set<string>()
        results.forEach(result => {
            if (result.metadata.uuid) {
                ids.add(result.metadata.uuid)
            }
        })
        return Array.from(ids)
    }, [results])

    // Voice Search Handler
    const handleVoiceSearch = useCallback(() => {
        if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
            setError(t('project.search.errors.voice_not_supported'))
            return
        }

        const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
        const recognition = new SpeechRecognition()

        recognition.onstart = () => {
            setIsListening(true)
        }

        recognition.onresult = (event: any) => {
            const transcript = event.results[0][0].transcript
            setQuery(transcript)
            setIsListening(false)
        }

        recognition.onerror = () => {
            setIsListening(false)
            setError(t('project.search.errors.voice_failed'))
        }

        recognition.onend = () => {
            setIsListening(false)
        }

        recognition.start()
    }, [t])

    // Export Results Handler
    const handleExportResults = useCallback(() => {
        const exportData = {
            search_mode: searchMode,
            query: query || startEntityUuid || communityUuid,
            timestamp: new Date().toISOString(),
            total_results: results.length,
            results: results.map(r => ({
                content: r.content,
                score: r.score,
                type: r.metadata.type,
                uuid: r.metadata.uuid,
                name: r.metadata.name,
                created_at: r.metadata.created_at
            }))
        }

        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `search-results-${Date.now()}.json`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
    }, [searchMode, query, startEntityUuid, communityUuid, results])

    // Toggle Tag Selection
    const handleToggleTag = useCallback((tag: string) => {
        setSelectedTags(prev =>
            prev.includes(tag)
                ? prev.filter(t => t !== tag)
                : [...prev, tag]
        )
    }, [])

    // Toggle Entity Type Selection
    const handleToggleEntityType = useCallback((type: string) => {
        setSelectedEntityTypes(prev =>
            prev.includes(type)
                ? prev.filter(t => t !== type)
                : [...prev, type]
        )
    }, [])

    // Reset subgraph mode when no results
    React.useEffect(() => {
        if (highlightNodeIds.length === 0) {
            setIsSubgraphMode(false)
        }
    }, [highlightNodeIds])

    const getScoreColor = useCallback((score: number) => {
        if (score >= 0.8) return 'text-emerald-500'
        if (score >= 0.6) return 'text-violet-500'
        if (score >= 0.4) return 'text-amber-500'
        return 'text-slate-400'
    }, [])

    const getIconForType = useCallback((type: string) => {
        switch (type?.toLowerCase()) {
            case 'document':
            case 'pdf':
            case 'file':
                return <FileText className="w-5 h-5" />
            case 'thread':
            case 'slack':
            case 'message':
                return <MessageSquare className="w-5 h-5" />
            case 'asset':
            case 'img':
            case 'image':
                return <ImageIcon className="w-5 h-5" />
            case 'reference':
            case 'web':
            case 'jira':
            case 'link':
                return <LinkIcon className="w-5 h-5" />
            case 'episode':
            case 'memory':
                return <MessageSquare className="w-5 h-5 text-blue-500" />
            case 'person':
            case 'user':
                return <FileText className="w-5 h-5 text-purple-500" />
            case 'organization':
            case 'company':
                return <Network className="w-5 h-5 text-indigo-500" />
            case 'location':
            case 'place':
                return <Target className="w-5 h-5 text-red-500" />
            case 'event':
                return <Target className="w-5 h-5 text-amber-500" />
            case 'concept':
            case 'topic':
                return <Folder className="w-5 h-5 text-emerald-500" />
            case 'product':
                return <FileText className="w-5 h-5 text-cyan-500" />
            default:
                // Fallback for unknown entity types - use a generic entity icon
                return <Network className="w-5 h-5 text-slate-400" />
        }
    }, [FileText, MessageSquare, ImageIcon, LinkIcon, Network, Target, Folder])

    return (
        <div className="bg-slate-50 dark:bg-[#121520] text-slate-900 dark:text-white font-sans h-full flex overflow-hidden">
            {/* Sidebar would go here if not provided by layout */}

            <main className="flex-1 flex flex-col min-w-0 bg-slate-50 dark:bg-[#121520]">
                {/* Header */}
                <header className="flex flex-col gap-4 px-6 pt-6 pb-2 shrink-0">
                    {/* Search Mode Selector */}
                    <div className="flex flex-wrap gap-2 items-center">
                        <button
                            onClick={() => setSearchMode('semantic')}
                            className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all flex items-center gap-2 ${searchMode === 'semantic'
                                ? 'bg-blue-600 text-white shadow-md shadow-blue-600/20'
                                : 'bg-white dark:bg-[#1e212b] text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800'
                                }`}
                        >
                            <Search className="w-4 h-4" />
                            {t('project.search.modes.semantic')}
                        </button>
                        <button
                            onClick={() => setSearchMode('graphTraversal')}
                            className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all flex items-center gap-2 ${searchMode === 'graphTraversal'
                                ? 'bg-blue-600 text-white shadow-md shadow-blue-600/20'
                                : 'bg-white dark:bg-[#1e212b] text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800'
                                }`}
                        >
                            <Network className="w-4 h-4" />
                            {t('project.search.modes.graph')}
                        </button>
                        <button
                            onClick={() => setSearchMode('temporal')}
                            className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all flex items-center gap-2 ${searchMode === 'temporal'
                                ? 'bg-blue-600 text-white shadow-md shadow-blue-600/20'
                                : 'bg-white dark:bg-[#1e212b] text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800'
                                }`}
                        >
                            <ArrowUpDown className="w-4 h-4" />
                            {t('project.search.modes.temporal')}
                        </button>
                        <button
                            onClick={() => setSearchMode('faceted')}
                            className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all flex items-center gap-2 ${searchMode === 'faceted'
                                ? 'bg-blue-600 text-white shadow-md shadow-blue-600/20'
                                : 'bg-white dark:bg-[#1e212b] text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800'
                                }`}
                        >
                            <Filter className="w-4 h-4" />
                            {t('project.search.modes.faceted')}
                        </button>
                        <button
                            onClick={() => setSearchMode('community')}
                            className={`px-4 py-2 rounded-lg text-sm font-semibold transition-all flex items-center gap-2 ${searchMode === 'community'
                                ? 'bg-blue-600 text-white shadow-md shadow-blue-600/20'
                                : 'bg-white dark:bg-[#1e212b] text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800'
                                }`}
                        >
                            <Grid className="w-4 h-4" />
                            {t('project.search.modes.community')}
                        </button>
                        <div className="flex-1"></div>
                        {/* Search History & Export */}
                        <div className="flex items-center gap-2">
                            {searchHistory.length > 0 && (
                                <button
                                    onClick={() => setShowHistory(!showHistory)}
                                    className={`px-3 py-2 rounded-lg text-xs font-semibold transition-all flex items-center gap-1.5 ${showHistory
                                        ? 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400'
                                        : 'bg-white dark:bg-[#1e212b] text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800'
                                        }`}
                                >
                                    <MessageSquare className="w-3.5 h-3.5" />
                                    {t('project.search.actions.history')} ({searchHistory.length})
                                </button>
                            )}
                            {results.length > 0 && (
                                <button
                                    onClick={handleExportResults}
                                    className="px-3 py-2 rounded-lg text-xs font-semibold bg-white dark:bg-[#1e212b] text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800 transition-all flex items-center gap-1.5"
                                >
                                    <Download className="w-3.5 h-3.5" />
                                    {t('project.search.actions.export')}
                                </button>
                            )}
                        </div>
                    </div>

                    {/* Search History Dropdown */}
                    {showHistory && searchHistory.length > 0 && (
                        <div className="bg-white dark:bg-[#1e212b] border border-slate-200 dark:border-slate-800 rounded-xl shadow-lg p-3 max-h-64 overflow-y-auto">
                            <div className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2">{t('project.search.actions.recent')}</div>
                            {searchHistory.map((item, idx) => (
                                <button
                                    key={idx}
                                    onClick={() => {
                                        setQuery(item.query)
                                        setSearchMode(item.mode as any)
                                        setShowHistory(false)
                                    }}
                                    className="w-full text-left px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors flex items-center justify-between group"
                                >
                                    <div className="flex flex-col">
                                        <span className="text-sm text-slate-900 dark:text-white truncate max-w-md">{item.query}</span>
                                        <span className="text-xs text-slate-500 capitalize">{item.mode.replace('graphTraversal', t('project.search.modes.graph'))}</span>
                                    </div>
                                    <span className="text-xs text-slate-400">
                                        {new Date(item.timestamp).toLocaleTimeString()}
                                    </span>
                                </button>
                            ))}
                        </div>
                    )}

                    <div className="flex flex-col md:flex-row gap-4 items-start md:items-center justify-between">
                        <div className="flex-1 w-full flex gap-3">
                            <button
                                onClick={() => setShowMobileConfig(true)}
                                className="lg:hidden p-3 bg-white dark:bg-[#1e212b] border border-slate-200 dark:border-slate-800 rounded-xl text-slate-500 hover:text-blue-600 transition-colors shadow-sm"
                            >
                                <Sliders className="w-5 h-5" />
                            </button>
                            <label className="flex-1 relative group">
                                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                    {searchMode === 'graphTraversal' ? (
                                        <Network className="w-5 h-5 text-slate-400 group-focus-within:text-blue-600 transition-colors" />
                                    ) : searchMode === 'community' ? (
                                        <Grid className="w-5 h-5 text-slate-400 group-focus-within:text-blue-600 transition-colors" />
                                    ) : (
                                        <Search className="w-5 h-5 text-slate-400 group-focus-within:text-blue-600 transition-colors" />
                                    )}
                                </div>
                                <input
                                    className="block w-full pl-10 pr-12 py-3 bg-white dark:bg-[#1e212b] border border-transparent focus:border-blue-600/50 ring-0 focus:ring-4 focus:ring-blue-600/10 rounded-xl text-sm placeholder-slate-400 text-slate-900 dark:text-white shadow-sm transition-all"
                                    placeholder={
                                        searchMode === 'graphTraversal'
                                            ? t('project.search.input.placeholder.graph')
                                            : searchMode === 'community'
                                                ? t('project.search.input.placeholder.community')
                                                : isSearchFocused
                                                    ? ''
                                                    : t('project.search.input.placeholder.default')
                                    }
                                    type="text"
                                    value={searchMode === 'graphTraversal' ? startEntityUuid : searchMode === 'community' ? communityUuid : query}
                                    onChange={(e) => {
                                        if (searchMode === 'graphTraversal') setStartEntityUuid(e.target.value)
                                        else if (searchMode === 'community') setCommunityUuid(e.target.value)
                                        else setQuery(e.target.value)
                                    }}
                                    onFocus={() => setIsSearchFocused(true)}
                                    onBlur={() => setIsSearchFocused(false)}
                                    onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                                />
                                {(searchMode === 'semantic' || searchMode === 'temporal' || searchMode === 'faceted') && (
                                    <div className="absolute inset-y-0 right-0 pr-2 flex items-center">
                                        <button
                                            onClick={handleVoiceSearch}
                                            className={`p-1.5 rounded-lg transition-colors ${isListening
                                                ? 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 animate-pulse'
                                                : 'text-slate-400 hover:text-blue-600 hover:bg-slate-100 dark:hover:bg-slate-700'
                                                }`}
                                            title={isListening ? t('project.search.input.listening') : t('project.search.input.voice_search')}
                                        >
                                            <Mic className="w-5 h-5" />
                                        </button>
                                    </div>
                                )}
                            </label>
                            <button
                                onClick={handleSearch}
                                disabled={loading}
                                className="h-[46px] px-6 bg-blue-600 hover:bg-blue-600/90 text-white text-sm font-semibold rounded-lg shadow-md shadow-blue-600/20 flex items-center gap-2 transition-all active:scale-95 shrink-0 disabled:opacity-50"
                            >
                                <span>{loading ? t('project.search.actions.searching') : t('project.search.actions.retrieve')}</span>
                                <ArrowRight className="w-5 h-5" />
                            </button>
                            <div className="hidden lg:flex items-center">
                                <button
                                    onClick={() => setIsConfigOpen(!isConfigOpen)}
                                    className={`p-3 h-[46px] rounded-lg transition-colors border ${isConfigOpen
                                        ? 'border-transparent text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
                                        : 'border-blue-200 dark:border-blue-900 bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                                        }`}
                                    title={isConfigOpen ? "Collapse Config" : "Expand Config"}
                                >
                                    {isConfigOpen ? <PanelRightClose className="w-5 h-5" /> : <PanelRightOpen className="w-5 h-5" />}
                                </button>
                            </div>
                        </div>
                    </div>
                </header>

                <div className="flex-1 flex overflow-hidden p-6 gap-6 pt-2">
                    {/* Config Sidebar */}
                    {/* Mobile Backdrop */}
                    {showMobileConfig && (
                        <div
                            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40 lg:hidden"
                            onClick={() => setShowMobileConfig(false)}
                        />
                    )}

                    <aside className={`
                        fixed inset-y-0 right-0 z-50 w-80 bg-slate-50 dark:bg-[#121520] lg:bg-transparent transition-all duration-300 ease-in-out lg:relative lg:transform-none lg:z-0 flex flex-col gap-6 shrink-0 h-full
                        ${showMobileConfig ? 'translate-x-0' : 'translate-x-full lg:translate-x-0'}
                        ${!isConfigOpen && 'lg:w-0 lg:overflow-hidden lg:opacity-0 lg:p-0'}
                    `}>
                        <div className="flex-1 flex flex-col gap-5 p-5 bg-white dark:bg-[#1e212b] rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-y-auto custom-scrollbar h-full">
                            <div className="flex items-center justify-between pb-2 border-b border-slate-200 dark:border-slate-800 shrink-0">
                                <h2 className="text-sm font-bold text-slate-800 dark:text-white flex items-center gap-2">
                                    <Sliders className="w-5 h-5 text-blue-600" />
                                    {t('project.search.config.title')}
                                </h2>
                                <div className="flex items-center gap-2">
                                    <span className="text-[10px] px-1.5 py-0.5 bg-blue-600/10 text-blue-600 rounded font-medium">{t('project.search.config.advanced')}</span>
                                    <button
                                        onClick={() => setShowMobileConfig(false)}
                                        className="lg:hidden p-1 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg text-slate-500 transition-colors"
                                    >
                                        <X className="w-5 h-5" />
                                    </button>
                                </div>
                            </div>

                            {/* Internal Tabs */}
                            <div className="flex p-1 bg-slate-100 dark:bg-slate-800 rounded-lg shrink-0">
                                <button
                                    onClick={() => setConfigTab('params')}
                                    className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition-all flex items-center justify-center gap-1.5 ${configTab === 'params' ? 'bg-white dark:bg-[#1e212b] text-blue-600 dark:text-white shadow-sm' : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'}`}
                                >
                                    <Sliders className="w-3.5 h-3.5" />
                                    {t('project.search.config.params')}
                                </button>
                                <button
                                    onClick={() => setConfigTab('filters')}
                                    className={`flex-1 py-1.5 text-xs font-semibold rounded-md transition-all flex items-center justify-center gap-1.5 ${configTab === 'filters' ? 'bg-white dark:bg-[#1e212b] text-blue-600 dark:text-white shadow-sm' : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'}`}
                                >
                                    <Filter className="w-3.5 h-3.5" />
                                    {t('project.search.config.filters')}
                                </button>
                            </div>

                            {/* Tab Content - Shows different options based on search mode */}
                            <div className="flex-1 flex flex-col gap-6 overflow-y-auto custom-scrollbar pr-1">
                                {searchMode === 'semantic' && configTab === 'params' && (
                                    <>
                                        {/* Retrieval Mode */}
                                        <div className="flex flex-col gap-2">
                                            <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">{t('project.search.params.retrieval_mode')}</label>
                                            <div className="bg-slate-100 dark:bg-slate-800 p-1 rounded-lg flex">
                                                <button
                                                    onClick={() => setRetrievalMode('hybrid')}
                                                    className={`flex-1 py-2 px-2 rounded-md shadow-sm text-xs font-semibold transition-all ${retrievalMode === 'hybrid' ? 'bg-white dark:bg-[#1e212b] text-blue-600 dark:text-white ring-1 ring-black/5 dark:ring-white/10' : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'}`}
                                                >
                                                    {t('project.search.params.hybrid')}
                                                </button>
                                                <button
                                                    onClick={() => setRetrievalMode('nodeDistance')}
                                                    className={`flex-1 py-2 px-2 rounded-md text-xs font-medium transition-all ${retrievalMode === 'nodeDistance' ? 'bg-white dark:bg-[#1e212b] text-blue-600 dark:text-white ring-1 ring-black/5 dark:ring-white/10' : 'text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200'}`}
                                                >
                                                    {t('project.search.params.node_distance')}
                                                </button>
                                            </div>
                                        </div>

                                        {/* Strategy Recipe */}
                                        <div className="flex flex-col gap-2">
                                            <div className="flex items-center justify-between">
                                                <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">{t('project.search.params.strategy')}</label>
                                                <div className="relative">
                                                    <Info
                                                        className="w-4 h-4 text-slate-400 cursor-help hover:text-blue-600"
                                                        onMouseEnter={() => setShowTooltip('strategy')}
                                                        onMouseLeave={() => setShowTooltip(null)}
                                                    />
                                                    {showTooltip === 'strategy' && (
                                                        <div className="absolute right-0 top-6 w-64 p-2 bg-slate-900 dark:bg-slate-700 text-white text-xs rounded-lg shadow-lg z-50">
                                                            <p className="font-semibold mb-1">{t('project.search.params.strategy_tooltip.title')}</p>
                                                            <p>{t('project.search.params.strategy_tooltip.desc')}</p>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                            <div className="relative">
                                                <select
                                                    value={strategy}
                                                    onChange={(e) => setStrategy(e.target.value)}
                                                    className="w-full text-xs py-2.5 pl-3 pr-8 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-1 focus:ring-blue-600 focus:border-blue-600 text-slate-700 dark:text-slate-200 appearance-none shadow-sm cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700/50 transition-colors"
                                                >
                                                    <option value="COMBINED_HYBRID_SEARCH_RRF">Combined Hybrid (RRF)</option>
                                                    <option value="EDGE_HYBRID_SEARCH_CROSS_ENCODER">Edge Hybrid (Cross-Encoder)</option>
                                                    <option value="HYBRID_MMR">Hybrid Search (MMR)</option>
                                                    <option value="STANDARD_DENSE">Standard Dense Only</option>
                                                </select>
                                                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
                                                    <ChevronDown className="w-4 h-4" />
                                                </div>
                                            </div>
                                        </div>

                                        {/* Focal Node UUID */}
                                        <div className="flex flex-col gap-2">
                                            <div className="flex items-center justify-between">
                                                <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">{t('project.search.params.focal_node')}</label>
                                                <div className="relative">
                                                    <HelpCircle
                                                        className="w-4 h-4 text-slate-400 cursor-help hover:text-blue-600"
                                                        onMouseEnter={() => setShowTooltip('focal')}
                                                        onMouseLeave={() => setShowTooltip(null)}
                                                    />
                                                    {showTooltip === 'focal' && (
                                                        <div className="absolute right-0 top-6 w-64 p-2 bg-slate-900 dark:bg-slate-700 text-white text-xs rounded-lg shadow-lg z-50">
                                                            <p className="font-semibold mb-1">{t('project.search.params.focal_tooltip.title')}</p>
                                                            <p>{t('project.search.params.focal_tooltip.desc')}</p>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                            <div className="relative group">
                                                <input
                                                    className="w-full text-xs py-2.5 pl-9 pr-3 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-1 focus:ring-blue-600 focus:border-blue-600 text-slate-700 dark:text-slate-200 placeholder-slate-400 transition-shadow"
                                                    placeholder="e.g. node-1234-uuid..."
                                                    type="text"
                                                    value={focalNode}
                                                    onChange={(e) => setFocalNode(e.target.value)}
                                                    disabled={retrievalMode !== 'nodeDistance'}
                                                />
                                                <Network className="absolute left-2.5 top-2.5 w-4 h-4 text-slate-400 group-focus-within:text-blue-600 transition-colors" />
                                            </div>
                                        </div>

                                        {/* Cross-Encoder Client */}
                                        <div className="flex flex-col gap-2">
                                            <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">{t('project.search.params.cross_encoder')}</label>
                                            <div className="relative">
                                                <select
                                                    value={crossEncoder}
                                                    onChange={(e) => setCrossEncoder(e.target.value)}
                                                    className="w-full text-xs py-2.5 pl-3 pr-8 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-1 focus:ring-blue-600 focus:border-blue-600 text-slate-700 dark:text-slate-200 appearance-none shadow-sm cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700/50 transition-colors"
                                                >
                                                    <option value="openai">{t('project.search.options.cross_encoders.openai')}</option>
                                                    <option value="gemini">{t('project.search.options.cross_encoders.gemini')}</option>
                                                    <option value="bge">{t('project.search.options.cross_encoders.bge')}</option>
                                                </select>
                                                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-slate-500">
                                                    <ChevronDown className="w-4 h-4" />
                                                </div>
                                            </div>
                                        </div>
                                    </>
                                )}

                                {searchMode === 'graphTraversal' && configTab === 'params' && (
                                    <>
                                        {/* Max Depth */}
                                        <div className="flex flex-col gap-2">
                                            <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">{t('project.search.params.max_depth')}</label>
                                            <div className="flex items-center gap-2">
                                                <button
                                                    onClick={() => setMaxDepth(Math.max(1, maxDepth - 1))}
                                                    className="p-2 bg-slate-100 dark:bg-slate-800 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                                                >
                                                    <Minus className="w-4 h-4" />
                                                </button>
                                                <span className="flex-1 text-center font-bold text-slate-900 dark:text-white">{maxDepth}</span>
                                                <button
                                                    onClick={() => setMaxDepth(Math.min(5, maxDepth + 1))}
                                                    className="p-2 bg-slate-100 dark:bg-slate-800 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                                                >
                                                    <Plus className="w-4 h-4" />
                                                </button>
                                            </div>
                                        </div>

                                        {/* Relationship Types */}
                                        <div className="flex flex-col gap-2">
                                            <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">{t('project.search.params.relationship_types')}</label>
                                            <div className="flex flex-wrap gap-1.5">
                                                {['RELATES_TO', 'MENTIONS', 'PART_OF', 'CONTAINS', 'BELONGS_TO'].map(rel => (
                                                    <button
                                                        key={rel}
                                                        onClick={() => setRelationshipTypes(prev =>
                                                            prev.includes(rel) ? prev.filter(r => r !== rel) : [...prev, rel]
                                                        )}
                                                        className={`px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${relationshipTypes.includes(rel)
                                                            ? 'bg-blue-600 text-white'
                                                            : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
                                                            }`}
                                                    >
                                                        {rel}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    </>
                                )}

                                {searchMode === 'temporal' && (
                                    <>
                                        {/* Time Range Selector */}
                                        <div className="flex flex-col gap-3">
                                            <div className="flex items-center justify-between">
                                                <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">{t('project.search.filters.time_range')}</h3>
                                                <button onClick={() => { setTimeRange('all'); setCustomTimeRange({}) }} className="text-xs text-blue-600 hover:underline font-medium">{t('project.search.filters.reset')}</button>
                                            </div>
                                            <div className="flex flex-col gap-1.5">
                                                <label className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer group transition-colors">
                                                    <input
                                                        className="text-blue-600 focus:ring-blue-600 bg-white dark:bg-[#1e212b] border-slate-300 dark:border-slate-600 w-3.5 h-3.5"
                                                        name="time"
                                                        type="radio"
                                                        checked={timeRange === 'all'}
                                                        onChange={() => setTimeRange('all')}
                                                    />
                                                    <span className="text-xs text-slate-700 dark:text-slate-300">{t('project.search.filters.all_time')}</span>
                                                </label>
                                                <label className={`flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer group ${timeRange === 'last30' ? 'bg-blue-600/5 border border-blue-600/10' : 'hover:bg-slate-50 dark:hover:bg-slate-800'}`}>
                                                    <input
                                                        className="text-blue-600 focus:ring-blue-600 bg-white dark:bg-[#1e212b] border-slate-300 dark:border-slate-600 w-3.5 h-3.5"
                                                        name="time"
                                                        type="radio"
                                                        checked={timeRange === 'last30'}
                                                        onChange={() => setTimeRange('last30')}
                                                    />
                                                    <span className={`text-xs font-medium ${timeRange === 'last30' ? 'text-blue-600 dark:text-blue-400' : 'text-slate-700 dark:text-slate-300'}`}>{t('project.search.filters.last_30')}</span>
                                                </label>
                                                <label className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer group transition-colors">
                                                    <input
                                                        className="text-blue-600 focus:ring-blue-600 bg-white dark:bg-[#1e212b] border-slate-300 dark:border-slate-600 w-3.5 h-3.5"
                                                        name="time"
                                                        type="radio"
                                                        checked={timeRange === 'custom'}
                                                        onChange={() => setTimeRange('custom')}
                                                    />
                                                    <span className="text-xs text-slate-700 dark:text-slate-300">{t('project.search.filters.custom')}</span>
                                                </label>
                                            </div>
                                        </div>

                                        {/* Custom Date Pickers */}
                                        {timeRange === 'custom' && (
                                            <div className="flex flex-col gap-3">
                                                <div>
                                                    <label className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 block">{t('project.search.filters.from')}</label>
                                                    <input
                                                        type="datetime-local"
                                                        value={customTimeRange.since || ''}
                                                        onChange={(e) => setCustomTimeRange(prev => ({ ...prev, since: e.target.value ? new Date(e.target.value).toISOString() : undefined }))}
                                                        className="w-full text-xs py-2.5 px-3 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-1 focus:ring-blue-600 text-slate-700 dark:text-slate-200"
                                                    />
                                                </div>
                                                <div>
                                                    <label className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2 block">{t('project.search.filters.to')}</label>
                                                    <input
                                                        type="datetime-local"
                                                        value={customTimeRange.until || ''}
                                                        onChange={(e) => setCustomTimeRange(prev => ({ ...prev, until: e.target.value ? new Date(e.target.value).toISOString() : undefined }))}
                                                        className="w-full text-xs py-2.5 px-3 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg focus:ring-1 focus:ring-blue-600 text-slate-700 dark:text-slate-200"
                                                    />
                                                </div>
                                            </div>
                                        )}
                                    </>
                                )}

                                {searchMode === 'faceted' && (
                                    <>
                                        {/* Entity Types */}
                                        <div className="flex flex-col gap-3">
                                            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">{t('project.search.filters.entity_types')}</h3>
                                            <div className="flex flex-wrap gap-1.5">
                                                {['Person', 'Organization', 'Location', 'Event', 'Concept', 'Product'].map(type => (
                                                    <button
                                                        key={type}
                                                        onClick={() => handleToggleEntityType(type)}
                                                        className={`px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${selectedEntityTypes.includes(type)
                                                            ? 'bg-blue-600 text-white'
                                                            : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
                                                            }`}
                                                    >
                                                        {type}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>

                                        <div className="h-px bg-slate-100 dark:bg-slate-700 my-1"></div>

                                        {/* Tags */}
                                        <div className="flex flex-col gap-3">
                                            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider">{t('project.search.filters.tags')}</h3>
                                            <div className="flex flex-wrap gap-1.5">
                                                {availableTags.map(tag => (
                                                    <button
                                                        key={tag}
                                                        onClick={() => handleToggleTag(tag)}
                                                        className={`px-2 py-1 rounded-md text-[10px] font-medium transition-colors ${selectedTags.includes(tag)
                                                            ? 'bg-blue-600/10 text-blue-600 border border-blue-600/10'
                                                            : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700 border border-transparent'
                                                            }`}
                                                    >
                                                        #{tag}
                                                    </button>
                                                ))}
                                                <button className="px-2 py-1 rounded-md bg-white dark:bg-slate-800 text-slate-400 dark:text-slate-500 border border-dashed border-slate-300 dark:border-slate-600 hover:border-blue-600/50 hover:text-blue-600 text-[10px] font-medium transition-colors flex items-center gap-1">
                                                    <Plus className="w-3 h-3" /> {t('project.search.filters.add_tag')}
                                                </button>
                                            </div>
                                        </div>
                                    </>
                                )}

                                {searchMode === 'community' && (
                                    <>
                                        {/* Include Episodes Toggle */}
                                        <div className="flex flex-col gap-2">
                                            <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">{t('project.search.filters.results')}</label>
                                            <label className="flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer transition-colors">
                                                <input
                                                    type="checkbox"
                                                    checked={includeEpisodes}
                                                    onChange={(e) => setIncludeEpisodes(e.target.checked)}
                                                    className="w-4 h-4 text-blue-600 focus:ring-blue-600 bg-white dark:bg-[#1e212b] border-slate-300 dark:border-slate-600 rounded"
                                                />
                                                <span className="text-xs text-slate-700 dark:text-slate-300">{t('project.search.filters.include_episodes')}</span>
                                            </label>
                                        </div>

                                        {/* Community Info */}
                                        <div className="p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
                                            <p className="text-xs text-blue-800 dark:text-blue-300">
                                                {t('project.search.filters.community_info')}
                                            </p>
                                        </div>
                                    </>
                                )}
                            </div>
                        </div>
                    </aside>

                    <div className="flex-1 flex flex-col gap-4 min-w-0 overflow-hidden">
                        {/* Error Message */}
                        {error && (
                            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-3 flex items-center gap-2">
                                <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400" />
                                <span className="text-sm text-red-800 dark:text-red-400">{error}</span>
                            </div>
                        )}

                        {/* Graph View */}
                        <section className={`
                            bg-white dark:bg-[#1e212b] rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 relative overflow-hidden group transition-all duration-300 ease-in-out
                            ${isResultsCollapsed ? 'flex-1' : 'h-[55%]'}
                        `}>
                            <div className="absolute top-4 left-4 z-10 flex gap-2">
                                <div className="bg-white/90 dark:bg-slate-800/90 backdrop-blur border border-slate-200 dark:border-slate-700 rounded-lg shadow-sm p-1 flex gap-1">
                                    <button
                                        onClick={() => setIsResultsCollapsed(!isResultsCollapsed)}
                                        className={`p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded text-slate-600 dark:text-slate-400 transition-colors ${isResultsCollapsed ? 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20' : ''}`}
                                        title={isResultsCollapsed ? t('project.search.actions.show_results') : t('project.search.actions.expand_graph')}
                                    >
                                        <Maximize className="w-4 h-4" />
                                    </button>
                                    {highlightNodeIds.length > 0 && (
                                        <button
                                            onClick={() => setIsSubgraphMode(!isSubgraphMode)}
                                            className={`p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded text-slate-600 dark:text-slate-400 transition-colors ${isSubgraphMode ? 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20' : ''}`}
                                            title={isSubgraphMode ? t('project.search.actions.show_full_graph') : t('project.search.actions.show_subgraph')}
                                        >
                                            <Network className="w-4 h-4" />
                                        </button>
                                    )}
                                </div>
                            </div>

                            {/* Real Graph Visualization */}
                            <div className="w-full h-full relative">
                                <CytoscapeGraph
                                    projectId={projectId}
                                    tenantId={currentProject?.tenant_id}
                                    highlightNodeIds={highlightNodeIds}
                                    subgraphNodeIds={isSubgraphMode ? selectedSubgraphIds : undefined}
                                    includeCommunities={true}
                                    onNodeClick={(node) => {
                                        if (node?.uuid) {
                                            setFocalNode(node.uuid)
                                            setRetrievalMode('nodeDistance')
                                        }
                                    }}
                                />
                            </div>
                        </section>

                        {/* Results List */}
                        <section className={`
                            flex flex-col gap-3 min-h-0 transition-all duration-300 ease-in-out
                            ${isResultsCollapsed ? 'h-10 overflow-hidden' : 'flex-1'}
                        `}>
                            <div
                                className="flex items-center justify-between shrink-0 px-1 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 rounded-lg p-1 transition-colors select-none"
                                onClick={() => setIsResultsCollapsed(!isResultsCollapsed)}
                            >
                                <div className="flex items-center gap-3">
                                    <div className={`transition-transform duration-300 ${isResultsCollapsed ? '-rotate-90' : 'rotate-0'}`}>
                                        <ChevronDown className="w-4 h-4 text-slate-400" />
                                    </div>
                                    <h2 className="text-base font-bold text-slate-900 dark:text-white">{t('project.search.results.title')}</h2>
                                    <span className="px-2 py-0.5 rounded-full bg-slate-200 dark:bg-slate-700 text-xs font-semibold text-slate-600 dark:text-slate-300">{results.length} {t('project.search.results.items')}</span>
                                </div>
                                <div className="flex items-center gap-3" onClick={e => e.stopPropagation()}>
                                    <div className="flex items-center bg-white dark:bg-[#1e212b] border border-slate-200 dark:border-slate-800 rounded-lg p-0.5">
                                        <button
                                            onClick={() => setViewMode('grid')}
                                            className={`p-1.5 rounded shadow-sm transition-colors ${viewMode === 'grid' ? 'bg-slate-100 dark:bg-slate-700 text-slate-900 dark:text-white' : 'hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400'}`}
                                        >
                                            <Grid className="w-4 h-4" />
                                        </button>
                                        <button
                                            onClick={() => setViewMode('list')}
                                            className={`p-1.5 rounded shadow-sm transition-colors ${viewMode === 'list' ? 'bg-slate-100 dark:bg-slate-700 text-slate-900 dark:text-white' : 'hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400'}`}
                                        >
                                            <List className="w-4 h-4" />
                                        </button>
                                    </div>
                                    <div className="h-4 w-px bg-slate-300 dark:bg-slate-700"></div>
                                    <div className="flex items-center gap-1 text-slate-500 cursor-pointer hover:text-blue-600 transition-colors group">
                                        <ArrowUpDown className="w-4 h-4 text-slate-400 group-hover:text-blue-600" />
                                        <span className="text-xs font-medium">{t('project.search.results.relevance')}</span>
                                    </div>
                                </div>
                            </div>

                            <div className={`overflow-y-auto custom-scrollbar pr-2 flex-1 -mr-2 ${isResultsCollapsed ? 'opacity-0' : 'opacity-100'} transition-opacity duration-200`}>
                                <div className={`gap-4 pb-4 ${viewMode === 'grid' ? 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3' : 'flex flex-col'}`}>
                                    {/* Mock Result 1 (Static Example if no results) */}
                                    {results.length === 0 && !loading && (
                                        <>
                                            <div className={`
                                                bg-white dark:bg-[#1e212b] rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 hover:border-blue-600/40 dark:hover:border-blue-600/40 cursor-pointer transition-all group hover:shadow-md hover:shadow-blue-600/5
                                                ${viewMode === 'grid' ? 'p-4 flex flex-col h-full' : 'p-3 flex items-start gap-4'}
                                            `}>
                                                <div className={`flex ${viewMode === 'grid' ? 'items-start justify-between mb-3' : 'shrink-0'}`}>
                                                    <div className="flex items-center gap-2">
                                                        <div className="p-2 rounded-lg bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">
                                                            <FileText className="w-5 h-5" />
                                                        </div>
                                                        {viewMode === 'grid' && (
                                                            <div className="flex flex-col">
                                                                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">Document</span>
                                                                <span className="text-xs font-bold text-emerald-600 dark:text-emerald-400">PDF</span>
                                                            </div>
                                                        )}
                                                    </div>
                                                    {viewMode === 'grid' && (
                                                        <div className="flex flex-col items-end">
                                                            <span className="text-sm font-bold text-blue-600">98%</span>
                                                            <span className="text-[10px] text-slate-400">{t('project.search.results.relevance')}</span>
                                                        </div>
                                                    )}
                                                </div>

                                                <div className="flex-1 min-w-0">
                                                    <div className="flex items-center justify-between gap-2 mb-1">
                                                        <h3 className="text-sm font-semibold text-slate-900 dark:text-white group-hover:text-blue-600 transition-colors line-clamp-1">Architecture Specs v2.pdf</h3>
                                                        {viewMode === 'list' && (
                                                            <div className="flex items-center gap-3 shrink-0">
                                                                <div
                                                                    className="flex items-center gap-1.5 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-[10px] text-slate-500 font-mono cursor-pointer hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                                                                    onClick={(e) => handleCopyId('node-1234-5678', e)}
                                                                    title={t('project.search.results.copy_id')}
                                                                >
                                                                    <span>node-123...</span>
                                                                    {copiedId === 'node-1234-5678' ? (
                                                                        <Check className="w-3 h-3 text-emerald-500" />
                                                                    ) : (
                                                                        <Copy className="w-3 h-3 hover:text-blue-600" />
                                                                    )}
                                                                </div>
                                                                <div className="flex flex-col items-end">
                                                                    <span className="text-sm font-bold text-blue-600 leading-none">98%</span>
                                                                </div>
                                                            </div>
                                                        )}
                                                    </div>

                                                    {/* Node ID for Grid View */}
                                                    {viewMode === 'grid' && (
                                                        <div className="flex items-center gap-1.5 mb-2">
                                                            <span
                                                                className="text-[10px] text-slate-400 font-mono bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded flex items-center gap-1.5 group/id cursor-pointer hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                                                                onClick={(e) => handleCopyId('node-8f7a-2b3c', e)}
                                                                title={t('project.search.results.copy_id')}
                                                            >
                                                                node-8f7a-2b3c
                                                                {copiedId === 'node-8f7a-2b3c' ? (
                                                                    <Check className="w-3 h-3 text-emerald-500" />
                                                                ) : (
                                                                    <Copy className="w-3 h-3 hover:text-blue-600 opacity-0 group-hover/id:opacity-100 transition-opacity" />
                                                                )}
                                                            </span>
                                                        </div>
                                                    )}

                                                    <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed mb-3 line-clamp-2">
                                                        ...final decision regarding the <mark className="bg-yellow-100 dark:bg-yellow-900/30 text-slate-900 dark:text-white px-0.5 rounded">architecture</mark> of Project Alpha was to utilize microservices for better scalability...
                                                    </p>

                                                    <div className={`flex items-center justify-between ${viewMode === 'grid' ? 'mt-auto pt-3 border-t border-slate-50 dark:border-slate-800' : ''}`}>
                                                        <div className="flex gap-2">
                                                            <span className="text-[10px] text-slate-400 font-medium bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">#specs</span>
                                                            <span className="text-[10px] px-1.5 py-0.5 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-300 rounded-full font-medium">Top-1</span>
                                                        </div>
                                                        <span className="text-[10px] text-slate-400 font-medium">Oct 12, 2023</span>
                                                    </div>
                                                </div>
                                            </div>
                                        </>
                                    )}

                                    {/* Dynamic Results */}
                                    {results.map((result, index) => {
                                        const isSelected = result.metadata.uuid && selectedSubgraphIds.includes(result.metadata.uuid)
                                        return (
                                            <div
                                                key={index}
                                                onClick={() => handleResultClick(result)}
                                                className={`
                                            bg-white dark:bg-[#1e212b] rounded-xl shadow-sm border transition-all group hover:shadow-md hover:shadow-blue-600/5 cursor-pointer
                                            ${isSelected
                                                        ? 'border-blue-600 dark:border-blue-500 ring-1 ring-blue-600 dark:ring-blue-500'
                                                        : 'border-slate-200 dark:border-slate-800 hover:border-blue-600/40 dark:hover:border-blue-600/40'
                                                    }
                                            ${viewMode === 'grid' ? 'p-4 flex flex-col h-full' : 'p-3 flex items-start gap-4'}
                                        `}>
                                                <div className={`flex ${viewMode === 'grid' ? 'items-start justify-between mb-3' : 'shrink-0'}`}>
                                                    <div className="flex items-center gap-2">
                                                        <div className="p-2 rounded-lg bg-slate-50 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                                                            {getIconForType(result.metadata.type || 'document')}
                                                        </div>
                                                        {viewMode === 'grid' && (
                                                            <div className="flex flex-col">
                                                                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wide">{result.metadata.type || 'Result'}</span>
                                                                <span className="text-xs font-bold text-slate-600 dark:text-slate-400">{result.source}</span>
                                                            </div>
                                                        )}
                                                    </div>
                                                    {viewMode === 'grid' && (
                                                        <div className="flex flex-col items-end">
                                                            <span className={`text-sm font-bold ${getScoreColor(result.score)}`}>{Math.round(result.score * 100)}%</span>
                                                            <span className="text-[10px] text-slate-400">{t('project.search.results.relevance')}</span>
                                                        </div>
                                                    )}
                                                </div>

                                                <div className="flex-1 min-w-0">
                                                    <div className="flex items-center justify-between gap-2 mb-1">
                                                        <h3 className="text-sm font-semibold text-slate-900 dark:text-white group-hover:text-blue-600 transition-colors line-clamp-1">{result.metadata.name || t('project.search.results.untitled')}</h3>
                                                        {viewMode === 'list' && (
                                                            <div className="flex items-center gap-3 shrink-0">
                                                                {result.metadata.uuid && (
                                                                    <div
                                                                        className="flex items-center gap-1.5 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-[10px] text-slate-500 font-mono hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors group/id"
                                                                        onClick={(e) => handleCopyId(result.metadata.uuid!, e)}
                                                                        title={t('project.search.results.copy_id')}
                                                                    >
                                                                        <span>{result.metadata.uuid.slice(0, 8)}...</span>
                                                                        {copiedId === result.metadata.uuid ? (
                                                                            <Check className="w-3 h-3 text-emerald-500" />
                                                                        ) : (
                                                                            <Copy className="w-3 h-3 hover:text-blue-600" />
                                                                        )}
                                                                    </div>
                                                                )}
                                                                <div className="flex flex-col items-end">
                                                                    <span className={`text-sm font-bold ${getScoreColor(result.score)} leading-none`}>{Math.round(result.score * 100)}%</span>
                                                                </div>
                                                            </div>
                                                        )}
                                                    </div>

                                                    {/* Node ID for Grid View */}
                                                    {viewMode === 'grid' && result.metadata.uuid && (
                                                        <div className="flex items-center gap-1.5 mb-2">
                                                            <span
                                                                className="text-[10px] text-slate-400 font-mono bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded flex items-center gap-1.5 group/id hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                                                                onClick={(e) => handleCopyId(result.metadata.uuid!, e)}
                                                                title={t('project.search.results.copy_id')}
                                                            >
                                                                {result.metadata.uuid.slice(0, 8)}...
                                                                {copiedId === result.metadata.uuid ? (
                                                                    <Check className="w-3 h-3 text-emerald-500" />
                                                                ) : (
                                                                    <Copy className="w-3 h-3 hover:text-blue-600 opacity-0 group-hover/id:opacity-100 transition-opacity" />
                                                                )}
                                                            </span>
                                                        </div>
                                                    )}

                                                    <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed mb-3 line-clamp-2">
                                                        {result.content}
                                                    </p>

                                                    <div className={`flex items-center justify-between ${viewMode === 'grid' ? 'mt-auto pt-3 border-t border-slate-50 dark:border-slate-800' : ''}`}>
                                                        <div className="flex gap-2">
                                                            {result.metadata.tags && Array.isArray(result.metadata.tags) && result.metadata.tags.map((tag: string, i: number) => (
                                                                <span key={i} className="text-[10px] text-slate-400 font-medium bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">#{tag}</span>
                                                            ))}
                                                        </div>
                                                        <span className="text-[10px] text-slate-400 font-medium">{result.metadata.created_at || t('project.search.results.unknown_date')}</span>
                                                    </div>
                                                </div>
                                            </div>
                                        )
                                    })}
                                </div>
                            </div>
                        </section>
                    </div>
                </div>
            </main>
        </div>
    )
}
