import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { schemaAPI } from '../../../services/api';
import {
    Search,
    Filter,
    Download,
    RotateCcw,
    ArrowRight,
    ArrowDown,
    EyeOff,
    AlertTriangle,
    Plus,
    X,
} from 'lucide-react';

export default function EdgeMapList() {
    const { projectId } = useParams<{ projectId: string }>();
    const { t } = useTranslation();
    const [mappings, setMappings] = useState<any[]>([]);
    const [entityTypes, setEntityTypes] = useState<any[]>([]);
    const [edgeTypes, setEdgeTypes] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);

    // UI State
    const [filterSource, setFilterSource] = useState<string>('All');
    const [filterTarget, setFilterTarget] = useState<string>('All');
    const [hideEmpty, setHideEmpty] = useState(false);

    // Add Mapping State
    const [isAddModalOpen, setIsAddModalOpen] = useState(false);
    const [newMapData, setNewMapData] = useState({ source: '', target: '', edge: '' });

    const loadData = useCallback(async () => {
        if (!projectId) return;
        try {
            const [maps, entities, edges] = await Promise.all([
                schemaAPI.listEdgeMaps(projectId),
                schemaAPI.listEntityTypes(projectId),
                schemaAPI.listEdgeTypes(projectId)
            ]);
            setMappings(maps);
            setEntityTypes(entities);
            setEdgeTypes(edges);
        } catch (error) {
            console.error('Failed to load data:', error);
        } finally {
            setLoading(false);
        }
    }, [projectId]);

    useEffect(() => {
        loadData();
    }, [loadData]);

    const handleCreate = async () => {
        if (!projectId) return;
        try {
            await schemaAPI.createEdgeMap(projectId, {
                source_type: newMapData.source,
                target_type: newMapData.target,
                edge_type: newMapData.edge
            });
            setIsAddModalOpen(false);
            setNewMapData({ source: '', target: '', edge: '' });
            loadData();
        } catch (error) {
            console.error('Failed to create mapping:', error);
            alert(t('project.schema.mappings.create_error'));
        }
    };

    const handleDelete = async (id: string) => {
        if (!confirm(t('project.schema.mappings.delete_confirm'))) return;
        if (!projectId) return;
        try {
            await schemaAPI.deleteEdgeMap(projectId, id);
            loadData();
        } catch (error) {
            console.error('Failed to delete:', error);
        }
    };

    const openAddModal = (source: string, target: string) => {
        setNewMapData({ source, target, edge: edgeTypes[0]?.name || '' });
        setIsAddModalOpen(true);
    };

    if (loading) return <div className="p-8 text-center text-slate-500 dark:text-gray-500">{t('common.loading')}</div>;

    // Combine system types and user types
    const systemTypes = ["Entity"]; // Base type
    const allEntityNames = Array.from(new Set([...systemTypes, ...entityTypes.map(e => e.name)]));

    // Filter rows and columns
    const filteredRows = filterSource === 'All' ? allEntityNames : [filterSource];
    const filteredCols = filterTarget === 'All' ? allEntityNames : [filterTarget];

    return (
        <div className="flex flex-col h-full bg-slate-50 dark:bg-[#111521] text-slate-900 dark:text-white overflow-hidden">
            {/* Header */}
            <div className="w-full flex-none pt-6 pb-4 px-8 border-b border-slate-200 dark:border-[#2a324a]/50 bg-white dark:bg-[#121521]">
                <div className="max-w-[1600px] mx-auto flex flex-col gap-4">
                    <div className="flex flex-wrap justify-between items-end gap-4">
                        <div className="flex flex-col gap-2 max-w-3xl">
                            <h1 className="text-slate-900 dark:text-white text-3xl font-black leading-tight tracking-tight">{t('project.schema.mappings.title')}</h1>
                            <p className="text-slate-500 dark:text-[#95a0c6] text-base font-normal">
                                {t('project.schema.mappings.subtitle')}
                            </p>
                        </div>
                        <div className="flex gap-3">
                            <button className="flex items-center justify-center rounded-lg h-10 px-4 bg-slate-100 dark:bg-[#1e2433] border border-slate-200 dark:border-[#2a324a] text-slate-700 dark:text-white text-sm font-bold hover:bg-slate-200 dark:hover:bg-[#252d46] transition-colors">
                                {t('project.schema.mappings.cancel')}
                            </button>
                            <button className="flex items-center justify-center rounded-lg h-10 px-6 bg-blue-600 dark:bg-[#193db3] text-white text-sm font-bold shadow-lg shadow-blue-900/20 hover:bg-blue-700 transition-colors">
                                {t('project.schema.mappings.save')}
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-8 bg-slate-50 dark:bg-[#111521]">
                <div className="max-w-[1600px] mx-auto flex flex-col gap-6">

                    {/* Toolbar */}
                    <div className="flex flex-col gap-4">
                        <div className="flex flex-wrap justify-between gap-4">
                            <div className="flex items-center gap-2 bg-white dark:bg-[#1e2433]/50 p-1 rounded-lg border border-slate-200 dark:border-[#2a324a]">
                                <div className="relative group">
                                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                                        <Search className="text-slate-400 dark:text-[#95a0c6] w-5 h-5" />
                                    </div>
                                    <input
                                        className="block w-64 bg-transparent border-none rounded-md py-2 pl-10 pr-3 text-sm text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-[#95a0c6] focus:ring-1 focus:ring-blue-600 dark:focus:ring-[#193db3] outline-none"
                                        placeholder={t('project.schema.mappings.search_placeholder')}
                                        type="text"
                                    />
                                </div>
                                <div className="h-6 w-px bg-slate-200 dark:bg-[#2a324a] mx-1"></div>
                                <button className="p-2 text-slate-400 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white rounded hover:bg-slate-100 dark:hover:bg-[#2a324a] transition-colors" title="Filter">
                                    <Filter className="w-5 h-5" />
                                </button>
                                <button className="p-2 text-slate-400 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white rounded hover:bg-slate-100 dark:hover:bg-[#2a324a] transition-colors" title="Export Schema">
                                    <Download className="w-5 h-5" />
                                </button>
                            </div>
                            <button
                                onClick={() => { setFilterSource('All'); setFilterTarget('All'); setHideEmpty(false); }}
                                className="flex items-center gap-2 px-4 py-2 rounded-lg text-slate-500 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white hover:bg-slate-200 dark:hover:bg-[#1e2433] transition-colors text-sm font-bold"
                            >
                                <RotateCcw className="w-5 h-5" />
                                <span>{t('project.schema.mappings.reset_defaults')}</span>
                            </button>
                        </div>

                        {/* Filter Cards */}
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            {/* Source Filter */}
                            <div className="flex flex-col gap-2 rounded-lg border border-slate-200 dark:border-[#2a324a] bg-white dark:bg-[#1e2433] p-4 hover:border-blue-400 dark:hover:border-[#193db3]/50 transition-colors group">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2 text-slate-900 dark:text-white">
                                        <ArrowRight className="text-blue-600 dark:text-[#193db3] group-hover:translate-x-1 transition-transform w-5 h-5" />
                                        <h2 className="text-sm font-bold">{t('project.schema.mappings.filter_source.title')}</h2>
                                    </div>
                                    <select
                                        value={filterSource}
                                        onChange={(e) => setFilterSource(e.target.value)}
                                        className="bg-blue-50 dark:bg-[#193db3]/20 text-blue-600 dark:text-[#193db3] text-xs px-2 py-0.5 rounded font-medium border-none outline-none cursor-pointer"
                                    >
                                        <option value="All">All</option>
                                        {allEntityNames.map(name => <option key={name} value={name}>{name}</option>)}
                                    </select>
                                </div>
                                <p className="text-slate-500 dark:text-[#95a0c6] text-xs">{t('project.schema.mappings.filter_source.desc')}</p>
                            </div>

                            {/* Target Filter */}
                            <div className="flex flex-col gap-2 rounded-lg border border-slate-200 dark:border-[#2a324a] bg-white dark:bg-[#1e2433] p-4 hover:border-blue-400 dark:hover:border-[#193db3]/50 transition-colors group">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2 text-slate-900 dark:text-white">
                                        <ArrowDown className="text-blue-600 dark:text-[#193db3] group-hover:translate-y-1 transition-transform w-5 h-5" />
                                        <h2 className="text-sm font-bold">{t('project.schema.mappings.filter_target.title')}</h2>
                                    </div>
                                    <select
                                        value={filterTarget}
                                        onChange={(e) => setFilterTarget(e.target.value)}
                                        className="bg-blue-50 dark:bg-[#193db3]/20 text-blue-600 dark:text-[#193db3] text-xs px-2 py-0.5 rounded font-medium border-none outline-none cursor-pointer"
                                    >
                                        <option value="All">All</option>
                                        {allEntityNames.map(name => <option key={name} value={name}>{name}</option>)}
                                    </select>
                                </div>
                                <p className="text-slate-500 dark:text-[#95a0c6] text-xs">{t('project.schema.mappings.filter_target.desc')}</p>
                            </div>

                            {/* View Options */}
                            <div
                                onClick={() => setHideEmpty(!hideEmpty)}
                                className="flex flex-col gap-2 rounded-lg border border-slate-200 dark:border-[#2a324a] bg-white dark:bg-[#1e2433] p-4 hover:border-blue-400 dark:hover:border-[#193db3]/50 transition-colors cursor-pointer"
                            >
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2 text-slate-900 dark:text-white">
                                        <EyeOff className="text-slate-400 dark:text-[#95a0c6] w-5 h-5" />
                                        <h2 className="text-sm font-bold">{t('project.schema.mappings.empty_cells.title')}</h2>
                                    </div>
                                    <div className={`w-8 h-4 ${hideEmpty ? 'bg-blue-600 dark:bg-[#193db3]' : 'bg-slate-200 dark:bg-[#2a324a]'} rounded-full relative transition-colors`}>
                                        <div className={`absolute top-1 bg-white size-2 rounded-full transition-all ${hideEmpty ? 'left-5' : 'left-1'}`}></div>
                                    </div>
                                </div>
                                <p className="text-slate-500 dark:text-[#95a0c6] text-xs">{t('project.schema.mappings.empty_cells.desc')}</p>
                            </div>
                        </div>
                    </div>

                    {/* Matrix Table */}
                    <div className="flex flex-col flex-1 min-h-[500px] border border-slate-200 dark:border-[#2a324a] rounded-xl bg-white dark:bg-[#121521] shadow-2xl overflow-hidden relative">
                        {/* Legend */}
                        <div className="bg-slate-50 dark:bg-[#1e2433] px-4 py-2 border-b border-slate-200 dark:border-[#2a324a] flex items-center justify-between text-xs text-slate-500 dark:text-[#95a0c6]">
                            <div className="flex gap-4">
                                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-600 dark:bg-[#193db3]"></span> {t('project.schema.mappings.legend.manual')}</span>
                                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-purple-600 dark:bg-purple-500"></span> {t('project.schema.mappings.legend.auto')}</span>
                                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-slate-200 dark:bg-[#2a324a]"></span> {t('project.schema.mappings.legend.empty')}</span>
                                <span className="flex items-center gap-1"><AlertTriangle className="w-3.5 h-3.5 text-amber-500" /> {t('project.schema.mappings.legend.conflict')}</span>
                            </div>
                            <span>{t('project.schema.mappings.legend.showing', { rows: filteredRows.length, cols: filteredCols.length })}</span>
                        </div>

                        {/* Table */}
                        <div className="overflow-auto w-full h-full bg-white dark:bg-[#121521]">
                            <table className="w-full text-left border-collapse whitespace-nowrap">
                                <thead>
                                    <tr>
                                        {/* Sticky Corner */}
                                        <th className="sticky left-0 top-0 z-50 bg-slate-50 dark:bg-[#1e2433] p-4 border-b border-r border-slate-200 dark:border-[#2a324a] min-w-[200px] shadow-md">
                                            <div className="flex flex-col gap-1">
                                                <div className="flex items-center justify-between">
                                                    <span className="text-slate-500 dark:text-[#95a0c6] text-xs font-normal">Source \ Target</span>
                                                </div>
                                            </div>
                                        </th>
                                        {/* Column Headers */}
                                        {filteredCols.map(col => (
                                            <th key={col} className="sticky top-0 z-40 bg-slate-50 dark:bg-[#1e2433] p-3 border-b border-slate-200 dark:border-[#2a324a] min-w-[240px] text-slate-900 dark:text-white font-semibold text-sm">
                                                <div className="flex items-center gap-2">
                                                    <div className="size-6 rounded bg-purple-100 dark:bg-purple-500/20 text-purple-600 dark:text-purple-400 flex items-center justify-center">
                                                        <span className="text-xs font-bold">{col.charAt(0)}</span>
                                                    </div>
                                                    {col}
                                                </div>
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-slate-200 dark:divide-[#2a324a]">
                                    {filteredRows.map(row => (
                                        <tr key={row} className="group">
                                            {/* Row Header */}
                                            <td className="sticky left-0 z-30 bg-slate-50 dark:bg-[#1e2433] p-3 border-r border-slate-200 dark:border-[#2a324a] font-medium text-slate-900 dark:text-white shadow-md group-hover:bg-slate-100 dark:group-hover:bg-[#252d46] transition-colors">
                                                <div className="flex items-center gap-2">
                                                    <div className="size-6 rounded bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 flex items-center justify-center">
                                                        <span className="text-xs font-bold">{row.charAt(0)}</span>
                                                    </div>
                                                    {row}
                                                </div>
                                            </td>
                                            {/* Cells */}
                                            {filteredCols.map(col => {
                                                const cellMappings = mappings.filter(m => m.source_type === row && m.target_type === col);

                                                if (hideEmpty && cellMappings.length === 0) return null;

                                                return (
                                                    <td key={`${row}-${col}`} className="p-3 bg-white dark:bg-[#121521] hover:bg-slate-50 dark:hover:bg-[#1e2433] border-r border-slate-200/50 dark:border-[#2a324a]/30 transition-colors align-top min-h-[80px]">
                                                        <div className="flex flex-wrap gap-2">
                                                            {cellMappings.map(map => (
                                                                <span 
                                                                    key={map.id} 
                                                                    className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium border cursor-pointer group/chip ${
                                                                        map.source === 'generated'
                                                                            ? 'bg-purple-50 dark:bg-purple-500/20 text-purple-700 dark:text-purple-200 border-purple-200 dark:border-purple-500/30 hover:bg-purple-100 dark:hover:bg-purple-500/30'
                                                                            : 'bg-blue-50 dark:bg-[#193db3]/20 text-blue-700 dark:text-blue-200 border-blue-200 dark:border-[#193db3]/30 hover:bg-blue-100 dark:hover:bg-[#193db3]/30'
                                                                    }`}
                                                                >
                                                                    {map.edge_type}
                                                                    <X
                                                                        onClick={(e) => { e.stopPropagation(); handleDelete(map.id); }}
                                                                        className="w-3 h-3 opacity-0 group-hover/chip:opacity-100 hover:text-red-600 dark:hover:text-white"
                                                                    />
                                                                </span>
                                                            ))}
                                                            <button
                                                                onClick={() => openAddModal(row, col)}
                                                                className="text-slate-400 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white rounded-full size-6 flex items-center justify-center hover:bg-slate-100 dark:hover:bg-white/10"
                                                            >
                                                                <Plus className="w-4 h-4" />
                                                            </button>
                                                        </div>
                                                    </td>
                                                );
                                            })}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </div>

            {/* Add Mapping Modal */}
            {isAddModalOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setIsAddModalOpen(false)}>
                    <div className="bg-white dark:bg-[#1e2433] rounded-lg shadow-xl border border-slate-200 dark:border-[#2a324a] w-full max-w-md p-6" onClick={e => e.stopPropagation()}>
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="text-lg font-bold text-slate-900 dark:text-white">{t('project.schema.mappings.modal.title')}</h3>
                            <button onClick={() => setIsAddModalOpen(false)} className="text-slate-400 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white">
                                <X className="w-5 h-5" />
                            </button>
                        </div>
                        <div className="flex flex-col gap-4">
                            <div className="flex items-center justify-between bg-slate-100 dark:bg-[#121521] p-3 rounded-lg border border-slate-200 dark:border-[#2a324a]">
                                <span className="font-bold text-slate-900 dark:text-white">{newMapData.source}</span>
                                <ArrowRight className="text-slate-400 dark:text-[#95a0c6] w-4 h-4" />
                                <span className="font-bold text-slate-900 dark:text-white">{newMapData.target}</span>
                            </div>

                            <div>
                                <label className="block text-xs font-bold text-slate-500 dark:text-[#95a0c6] uppercase mb-2">{t('project.schema.mappings.modal.select_edge')}</label>
                                <select
                                    className="w-full bg-slate-50 dark:bg-[#121521] border border-slate-200 dark:border-[#2a324a] rounded-lg text-sm text-slate-900 dark:text-white px-3 py-2 outline-none focus:border-blue-600 dark:focus:border-[#193db3]"
                                    value={newMapData.edge}
                                    onChange={(e) => setNewMapData({ ...newMapData, edge: e.target.value })}
                                >
                                    {edgeTypes.map(edge => (
                                        <option key={edge.id} value={edge.name}>{edge.name}</option>
                                    ))}
                                </select>
                            </div>

                            <div className="flex justify-end gap-3 mt-2">
                                <button
                                    onClick={() => setIsAddModalOpen(false)}
                                    className="px-4 py-2 text-sm font-medium text-slate-500 dark:text-[#95a0c6] hover:text-slate-900 dark:hover:text-white border border-slate-200 dark:border-[#2a324a] rounded-lg hover:bg-slate-100 dark:hover:bg-[#2a324a] transition-colors"
                                >
                                    {t('project.schema.mappings.modal.cancel')}
                                </button>
                                <button
                                    onClick={handleCreate}
                                    className="px-4 py-2 text-sm font-bold text-white bg-blue-600 dark:bg-[#193db3] rounded-lg hover:bg-blue-700 dark:hover:bg-[#254bcc] shadow-lg shadow-blue-900/20"
                                >
                                    {t('project.schema.mappings.modal.add')}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
