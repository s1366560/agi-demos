import { useState, useEffect, useCallback } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { message } from 'antd';
import {
  Search,
  Download,
  RotateCcw,
  ArrowRight,
  ArrowDown,
  EyeOff,
  AlertTriangle,
  Plus,
  X,
  Loader2,
} from 'lucide-react';

import { AppModal } from '@/components/common';

import { schemaAPI } from '../../../services/api';
import { confirmAction } from '../../../utils/confirmAction';
import { logger } from '../../../utils/logger';

import type { EdgeMapping, SchemaEdgeType, SchemaEntityType } from '../../../types/memory';

export default function EdgeMapList() {
  const { projectId } = useParams<{ projectId: string }>();
  const { t } = useTranslation();
  const [mappings, setMappings] = useState<EdgeMapping[]>([]);
  const [entityTypes, setEntityTypes] = useState<SchemaEntityType[]>([]);
  const [edgeTypes, setEdgeTypes] = useState<SchemaEdgeType[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // UI State
  const [filterSource, setFilterSource] = useState<string>('All');
  const [filterTarget, setFilterTarget] = useState<string>('All');
  const [hideEmpty, setHideEmpty] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  // Add Mapping State
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newMapData, setNewMapData] = useState({ source: '', target: '', edge: '' });
  const [isCreating, setIsCreating] = useState(false);

  const loadData = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setLoadError(null);
    try {
      const [maps, entities, edges] = await Promise.all([
        schemaAPI.listEdgeMaps(projectId),
        schemaAPI.listEntityTypes(projectId),
        schemaAPI.listEdgeTypes(projectId),
      ]);
      setMappings(maps);
      setEntityTypes(entities);
      setEdgeTypes(edges);
    } catch (error) {
      logger.error('[EdgeMapList] Failed to load data:', error);
      setLoadError(t('project.schema.mappings.load_error', 'Failed to load schema mappings.'));
    } finally {
      setLoading(false);
    }
  }, [projectId, t]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const handleCreate = async () => {
    if (!projectId || isCreating) return;
    if (!newMapData.edge) {
      void message.error(t('project.schema.mappings.no_edge_types', 'Create an edge type first.'));
      return;
    }
    setIsCreating(true);
    try {
      await schemaAPI.createEdgeMap(projectId, {
        source_type: newMapData.source,
        target_type: newMapData.target,
        edge_type: newMapData.edge,
      });
      setIsAddModalOpen(false);
      setNewMapData({ source: '', target: '', edge: '' });
      void message.success(t('project.schema.mappings.create_success', 'Mapping created'));
      await loadData();
    } catch (error) {
      logger.error('[EdgeMapList] Failed to create mapping:', error);
      void message.error(t('project.schema.mappings.create_error'));
    } finally {
      setIsCreating(false);
    }
  };

  const handleExport = () => {
    const blob = new Blob(
      [
        JSON.stringify(
          {
            project_id: projectId,
            mappings,
            exported_at: new Date().toISOString(),
          },
          null,
          2
        ),
      ],
      { type: 'application/json;charset=utf-8' }
    );
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `edge-mappings-${projectId ?? 'project'}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const handleDelete = async (id: string) => {
    if (
      !(await confirmAction({ title: t('project.schema.mappings.delete_confirm'), danger: true }))
    )
      return;
    if (!projectId) return;
    try {
      await schemaAPI.deleteEdgeMap(projectId, id);
      await loadData();
    } catch (error) {
      logger.error('[EdgeMapList] Failed to delete:', error);
      void message.error(t('project.schema.mappings.delete_error', 'Failed to delete mapping'));
    }
  };

  const openAddModal = (source: string, target: string) => {
    if (edgeTypes.length === 0) return;
    setNewMapData({ source, target, edge: edgeTypes[0]?.name ?? '' });
    setIsAddModalOpen(true);
  };

  if (loading)
    return (
      <div className="p-8 text-center text-slate-500 dark:text-gray-500" role="status">
        {t('common.loading')}
      </div>
    );

  if (loadError)
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div
          role="alert"
          className="flex flex-col items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-center dark:border-red-500/30 dark:bg-red-500/10"
        >
          <p className="text-sm text-red-600 dark:text-red-400">{loadError}</p>
          <button
            type="button"
            onClick={() => {
              void loadData();
            }}
            className="inline-flex h-9 items-center rounded-lg bg-slate-950 px-4 text-sm font-medium text-slate-50 transition-colors hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950/20 dark:bg-slate-50 dark:text-slate-950 dark:hover:bg-slate-200 dark:focus-visible:ring-slate-50/20"
          >
            {t('common.retry', 'Retry')}
          </button>
        </div>
      </div>
    );

  // Combine system types and user types
  const systemTypes = ['Entity']; // Base type
  const allEntityNames = Array.from(new Set([...systemTypes, ...entityTypes.map((e) => e.name)]));
  const searchedEntityNames = searchQuery.trim()
    ? allEntityNames.filter((name) => name.toLowerCase().includes(searchQuery.trim().toLowerCase()))
    : allEntityNames;

  // Filter rows and columns
  const filteredRows =
    filterSource === 'All'
      ? searchedEntityNames
      : searchedEntityNames.includes(filterSource)
        ? [filterSource]
        : [];
  const filteredCols =
    filterTarget === 'All'
      ? searchedEntityNames
      : searchedEntityNames.includes(filterTarget)
        ? [filterTarget]
        : [];

  const handleResetDefaults = () => {
    setFilterSource('All');
    setFilterTarget('All');
    setHideEmpty(false);
    setSearchQuery('');
  };

  const openDefaultAddModal = () => {
    const entityName = allEntityNames[0] ?? '';
    if (!entityName || edgeTypes.length === 0) return;
    openAddModal(entityName, entityName);
  };

  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-background-dark text-slate-900 dark:text-slate-100 overflow-hidden">
      {/* Header */}
      <div className="w-full flex-none border-b border-slate-200 bg-slate-50 px-4 pb-4 pt-6 dark:border-border-dark/50 dark:bg-background-dark sm:px-6 lg:px-8">
        <div className="max-w-[1600px] mx-auto flex flex-col gap-4">
          <div className="flex flex-wrap justify-between items-end gap-4">
            <div className="flex flex-col gap-2 max-w-3xl">
              <h1 className="text-slate-900 dark:text-slate-100 text-3xl font-black leading-tight tracking-tight">
                {t('project.schema.mappings.title')}
              </h1>
              <p className="text-slate-500 dark:text-text-muted text-base font-normal">
                {t('project.schema.mappings.subtitle')}
              </p>
            </div>
            <div className="flex flex-wrap gap-2 sm:gap-3">
              <button
                type="button"
                onClick={() => {
                  void loadData();
                }}
                className="flex h-10 items-center justify-center rounded-lg border border-slate-200 bg-slate-100 px-4 text-sm font-bold text-slate-700 transition-colors hover:bg-slate-200 dark:border-border-dark dark:bg-surface-dark dark:text-slate-100 dark:hover:bg-surface-dark-alt"
              >
                {t('project.schema.mappings.refresh', 'Refresh')}
              </button>
              <button
                type="button"
                disabled={edgeTypes.length === 0}
                onClick={openDefaultAddModal}
                className="flex h-10 items-center justify-center rounded-lg bg-blue-600 px-6 text-sm font-bold text-slate-50 shadow-sm transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-primary"
              >
                {t('project.schema.mappings.add_mapping_button', 'Add Mapping')}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto bg-slate-50 p-4 dark:bg-background-dark sm:p-6 lg:p-8">
        <div className="max-w-[1600px] mx-auto flex flex-col gap-6">
          {/* Toolbar */}
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap justify-between gap-4">
              <div className="flex w-full min-w-0 flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-1 dark:border-border-dark dark:bg-surface-dark/50 sm:w-auto">
                <div className="group relative min-w-0 flex-1 sm:flex-none">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Search className="text-slate-400 dark:text-text-muted w-5 h-5" />
                  </div>
                  <input
                    aria-label={t('project.schema.mappings.search_placeholder')}
                    value={searchQuery}
                    onChange={(event) => {
                      setSearchQuery(event.target.value);
                    }}
                    className="block w-full rounded-md border-none bg-transparent py-2 pl-10 pr-3 text-sm text-slate-900 outline-none placeholder-slate-400 focus:ring-1 focus:ring-blue-600 dark:text-slate-100 dark:placeholder-text-muted dark:focus:ring-primary sm:w-64"
                    placeholder={t('project.schema.mappings.search_placeholder')}
                    type="text"
                  />
                </div>
                <div className="hidden h-6 w-px bg-slate-200 dark:bg-border-dark sm:block"></div>
                <button
                  type="button"
                  onClick={handleExport}
                  aria-label={t('project.schema.overview.export_schema')}
                  className="p-2 text-slate-400 dark:text-text-muted hover:text-slate-900 dark:hover:text-slate-100 rounded hover:bg-slate-100 dark:hover:bg-border-dark transition-colors"
                  title={t('project.schema.overview.export_schema')}
                >
                  <Download className="w-5 h-5" />
                </button>
              </div>
              <button
                type="button"
                onClick={handleResetDefaults}
                className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-bold text-slate-500 transition-colors hover:bg-slate-200 hover:text-slate-900 dark:text-text-muted dark:hover:bg-surface-dark dark:hover:text-slate-100"
              >
                <RotateCcw className="w-5 h-5" />
                <span>{t('project.schema.mappings.reset_defaults')}</span>
              </button>
            </div>

            {/* Filter Cards */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Source Filter */}
              <div className="flex flex-col gap-2 rounded-lg border border-slate-200 dark:border-border-dark bg-slate-50 dark:bg-surface-dark p-4 hover:border-blue-400 dark:hover:border-primary/50 transition-colors group">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
                    <ArrowRight className="text-blue-600 dark:text-primary group-hover:translate-x-1 transition-transform w-5 h-5" />
                    <h2 className="text-sm font-bold">
                      {t('project.schema.mappings.filter_source.title')}
                    </h2>
                  </div>
                  <select
                    aria-label={t('project.schema.mappings.filter_source.title')}
                    value={filterSource}
                    onChange={(e) => {
                      setFilterSource(e.target.value);
                    }}
                    className="bg-blue-50 dark:bg-primary/20 text-blue-600 dark:text-primary text-xs px-2 py-0.5 rounded font-medium border-none outline-none focus-visible:ring-1 focus-visible:ring-primary cursor-pointer"
                  >
                    <option value="All">{t('project.schema.mappings.all', 'All')}</option>
                    {allEntityNames.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </div>
                <p className="text-slate-500 dark:text-text-muted text-xs">
                  {t('project.schema.mappings.filter_source.desc')}
                </p>
              </div>

              {/* Target Filter */}
              <div className="flex flex-col gap-2 rounded-lg border border-slate-200 dark:border-border-dark bg-slate-50 dark:bg-surface-dark p-4 hover:border-blue-400 dark:hover:border-primary/50 transition-colors group">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
                    <ArrowDown className="text-blue-600 dark:text-primary group-hover:translate-y-1 transition-transform w-5 h-5" />
                    <h2 className="text-sm font-bold">
                      {t('project.schema.mappings.filter_target.title')}
                    </h2>
                  </div>
                  <select
                    aria-label={t('project.schema.mappings.filter_target.title')}
                    value={filterTarget}
                    onChange={(e) => {
                      setFilterTarget(e.target.value);
                    }}
                    className="bg-blue-50 dark:bg-primary/20 text-blue-600 dark:text-primary text-xs px-2 py-0.5 rounded font-medium border-none outline-none focus-visible:ring-1 focus-visible:ring-primary cursor-pointer"
                  >
                    <option value="All">{t('project.schema.mappings.all', 'All')}</option>
                    {allEntityNames.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </div>
                <p className="text-slate-500 dark:text-text-muted text-xs">
                  {t('project.schema.mappings.filter_target.desc')}
                </p>
              </div>

              {/* View Options */}
              <button
                type="button"
                onClick={() => {
                  setHideEmpty(!hideEmpty);
                }}
                aria-pressed={hideEmpty}
                className="flex flex-col gap-2 rounded-lg border border-slate-200 bg-slate-50 p-4 text-left transition-colors hover:border-blue-400 dark:border-border-dark dark:bg-surface-dark dark:hover:border-primary/50"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
                    <EyeOff className="text-slate-400 dark:text-text-muted w-5 h-5" />
                    <h2 className="text-sm font-bold">
                      {t('project.schema.mappings.empty_cells.title')}
                    </h2>
                  </div>
                  <div
                    className={`w-8 h-4 ${hideEmpty ? 'bg-blue-600 dark:bg-primary' : 'bg-slate-200 dark:bg-border-dark'} rounded-full relative transition-colors`}
                  >
                    <div
                      className={`absolute top-1 bg-slate-50 size-2 rounded-full transition-[left] ${hideEmpty ? 'left-5' : 'left-1'}`}
                    ></div>
                  </div>
                </div>
                <p className="text-slate-500 dark:text-text-muted text-xs">
                  {t('project.schema.mappings.empty_cells.desc')}
                </p>
              </button>
            </div>
          </div>

          {/* Matrix Table */}
          <div className="flex flex-col flex-1 min-h-[500px] border border-slate-200 dark:border-border-dark rounded-lg bg-slate-50 dark:bg-background-dark shadow-sm overflow-hidden relative">
            {/* Legend */}
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-500 dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
              <div className="flex flex-wrap gap-x-4 gap-y-2">
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-blue-600 dark:bg-primary"></span>{' '}
                  {t('project.schema.mappings.legend.manual')}
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-purple-600 dark:bg-purple-500"></span>{' '}
                  {t('project.schema.mappings.legend.auto')}
                </span>
                <span className="flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-slate-200 dark:bg-border-dark"></span>{' '}
                  {t('project.schema.mappings.legend.empty')}
                </span>
                <span className="flex items-center gap-1">
                  <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />{' '}
                  {t('project.schema.mappings.legend.conflict')}
                </span>
              </div>
              <span>
                {t('project.schema.mappings.legend.showing', {
                  rows: filteredRows.length,
                  cols: filteredCols.length,
                })}
              </span>
            </div>

            {/* Table */}
            <div className="overflow-auto w-full h-full bg-slate-50 dark:bg-background-dark">
              <table className="w-full text-left border-collapse whitespace-nowrap">
                <thead>
                  <tr>
                    {/* Sticky Corner */}
                    <th className="sticky left-0 top-0 z-50 bg-slate-50 dark:bg-surface-dark p-4 border-b border-r border-slate-200 dark:border-border-dark min-w-50 shadow-md">
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center justify-between">
                          <span className="text-slate-500 dark:text-text-muted text-xs font-normal">
                            {t('project.schema.mappings.source_target', 'Source \\ Target')}
                          </span>
                        </div>
                      </div>
                    </th>
                    {/* Column Headers */}
                    {filteredCols.map((col) => (
                      <th
                        key={col}
                        className="sticky top-0 z-40 bg-slate-50 dark:bg-surface-dark p-3 border-b border-slate-200 dark:border-border-dark min-w-[240px] text-slate-900 dark:text-slate-100 font-semibold text-sm"
                      >
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
                <tbody className="divide-y divide-slate-200 dark:divide-border-dark">
                  {filteredRows.map((row) => (
                    <tr key={row} className="group">
                      {/* Row Header */}
                      <th
                        scope="row"
                        className="sticky left-0 z-30 bg-slate-50 dark:bg-surface-dark p-3 border-r border-slate-200 dark:border-border-dark text-left font-medium text-slate-900 dark:text-slate-100 shadow-sm group-hover:bg-slate-100 dark:group-hover:bg-surface-dark-alt transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <div className="size-6 rounded bg-blue-100 dark:bg-blue-500/20 text-blue-600 dark:text-blue-400 flex items-center justify-center">
                            <span className="text-xs font-bold">{row.charAt(0)}</span>
                          </div>
                          {row}
                        </div>
                      </th>
                      {/* Cells */}
                      {filteredCols.map((col) => {
                        const cellMappings = mappings.filter(
                          (m) => m.source_type === row && m.target_type === col
                        );

                        if (hideEmpty && cellMappings.length === 0) {
                          // Keep the grid aligned: render a placeholder cell instead of
                          // skipping the <td> entirely.
                          return (
                            <td
                              key={`${row}-${col}`}
                              aria-hidden="true"
                              className="p-3 bg-slate-100/60 dark:bg-slate-900/40 border-r border-slate-200/50 dark:border-border-dark/30"
                            />
                          );
                        }

                        return (
                          <td
                            key={`${row}-${col}`}
                            className="p-3 bg-slate-50 dark:bg-background-dark hover:bg-slate-100 dark:hover:bg-surface-dark border-r border-slate-200/50 dark:border-border-dark/30 transition-colors align-top min-h-[80px]"
                          >
                            <div className="flex flex-wrap gap-2">
                              {cellMappings.map((map) => (
                                <span
                                  key={map.id}
                                  className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium border group/chip ${
                                    map.source === 'generated'
                                      ? 'bg-purple-50 dark:bg-purple-500/20 text-purple-700 dark:text-purple-200 border-purple-200 dark:border-purple-500/30 hover:bg-purple-100 dark:hover:bg-purple-500/30'
                                      : 'bg-blue-50 dark:bg-primary/20 text-blue-700 dark:text-blue-200 border-blue-200 dark:border-primary/30 hover:bg-blue-100 dark:hover:bg-primary/30'
                                  }`}
                                >
                                  {map.edge_type}
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      void handleDelete(map.id);
                                    }}
                                    aria-label={t('project.schema.mappings.remove_mapping', {
                                      edge: map.edge_type,
                                    })}
                                    className="rounded text-current opacity-0 transition-opacity hover:text-red-600 focus-visible:opacity-100 group-hover/chip:opacity-100 dark:hover:text-slate-100"
                                  >
                                    <X className="h-3 w-3" />
                                  </button>
                                </span>
                              ))}
                              <button
                                type="button"
                                disabled={edgeTypes.length === 0}
                                onClick={() => {
                                  openAddModal(row, col);
                                }}
                                aria-label={t('project.schema.mappings.add_mapping', {
                                  source: row,
                                  target: col,
                                })}
                                className="text-slate-400 dark:text-text-muted hover:text-slate-900 dark:hover:text-slate-100 rounded-full size-6 flex items-center justify-center hover:bg-slate-100 dark:hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
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
      <AppModal
        open={isAddModalOpen}
        onClose={() => {
          setIsAddModalOpen(false);
        }}
        title={t('project.schema.mappings.modal.title')}
        size="sm"
        footer={
          <>
            <button
              type="button"
              onClick={() => {
                setIsAddModalOpen(false);
              }}
              className="px-4 py-2 text-sm font-medium text-slate-500 dark:text-text-muted hover:text-slate-900 dark:hover:text-slate-100 border border-slate-200 dark:border-border-dark rounded-lg hover:bg-slate-100 dark:hover:bg-border-dark transition-colors"
            >
              {t('project.schema.mappings.modal.cancel')}
            </button>
            <button
              type="button"
              disabled={isCreating || !newMapData.edge}
              onClick={() => {
                void handleCreate();
              }}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm font-bold text-slate-50 bg-blue-600 dark:bg-primary rounded-lg hover:bg-blue-700 dark:hover:bg-primary-light shadow-sm disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isCreating && (
                <Loader2
                  className="w-4 h-4 animate-spin motion-reduce:animate-none"
                  aria-hidden="true"
                />
              )}
              {isCreating
                ? t('project.schema.mappings.modal.adding', 'Adding…')
                : t('project.schema.mappings.modal.add')}
            </button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between bg-slate-100 dark:bg-background-dark p-3 rounded-lg border border-slate-200 dark:border-border-dark">
            <span className="font-bold text-slate-900 dark:text-slate-100">
              {newMapData.source}
            </span>
            <ArrowRight className="text-slate-400 dark:text-text-muted w-4 h-4" />
            <span className="font-bold text-slate-900 dark:text-slate-100">
              {newMapData.target}
            </span>
          </div>

          <div>
            <label className="block text-xs font-bold text-slate-500 dark:text-text-muted uppercase mb-2">
              {t('project.schema.mappings.modal.select_edge')}
            </label>
            <select
              aria-label={t('project.schema.mappings.modal.select_edge')}
              className="w-full bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-border-dark rounded-lg text-sm text-slate-900 dark:text-slate-100 px-3 py-2 outline-none focus:border-blue-600 dark:focus:border-primary"
              value={newMapData.edge}
              onChange={(e) => {
                setNewMapData({ ...newMapData, edge: e.target.value });
              }}
            >
              {edgeTypes.map((edge) => (
                <option key={edge.id} value={edge.name}>
                  {edge.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </AppModal>
    </div>
  );
}
