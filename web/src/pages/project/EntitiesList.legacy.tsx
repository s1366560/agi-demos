import React, { useState, useEffect, useCallback, memo } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import { useDebounce } from 'use-debounce';

import { VirtualGrid } from '../../components/common';
import { EntityCard, getEntityTypeColor } from '../../components/graph';
import { graphService } from '../../services/graphService';

interface Entity {
  uuid: string;
  name: string;
  entity_type: string;
  summary: string;
  created_at?: string;
}

interface EntityType {
  entity_type: string;
  count: number;
}

interface Relationship {
  edge_id: string;
  relation_type: string;
  direction: string;
  fact: string;
  score: number;
  created_at?: string;
  related_entity: {
    uuid: string;
    name: string;
    entity_type: string;
    summary: string;
  };
}

const EntitiesListInternal: React.FC = () => {
  const { t } = useTranslation();
  const { projectId } = useParams();
  const [entities, setEntities] = useState<Entity[]>([]);
  const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [entityTypes, setEntityTypes] = useState<EntityType[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingTypes, setLoadingTypes] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const limit = 20;

  // Filters
  const [entityTypeFilter, setEntityTypeFilter] = useState<string>('');
  const [searchInput, setSearchInput] = useState<string>(''); // Input state (immediate)
  const [sortBy, setSortBy] = useState<'name' | 'created_at'>('created_at');

  // Debounced search value for filtering (300ms delay)
  const [searchQuery] = useDebounce(searchInput, 300);

  // Load entity types
  const loadEntityTypes = useCallback(async () => {
    setLoadingTypes(true);
    try {
      const result = await graphService.getEntityTypes({ project_id: projectId });
      setEntityTypes(result.entity_types);
    } catch (err) {
      console.error('Failed to load entity types:', err);
    } finally {
      setLoadingTypes(false);
    }
  }, [projectId]);

  // Load entities
  const loadEntities = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await graphService.listEntities({
        tenant_id: undefined,
        project_id: projectId,
        entity_type: entityTypeFilter || undefined,
        limit,
        offset: page * limit,
      });
      setEntities(result.items);
      setTotalCount(result.total);
    } catch (err) {
      console.error('Failed to load entities:', err);
      setError(t('project.graph.entities.error'));
    } finally {
      setLoading(false);
    }
  }, [projectId, entityTypeFilter, page, t]);

  // Load relationships
  const loadRelationships = async (entityUuid: string) => {
    try {
      const result = await graphService.getEntityRelationships(entityUuid, { limit: 50 });
      // Map API response to Relationship interface
      const mappedRelationships: Relationship[] = result.relationships.map((rel) => ({
        edge_id: `${rel.source_entity_name}-${rel.relationship_type}-${rel.target_entity_name || ''}`,
        relation_type: rel.relationship_type,
        direction: rel.target_entity_name ? 'outgoing' : 'incoming',
        fact: `${rel.source_entity_name} ${rel.relationship_type} ${rel.target_entity_name || ''}`,
        score: 0,
        created_at: undefined,
        related_entity: {
          uuid: '',
          name: rel.target_entity_name || rel.source_entity_name,
          entity_type: rel.target_entity_type || rel.source_entity_type,
          summary: '',
        },
      }));
      setRelationships(mappedRelationships);
    } catch (err) {
      console.error('Failed to load relationships:', err);
    }
  };

  // Load entity types and entities in parallel (async-parallel)
  useEffect(() => {
    const loadInitialData = async () => {
      await Promise.all([loadEntityTypes(), loadEntities()]);
    };
    loadInitialData();
  }, [loadEntityTypes, loadEntities]);

  // Filter entities by search query
  const filteredEntities = entities.filter(
    (entity) =>
      searchQuery === '' ||
      entity.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (entity.summary && entity.summary.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  // Sort entities - use spread for immutable sorting (js-tosorted-immutable)
  // Note: toSorted() requires ES2023+, using spread + sort for compatibility
  const sortedEntities = [...filteredEntities].sort((a, b) => {
    if (sortBy === 'name') {
      return a.name.localeCompare(b.name);
    } else {
      const dateA = a.created_at ? new Date(a.created_at).getTime() : 0;
      const dateB = b.created_at ? new Date(b.created_at).getTime() : 0;
      return dateB - dateA; // Descending
    }
  });

  const handleEntityClick = (entity: Entity) => {
    setSelectedEntity(entity);
    loadRelationships(entity.uuid);
  };

  const handleRefresh = () => {
    loadEntities();
    loadEntityTypes();
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-start">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
            {t('project.graph.entities.title')}
          </h1>
          <p className="text-slate-600 dark:text-slate-400 mt-1">
            {t('project.graph.entities.subtitle')}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleRefresh}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
          >
            <span className="material-symbols-outlined">
              {loading ? 'progress_activity' : 'refresh'}
            </span>
            {t('project.graph.entities.refresh')}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          {/* Entity Type Filter */}
          <div className="flex items-center gap-2">
            <label
              htmlFor="entity-type-filter"
              className="text-sm font-medium text-slate-700 dark:text-slate-300 whitespace-nowrap"
            >
              {t('project.graph.entities.filter.type')}
            </label>
            <select
              id="entity-type-filter"
              value={entityTypeFilter}
              onChange={(e) => {
                setEntityTypeFilter(e.target.value);
                setPage(0);
              }}
              disabled={loadingTypes}
              className="flex-1 px-3 py-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-md text-sm text-slate-900 dark:text-white disabled:opacity-50"
            >
              <option value="">
                {t('project.graph.entities.filter.all_types')} ({totalCount})
              </option>
              {loadingTypes ? (
                <option disabled>{t('common.loading', 'Loading...')}</option>
              ) : (
                entityTypes.map((et) => (
                  <option key={et.entity_type} value={et.entity_type}>
                    {et.entity_type} ({et.count})
                  </option>
                ))
              )}
            </select>
          </div>

          {/* Search */}
          <div className="md:col-span-2 flex items-center gap-2">
            <span className="material-symbols-outlined text-slate-400">search</span>
            <input
              type="text"
              placeholder={t('project.graph.entities.filter.search_placeholder')}
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="flex-1 px-3 py-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-md text-sm text-slate-900 dark:text-white placeholder:text-slate-400"
            />
          </div>

          {/* Sort */}
          <div className="flex items-center gap-2">
            <label
              htmlFor="sort-by-filter"
              className="text-sm font-medium text-slate-700 dark:text-slate-300 whitespace-nowrap"
            >
              {t('project.graph.entities.filter.sort_by')}
            </label>
            <select
              id="sort-by-filter"
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as 'name' | 'created_at')}
              className="flex-1 px-3 py-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-md text-sm text-slate-900 dark:text-white"
            >
              <option value="created_at">{t('project.graph.entities.filter.sort_latest')}</option>
              <option value="name">{t('project.graph.entities.filter.sort_name')}</option>
            </select>
          </div>
        </div>

        {/* Stats */}
        <div className="flex items-center justify-between mt-4 pt-4 border-t border-slate-200 dark:border-slate-700">
          <div className="flex gap-4 text-sm text-slate-600 dark:text-slate-400">
            <span>
              {t('project.graph.entities.stats.showing', {
                count: sortedEntities.length,
                total: totalCount.toLocaleString(),
              })}
            </span>
            {entityTypeFilter && (
              <span className="flex items-center gap-1">
                <span className="material-symbols-outlined text-base">filter_alt</span>
                {t('project.graph.entities.filter.filtered_by')} <strong>{entityTypeFilter}</strong>
              </span>
            )}
          </div>
          {(entityTypeFilter || searchQuery) && (
            <button
              onClick={() => {
                setEntityTypeFilter('');
                setSearchInput('');
                setPage(0);
              }}
              className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
            >
              {t('project.graph.entities.filter.clear')}
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Entity List */}
        <div className="lg:col-span-2 space-y-4">
          {loading ? (
            <div className="text-center py-12">
              <span className="material-symbols-outlined text-4xl text-slate-400 animate-spin">
                progress_activity
              </span>
              <p className="text-slate-500 mt-2">{t('project.graph.entities.loading')}</p>
            </div>
          ) : error ? (
            <div className="text-center py-12">
              <span className="material-symbols-outlined text-4xl text-red-500">error</span>
              <p className="text-slate-500 mt-2">{error}</p>
              <button
                onClick={handleRefresh}
                className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-500"
              >
                {t('common.actions.retry', 'Retry')}
              </button>
            </div>
          ) : (
            <>
              {/* Virtual Grid for entity cards */}
              <VirtualGrid
                items={sortedEntities}
                renderItem={(entity: Entity) => (
                  <EntityCard
                    entity={entity}
                    onClick={handleEntityClick}
                    isSelected={selectedEntity?.uuid === entity.uuid}
                  />
                )}
                estimateSize={() => 140} // Estimated height for each entity card
                containerHeight={600} // Fixed height for scroll container
                overscan={3}
                columns="responsive"
                emptyComponent={
                  <div className="text-center py-12 bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700">
                    <span className="material-symbols-outlined text-4xl text-slate-400">
                      category
                    </span>
                    <p className="text-slate-500 mt-2">
                      {searchQuery || entityTypeFilter
                        ? t('project.graph.entities.empty_filter')
                        : t('project.graph.entities.empty')}
                    </p>
                    {(searchQuery || entityTypeFilter) && (
                      <button
                        onClick={() => {
                          setEntityTypeFilter('');
                          setSearchInput('');
                        }}
                        className="mt-4 px-4 py-2 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-md hover:bg-slate-200 dark:hover:bg-slate-600"
                      >
                        {t('project.graph.entities.filter.clear')}
                      </button>
                    )}
                  </div>
                }
              />

              {/* Pagination */}
              {totalCount > limit && (
                <div className="flex items-center justify-between bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-4">
                  <button
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={page === 0}
                    className="px-4 py-2 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-md hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {t('common.actions.previous', 'Previous')}
                  </button>
                  <span className="text-sm text-slate-600 dark:text-slate-400">
                    {t('common.pagination.page_info', {
                      page: page + 1,
                      total: Math.ceil(totalCount / limit),
                      defaultValue: `Page ${page + 1} of ${Math.ceil(totalCount / limit)}`,
                    })}
                  </span>
                  <button
                    onClick={() => setPage((p) => p + 1)}
                    disabled={(page + 1) * limit >= totalCount}
                    className="px-4 py-2 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-md hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {t('common.actions.next', 'Next')}
                  </button>
                </div>
              )}
            </>
          )}
        </div>

        {/* Entity Detail Panel */}
        <div className="lg:col-span-1">
          {selectedEntity ? (
            <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6 sticky top-6">
              <div className="flex items-start justify-between mb-4">
                <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                  {t('project.graph.entities.detail.title')}
                </h2>
                <button
                  onClick={() => {
                    setSelectedEntity(null);
                    setRelationships([]);
                  }}
                  className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                >
                  <span className="material-symbols-outlined">close</span>
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase">
                    {t('project.graph.entities.detail.name')}
                  </label>
                  <p className="text-slate-900 dark:text-white font-medium">
                    {selectedEntity.name}
                  </p>
                </div>

                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase">
                    {t('project.graph.entities.detail.type')}
                  </label>
                  <span
                    className={`inline-block px-2 py-1 rounded-full text-xs font-medium mt-1 ${getEntityTypeColor(
                      selectedEntity.entity_type || 'Unknown'
                    )}`}
                  >
                    {selectedEntity.entity_type || t('common.status.unknown', 'Unknown')}
                  </span>
                </div>

                {selectedEntity.summary && (
                  <div>
                    <label className="text-xs font-semibold text-slate-500 uppercase">
                      {t('project.graph.entities.detail.summary')}
                    </label>
                    <p className="text-sm text-slate-600 dark:text-slate-400">
                      {selectedEntity.summary}
                    </p>
                  </div>
                )}

                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase">
                    {t('project.graph.entities.detail.uuid')}
                  </label>
                  <p className="text-xs text-slate-500 dark:text-slate-400 font-mono break-all">
                    {selectedEntity.uuid}
                  </p>
                </div>

                <div>
                  <label className="text-xs font-semibold text-slate-500 uppercase">
                    {t('project.graph.entities.detail.created')}
                  </label>
                  <p className="text-sm text-slate-600 dark:text-slate-400">
                    {selectedEntity.created_at
                      ? new Date(selectedEntity.created_at).toLocaleString()
                      : t('common.status.unknown', 'Unknown')}
                  </p>
                </div>

                {/* Relationships */}
                <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-white mb-3 flex items-center gap-2">
                    <span className="material-symbols-outlined text-base">hub</span>
                    {t('project.graph.entities.detail.relationships', {
                      count: relationships.length,
                    })}
                  </h3>
                  {relationships.length > 0 ? (
                    <div className="space-y-2 max-h-96 overflow-y-auto">
                      {relationships.map((rel) => (
                        <div
                          key={rel.edge_id}
                          className="p-3 bg-slate-50 dark:bg-slate-900 rounded-md border border-slate-200 dark:border-slate-700"
                        >
                          <div className="flex items-center gap-2 mb-1">
                            <span
                              className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                                rel.direction === 'outgoing'
                                  ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                                  : 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400'
                              }`}
                            >
                              {rel.direction === 'outgoing' ? '→' : '←'}
                            </span>
                            <span className="font-medium text-blue-600 dark:text-blue-400 text-sm">
                              {rel.relation_type}
                            </span>
                          </div>
                          {rel.fact && (
                            <div className="text-xs text-slate-600 dark:text-slate-400 mt-1">
                              {rel.fact}
                            </div>
                          )}
                          <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-700">
                            <div className="text-xs text-slate-500 dark:text-slate-400">
                              {t('project.graph.entities.detail.related')}{' '}
                              <span className="font-medium text-slate-700 dark:text-slate-300">
                                {rel.related_entity.name}
                              </span>
                              <span
                                className={`ml-1 px-1 py-0.5 rounded text-[10px] ${getEntityTypeColor(
                                  rel.related_entity.entity_type || 'Unknown'
                                )}`}
                              >
                                {rel.related_entity.entity_type}
                              </span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-slate-500 flex items-center gap-2">
                      <span className="material-symbols-outlined text-base">link_off</span>
                      {t('project.graph.entities.detail.no_relationships')}
                    </p>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-12 text-center sticky top-6">
              <span className="material-symbols-outlined text-4xl text-slate-400">touch_app</span>
              <p className="text-slate-500 mt-2">
                {t('project.graph.entities.detail.select_prompt')}
              </p>
              <p className="text-sm text-slate-400 mt-1">
                {t('project.graph.entities.detail.click_prompt')}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

/**
 * Memoized EntitiesList page component.
 * Prevents unnecessary re-renders when parent components update.
 */
export const EntitiesList = memo(EntitiesListInternal);
