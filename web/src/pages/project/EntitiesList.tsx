/**
 * EntitiesList - Entity Management with Compound Component Pattern
 *
 * ## Usage
 *
 * ### Convenience Usage (Default rendering)
 * ```tsx
 * <EntitiesList />
 * ```
 *
 * ### Compound Components (Custom rendering)
 * ```tsx
 * <EntitiesList>
 *   <EntitiesList.Header />
 *   <EntitiesList.Filters />
 *   <EntitiesList.List />
 *   <EntitiesList.Detail />
 * </EntitiesList>
 * ```
 *
 * ### Namespace Usage
 * ```tsx
 * <EntitiesList.Root>
 *   <EntitiesList.List />
 *   <EntitiesList.Detail />
 * </EntitiesList.Root>
 * ```
 */

import React, { useState, useEffect, useCallback, memo, Children, useMemo, useRef } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams } from 'react-router-dom';

import {
  AlertCircle,
  Filter,
  LayoutGrid,
  Loader2,
  Network,
  Pointer,
  RefreshCw,
  Search,
  Unlink,
  X,
} from 'lucide-react';
import { useDebounce } from 'use-debounce';

import { formatDateOnly, formatDateTime } from '@/utils/date';

import { VirtualGrid } from '../../components/common';
import { getEntityTypeColor } from '../../components/graph';
import { graphService } from '../../services/graphService';

import type {
  EntitiesListRootProps,
  EntitiesListHeaderProps,
  EntitiesListFiltersProps,
  EntitiesListStatsProps,
  EntitiesListListProps,
  EntitiesListPaginationProps,
  EntitiesListDetailProps,
  EntitiesListCompound,
  SortOption,
} from './entities/types';

interface Entity {
  uuid: string;
  name: string;
  entity_type: string;
  summary: string;
  created_at?: string | undefined;
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
  created_at?: string | undefined;
  related_entity: {
    uuid: string;
    name: string;
    entity_type: string;
    summary: string;
  };
}

const ENTITY_LIST_HEIGHT = 600;
const ENTITY_CARD_ESTIMATE_SIZE = 116;
const ENTITY_TYPE_PREVIEW_LIMIT = 6;

const formatEntityCount = (count: number): string => count.toLocaleString();

interface EntityListItemProps {
  entity: Entity;
  isSelected: boolean;
  onClick: (entity: Entity) => void;
  createdLabel: string;
  unknownLabel: string;
}

const EntityListItem: React.FC<EntityListItemProps> = memo(
  ({ entity, isSelected, onClick, createdLabel, unknownLabel }) => {
    const entityType = entity.entity_type || unknownLabel;

    return (
      <button
        type="button"
        onClick={() => {
          onClick(entity);
        }}
        className={`group w-full rounded-md border bg-white p-4 text-left transition-[background-color,border-color,box-shadow] hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-950/10 dark:bg-surface-dark dark:hover:bg-slate-900/60 dark:focus:ring-slate-50/10 ${
          isSelected
            ? 'border-primary shadow-[0_0_0_1px_rgba(30,63,174,0.16)] dark:border-primary-light'
            : 'border-slate-200 dark:border-slate-800'
        }`}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-slate-950 dark:text-slate-50">
              {entity.name}
            </h3>
            <p className="mt-2 line-clamp-2 text-sm leading-5 text-slate-600 dark:text-slate-400">
              {entity.summary || unknownLabel}
            </p>
          </div>
          <span
            className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${getEntityTypeColor(
              entityType
            )}`}
          >
            {entityType}
          </span>
        </div>
        <div className="mt-3 flex items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400">
          <span className="font-mono">{entity.uuid.slice(0, 8)}...</span>
          <span>
            {createdLabel}: {entity.created_at ? formatDateOnly(entity.created_at) : unknownLabel}
          </span>
        </div>
      </button>
    );
  }
);

EntityListItem.displayName = 'EntityListItem';

// ========================================
// Marker Symbols for Sub-Components
// ========================================

const HEADER_SYMBOL = Symbol('EntitiesListHeader');
const FILTERS_SYMBOL = Symbol('EntitiesListFilters');
const STATS_SYMBOL = Symbol('EntitiesListStats');
const LIST_SYMBOL = Symbol('EntitiesListList');
const PAGINATION_SYMBOL = Symbol('EntitiesListPagination');
const DETAIL_SYMBOL = Symbol('EntitiesListDetail');

// ========================================
// Sub-Components (Marker Components)
// ========================================
// Must be defined before the main component

function HeaderMarker(_props: EntitiesListHeaderProps) {
  return null;
}
function FiltersMarker(_props: EntitiesListFiltersProps) {
  return null;
}
function StatsMarker(_props: EntitiesListStatsProps) {
  return null;
}
function ListMarker(_props: EntitiesListListProps) {
  return null;
}
function PaginationMarker(_props: EntitiesListPaginationProps) {
  return null;
}
function DetailMarker(_props: EntitiesListDetailProps) {
  return null;
}

const markSubComponent = <P extends object>(
  component: React.FC<P>,
  marker: symbol,
  displayName: string
): React.FC<P> => Object.assign(component, { [marker]: true, displayName });

const hasSubComponentMarker = (child: React.ReactNode, marker: symbol): boolean => {
  if (!React.isValidElement(child) || typeof child.type === 'string') return false;
  const type = child.type as React.JSXElementConstructor<unknown> & Record<symbol, unknown>;
  return type[marker] === true;
};

markSubComponent(HeaderMarker, HEADER_SYMBOL, 'EntitiesListHeader');
markSubComponent(FiltersMarker, FILTERS_SYMBOL, 'EntitiesListFilters');
markSubComponent(StatsMarker, STATS_SYMBOL, 'EntitiesListStats');
markSubComponent(ListMarker, LIST_SYMBOL, 'EntitiesListList');
markSubComponent(PaginationMarker, PAGINATION_SYMBOL, 'EntitiesListPagination');
markSubComponent(DetailMarker, DETAIL_SYMBOL, 'EntitiesListDetail');

// ========================================
// Main Component
// ========================================

const EntitiesListInner: React.FC<EntitiesListRootProps> = memo(
  ({
    projectId: propProjectId,
    tenantId: propTenantId,
    children,
    defaultSortBy = 'created_at',
    limit = 20,
  }) => {
    const { t } = useTranslation();
    const { tenantId: routeTenantId, projectId: routeProjectId } = useParams();
    const tenantId = propTenantId || routeTenantId;
    const projectId = propProjectId || routeProjectId;

    // Parse children to detect sub-components
    const childrenArray = Children.toArray(children);
    const headerChild = childrenArray.find((child) => hasSubComponentMarker(child, HEADER_SYMBOL));
    const filtersChild = childrenArray.find((child) =>
      hasSubComponentMarker(child, FILTERS_SYMBOL)
    );
    const statsChild = childrenArray.find((child) => hasSubComponentMarker(child, STATS_SYMBOL));
    const listChild = childrenArray.find((child) => hasSubComponentMarker(child, LIST_SYMBOL));
    const paginationChild = childrenArray.find((child) =>
      hasSubComponentMarker(child, PAGINATION_SYMBOL)
    );
    const detailChild = childrenArray.find((child) => hasSubComponentMarker(child, DETAIL_SYMBOL));

    // Determine if using compound mode
    const hasSubComponents = Boolean(
      headerChild || filtersChild || statsChild || listChild || paginationChild || detailChild
    );

    // In legacy mode, include all sections by default
    // In compound mode, only include explicitly specified sections
    const includeHeader = hasSubComponents ? !!headerChild : true;
    const includeFilters = hasSubComponents ? !!filtersChild : true;
    const includeStats = hasSubComponents ? !!statsChild : true;
    const includeList = hasSubComponents ? !!listChild : true;
    const includePagination = hasSubComponents ? !!paginationChild : true;
    const includeDetail = hasSubComponents ? !!detailChild : true;
    const shouldLoadEntityTypes = includeFilters;
    const shouldLoadEntities = includeFilters || includeStats || includeList || includePagination;

    // State
    const [entities, setEntities] = useState<Entity[]>([]);
    const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);
    const [relationships, setRelationships] = useState<Relationship[]>([]);
    const [entityTypes, setEntityTypes] = useState<EntityType[]>([]);
    const [loading, setLoading] = useState(shouldLoadEntities);
    const [loadingTypes, setLoadingTypes] = useState(shouldLoadEntityTypes);
    const [error, setError] = useState<string | null>(null);
    const [page, setPage] = useState(0);
    const [totalCount, setTotalCount] = useState(0);

    // Filters
    const [entityTypeFilter, setEntityTypeFilter] = useState<string>('');
    const [searchInput, setSearchInput] = useState<string>('');
    const [sortBy, setSortBy] = useState<SortOption>(defaultSortBy);

    // Debounced search value for filtering (300ms delay)
    const [searchQuery] = useDebounce(searchInput, 300);
    const entityTypesRequestRef = useRef(0);
    const entitiesRequestRef = useRef(0);
    const relationshipsRequestRef = useRef(0);

    useEffect(() => {
      entityTypesRequestRef.current += 1;
      entitiesRequestRef.current += 1;
      relationshipsRequestRef.current += 1;
      setSelectedEntity(null);
      setRelationships([]);
      return () => {
        entityTypesRequestRef.current += 1;
        entitiesRequestRef.current += 1;
        relationshipsRequestRef.current += 1;
      };
    }, [tenantId, projectId]);

    // Load entity types
    const loadEntityTypes = useCallback(async () => {
      const requestId = entityTypesRequestRef.current + 1;
      entityTypesRequestRef.current = requestId;
      setLoadingTypes(true);
      try {
        const result = await graphService.getEntityTypes({ project_id: projectId });
        if (entityTypesRequestRef.current !== requestId) return;
        setEntityTypes(result.entity_types);
      } catch (err) {
        if (entityTypesRequestRef.current !== requestId) return;
        console.error('Failed to load entity types:', err);
      } finally {
        if (entityTypesRequestRef.current === requestId) {
          setLoadingTypes(false);
        }
      }
    }, [projectId]);

    // Load entities
    const loadEntities = useCallback(async () => {
      const requestId = entitiesRequestRef.current + 1;
      entitiesRequestRef.current = requestId;
      setLoading(true);
      setError(null);
      try {
        const result = await graphService.listEntities({
          tenant_id: tenantId,
          project_id: projectId,
          entity_type: entityTypeFilter || undefined,
          limit,
          offset: page * limit,
        });
        if (entitiesRequestRef.current !== requestId) return;
        setEntities(result.items);
        setTotalCount(result.total);
      } catch (err) {
        if (entitiesRequestRef.current !== requestId) return;
        console.error('Failed to load entities:', err);
        setError(t('project.graph.entities.error'));
      } finally {
        if (entitiesRequestRef.current === requestId) {
          setLoading(false);
        }
      }
    }, [tenantId, projectId, entityTypeFilter, page, limit, t]);

    // Load relationships
    const loadRelationships = async (entityUuid: string) => {
      const requestId = relationshipsRequestRef.current + 1;
      relationshipsRequestRef.current = requestId;
      try {
        const result = await graphService.getEntityRelationships(entityUuid, { limit: 50 });
        const mappedRelationships: Relationship[] = result.relationships.map((rel, index) => ({
          edge_id: rel.edge_id || `${entityUuid}-${rel.relation_type}-${String(index)}`,
          relation_type: rel.relation_type,
          direction: rel.direction,
          fact: rel.fact,
          score: rel.score,
          created_at: rel.created_at,
          related_entity: rel.related_entity,
        }));
        if (relationshipsRequestRef.current !== requestId) return;
        setRelationships(mappedRelationships);
      } catch (err) {
        if (relationshipsRequestRef.current !== requestId) return;
        console.error('Failed to load relationships:', err);
      }
    };

    // Load entity types and entities in parallel
    useEffect(() => {
      const loadInitialData = async () => {
        const loaders: Array<Promise<void>> = [];
        if (shouldLoadEntityTypes) {
          loaders.push(loadEntityTypes());
        }
        if (shouldLoadEntities) {
          loaders.push(loadEntities());
        }
        await Promise.all(loaders);
      };
      void loadInitialData();
    }, [loadEntityTypes, loadEntities, shouldLoadEntityTypes, shouldLoadEntities]);

    // Filter entities by search query
    const filteredEntities = entities.filter(
      (entity) =>
        searchQuery === '' ||
        (entity.name && entity.name.toLowerCase().includes(searchQuery.toLowerCase())) ||
        (entity.summary && entity.summary.toLowerCase().includes(searchQuery.toLowerCase()))
    );

    // Sort entities
    const sortedEntities = [...filteredEntities].sort((a, b) => {
      if (sortBy === 'name') {
        return a.name.localeCompare(b.name);
      } else {
        const dateA = a.created_at ? new Date(a.created_at).getTime() : 0;
        const dateB = b.created_at ? new Date(b.created_at).getTime() : 0;
        return dateB - dateA; // Descending
      }
    });

    const entityTypeOptions = useMemo(
      () => [
        {
          entity_type: '',
          count: totalCount,
          label: t('project.graph.entities.filter.all_types'),
        },
        ...entityTypes.slice(0, ENTITY_TYPE_PREVIEW_LIMIT).map((entityType) => ({
          entity_type: entityType.entity_type,
          count: entityType.count,
          label: entityType.entity_type,
        })),
      ],
      [entityTypes, t, totalCount]
    );
    const selectedTypeLabel = entityTypeFilter || t('project.graph.entities.filter.all_types');
    const activeFilterCount = [entityTypeFilter, searchQuery].filter(Boolean).length;
    const totalPages = Math.max(1, Math.ceil(totalCount / limit));
    const headerStats = [
      {
        label: t('project.graph.entities.metrics.total', 'Total'),
        value: formatEntityCount(totalCount),
      },
      {
        label: t('project.graph.entities.metrics.visible', 'Visible'),
        value: formatEntityCount(sortedEntities.length),
      },
      {
        label: t('project.graph.entities.metrics.types', 'Types'),
        value: formatEntityCount(entityTypes.length),
      },
    ];

    const handleEntityClick = (entity: Entity) => {
      setSelectedEntity(entity);
      setRelationships([]);
      void loadRelationships(entity.uuid);
    };

    const handleRefresh = () => {
      if (shouldLoadEntities) {
        void loadEntities();
      }
      if (shouldLoadEntityTypes) {
        void loadEntityTypes();
      }
    };

    const handleClearFilters = () => {
      setEntityTypeFilter('');
      setSearchInput('');
      setPage(0);
    };

    return (
      <div className="mx-auto flex w-full max-w-none flex-col gap-5">
        {/* Header */}
        {includeHeader && (
          <div
            className="flex flex-wrap items-start justify-between gap-4"
            data-testid="entities-header"
          >
            <div className="min-w-0">
              <div className="mb-2 inline-flex items-center gap-2 text-xs font-medium text-slate-500 dark:text-slate-400">
                <Network size={14} aria-hidden="true" />
                <span>{t('project.graph.entities.eyebrow', 'Knowledge graph')}</span>
              </div>
              <h1 className="text-[22px] font-semibold leading-7 text-slate-950 dark:text-slate-50">
                {t('project.graph.entities.title')}
              </h1>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {t('project.graph.entities.subtitle')}
              </p>
              <dl className="mt-4 flex flex-wrap gap-2">
                {headerStats.map((stat) => (
                  <div
                    key={stat.label}
                    className="inline-flex h-7 items-center gap-2 rounded-full border border-slate-200 bg-white px-3 text-xs text-slate-500 dark:border-slate-800 dark:bg-slate-900/40 dark:text-slate-400"
                  >
                    <dt>{stat.label}</dt>
                    <dd className="font-semibold text-slate-950 dark:text-slate-100">
                      {stat.value}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={loading}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-slate-950 px-4 text-sm font-medium text-slate-50 transition-colors hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-950/20 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-50 dark:text-slate-950 dark:hover:bg-slate-200 dark:focus:ring-slate-50/20"
            >
              {loading ? (
                <Loader2
                  size={16}
                  className="animate-spin motion-reduce:animate-none"
                  aria-hidden="true"
                />
              ) : (
                <RefreshCw size={16} aria-hidden="true" />
              )}
              {t('project.graph.entities.refresh')}
            </button>
          </div>
        )}

        {/* Filters */}
        {includeFilters && (
          <div
            className="overflow-hidden rounded-md bg-white shadow-[0_0_0_1px_rgba(15,23,42,0.10)] dark:bg-surface-dark dark:shadow-[0_0_0_1px_rgba(148,163,184,0.16)]"
            data-testid="entities-filters"
          >
            <div className="flex flex-col gap-3 p-3">
              <div className="flex min-w-0 flex-col gap-2">
                <label
                  htmlFor="entity-type-filter"
                  className="text-xs font-medium text-slate-500 dark:text-slate-400"
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
                  className="sr-only"
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
                <div
                  className="flex w-full gap-1 overflow-x-auto rounded-md border border-slate-200 bg-slate-50 p-1 dark:border-slate-800 dark:bg-slate-950/30"
                  role="group"
                  aria-label={t('project.graph.entities.filter.type_options')}
                >
                  {entityTypeOptions.map((option) => {
                    const isActive = entityTypeFilter === option.entity_type;
                    return (
                      <button
                        key={option.entity_type || 'all'}
                        type="button"
                        aria-pressed={isActive}
                        onClick={() => {
                          setEntityTypeFilter(option.entity_type);
                          setPage(0);
                        }}
                        disabled={loadingTypes}
                        className={`inline-flex h-8 shrink-0 items-center gap-2 rounded px-2.5 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-slate-950/10 disabled:cursor-not-allowed disabled:opacity-50 dark:focus:ring-slate-50/10 ${
                          isActive
                            ? 'bg-white text-slate-950 shadow-[0_0_0_1px_rgba(15,23,42,0.10)] dark:bg-slate-800 dark:text-slate-50 dark:shadow-[0_0_0_1px_rgba(148,163,184,0.16)]'
                            : 'text-slate-500 hover:bg-white hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-100'
                        }`}
                      >
                        <span>{option.label}</span>
                        <span
                          className={`rounded-full px-1.5 text-[11px] leading-5 ${
                            isActive
                              ? 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-200'
                              : 'bg-white text-slate-400 dark:bg-slate-900 dark:text-slate-500'
                          }`}
                        >
                          {formatEntityCount(option.count)}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px]">
                <div className="relative">
                  <Search
                    size={16}
                    className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
                    aria-hidden="true"
                  />
                  <input
                    type="text"
                    placeholder={t('project.graph.entities.filter.search_placeholder')}
                    value={searchInput}
                    onChange={(e) => {
                      setSearchInput(e.target.value);
                    }}
                    className="block h-9 w-full rounded-md border border-slate-200 bg-white pl-10 pr-3 text-sm text-slate-950 outline-none transition-colors placeholder:text-slate-400 hover:border-slate-300 focus:border-slate-950 focus:ring-2 focus:ring-slate-950/10 dark:border-slate-800 dark:bg-slate-900/30 dark:text-slate-50 dark:hover:border-slate-700 dark:focus:border-slate-400 dark:focus:ring-slate-50/10"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <label
                    htmlFor="sort-by-filter"
                    className="shrink-0 text-xs font-medium text-slate-500 dark:text-slate-400"
                  >
                    {t('project.graph.entities.filter.sort_by')}
                  </label>
                  <select
                    id="sort-by-filter"
                    value={sortBy}
                    onChange={(e) => {
                      setSortBy(e.target.value as SortOption);
                    }}
                    className="h-9 min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-950 outline-none transition-colors hover:border-slate-300 focus:border-slate-950 focus:ring-2 focus:ring-slate-950/10 dark:border-slate-800 dark:bg-slate-900/30 dark:text-slate-50 dark:hover:border-slate-700 dark:focus:border-slate-400 dark:focus:ring-slate-50/10"
                  >
                    <option value="created_at">
                      {t('project.graph.entities.filter.sort_latest')}
                    </option>
                    <option value="name">{t('project.graph.entities.filter.sort_name')}</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Stats */}
            {includeStats && (
              <div
                className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-3 py-2.5 dark:border-slate-800"
                data-testid="entities-stats"
              >
                <div className="flex flex-wrap items-center gap-3 text-sm text-slate-500 dark:text-slate-400">
                  <span>
                    {t('project.graph.entities.stats.showing', {
                      count: sortedEntities.length,
                      total: totalCount.toLocaleString(),
                    })}
                  </span>
                  {activeFilterCount > 0 && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                      <Filter size={14} aria-hidden="true" />
                      {t('project.graph.entities.filter.filtered_by')}: {selectedTypeLabel}
                    </span>
                  )}
                </div>
                {(entityTypeFilter || searchQuery) && (
                  <button
                    type="button"
                    onClick={handleClearFilters}
                    className="text-sm font-medium text-slate-600 transition-colors hover:text-slate-950 focus:outline-none focus:ring-2 focus:ring-slate-950/10 dark:text-slate-300 dark:hover:text-slate-50 dark:focus:ring-slate-50/10"
                  >
                    {t('project.graph.entities.filter.clear')}
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          {/* Entity List */}
          {includeList && (
            <div className="min-w-0 space-y-4">
              {loading ? (
                <div className="space-y-3" aria-label={t('project.graph.entities.loading')}>
                  {Array.from({ length: 5 }, (_, index) => (
                    <div
                      key={`entity-skeleton-${String(index)}`}
                      className="h-[104px] rounded-md border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-surface-dark"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0 flex-1 space-y-3">
                          <div className="h-3.5 w-1/3 animate-pulse rounded bg-slate-100 motion-reduce:animate-none dark:bg-slate-800"></div>
                          <div className="h-3 w-full animate-pulse rounded bg-slate-100 motion-reduce:animate-none dark:bg-slate-800"></div>
                          <div className="h-3 w-2/3 animate-pulse rounded bg-slate-100 motion-reduce:animate-none dark:bg-slate-800"></div>
                        </div>
                        <div className="h-6 w-20 animate-pulse rounded-full bg-slate-100 motion-reduce:animate-none dark:bg-slate-800"></div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : error ? (
                <div className="flex flex-col items-center justify-center rounded-md border border-error-border bg-error-bg px-6 py-14 text-center dark:border-error-border-dark dark:bg-error-bg-dark">
                  <div className="flex h-10 w-10 items-center justify-center rounded-md border border-error-border bg-white text-error dark:border-error-border-dark dark:bg-slate-950/30 dark:text-error-light">
                    <AlertCircle size={18} aria-hidden="true" />
                  </div>
                  <p className="mt-3 max-w-md text-sm text-status-text-error dark:text-status-text-error-dark">
                    {error}
                  </p>
                  <button
                    type="button"
                    onClick={handleRefresh}
                    className="mt-5 inline-flex h-9 items-center rounded-md bg-slate-950 px-4 text-sm font-medium text-slate-50 transition-colors hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-950/20 dark:bg-slate-50 dark:text-slate-950 dark:hover:bg-slate-200 dark:focus:ring-slate-50/20"
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
                      <EntityListItem
                        entity={entity}
                        onClick={handleEntityClick}
                        isSelected={selectedEntity?.uuid === entity.uuid}
                        createdLabel={t('project.graph.entities.detail.created')}
                        unknownLabel={t('common.status.unknown', 'Unknown')}
                      />
                    )}
                    estimateSize={() => ENTITY_CARD_ESTIMATE_SIZE}
                    containerHeight={ENTITY_LIST_HEIGHT}
                    overscan={3}
                    columns={1}
                    className="rounded-md"
                    emptyComponent={
                      <div className="flex flex-col items-center justify-center rounded-md border border-slate-200 bg-white px-6 py-16 text-center dark:border-slate-800 dark:bg-surface-dark">
                        <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-400">
                          <LayoutGrid size={18} aria-hidden="true" />
                        </div>
                        <p className="text-base font-semibold text-slate-950 dark:text-slate-50">
                          {searchQuery || entityTypeFilter
                            ? t('project.graph.entities.empty_filter')
                            : t('project.entities.empty')}
                        </p>
                        <p className="mt-1 max-w-sm text-sm text-slate-500 dark:text-slate-400">
                          {t(
                            'project.graph.entities.empty_hint',
                            'Entities appear here after memories are indexed.'
                          )}
                        </p>
                        {(searchQuery || entityTypeFilter) && (
                          <button
                            type="button"
                            onClick={handleClearFilters}
                            className="mt-5 inline-flex h-9 items-center rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-950 transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-950/10 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-50 dark:hover:bg-slate-800 dark:focus:ring-slate-50/10"
                          >
                            {t('project.graph.entities.filter.clear')}
                          </button>
                        )}
                      </div>
                    }
                  />

                  {/* Pagination */}
                  {includePagination && totalCount > limit && (
                    <div
                      className="flex items-center justify-between rounded-md bg-white p-3 shadow-[0_0_0_1px_rgba(15,23,42,0.10)] dark:bg-surface-dark dark:shadow-[0_0_0_1px_rgba(148,163,184,0.16)]"
                      data-testid="entities-pagination"
                    >
                      <button
                        type="button"
                        onClick={() => {
                          setPage((p) => Math.max(0, p - 1));
                        }}
                        disabled={page === 0}
                        className="inline-flex h-9 items-center rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                      >
                        {t('common.actions.previous', 'Previous')}
                      </button>
                      <span className="text-sm text-slate-500 dark:text-slate-400">
                        {t('common.pagination.page_info', {
                          page: page + 1,
                          total: totalPages,
                          defaultValue: `Page ${String(page + 1)} of ${String(totalPages)}`,
                        })}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          setPage((p) => p + 1);
                        }}
                        disabled={(page + 1) * limit >= totalCount}
                        className="inline-flex h-9 items-center rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
                      >
                        {t('common.actions.next', 'Next')}
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Entity Detail Panel */}
          {includeDetail && (
            <div className="min-w-0">
              {selectedEntity ? (
                <div
                  className="sticky top-4 rounded-md bg-white p-5 shadow-[0_0_0_1px_rgba(15,23,42,0.10)] dark:bg-surface-dark dark:shadow-[0_0_0_1px_rgba(148,163,184,0.16)]"
                  data-testid="entities-detail"
                >
                  <div className="mb-5 flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
                        {t('project.graph.entities.detail.title')}
                      </p>
                      <h2 className="mt-1 truncate text-lg font-semibold text-slate-950 dark:text-slate-50">
                        {selectedEntity.name}
                      </h2>
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedEntity(null);
                        setRelationships([]);
                      }}
                      aria-label={t('project.graph.entities.detail.close', 'Close entity details')}
                      title={t('project.graph.entities.detail.close', 'Close entity details')}
                      className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-950 focus:outline-none focus:ring-2 focus:ring-slate-950/10 dark:hover:bg-slate-800 dark:hover:text-slate-50 dark:focus:ring-slate-50/10"
                    >
                      <X size={16} aria-hidden="true" />
                    </button>
                  </div>

                  <div className="space-y-5">
                    <div className="grid gap-4 rounded-md border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950/30">
                      <div>
                        <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
                          {t('project.graph.entities.detail.type')}
                        </span>
                        <span
                          className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${getEntityTypeColor(
                            selectedEntity.entity_type || 'Unknown'
                          )}`}
                        >
                          {selectedEntity.entity_type || t('common.status.unknown', 'Unknown')}
                        </span>
                      </div>
                      <div>
                        <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
                          {t('project.graph.entities.detail.created')}
                        </span>
                        <p className="text-sm text-slate-700 dark:text-slate-300">
                          {selectedEntity.created_at
                            ? formatDateTime(selectedEntity.created_at)
                            : t('common.status.unknown', 'Unknown')}
                        </p>
                      </div>
                    </div>

                    {selectedEntity.summary && (
                      <div>
                        <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
                          {t('project.graph.entities.detail.summary')}
                        </span>
                        <p className="text-sm leading-6 text-slate-600 dark:text-slate-400">
                          {selectedEntity.summary}
                        </p>
                      </div>
                    )}

                    <div>
                      <span className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400">
                        {t('project.graph.entities.detail.uuid')}
                      </span>
                      <p className="break-all rounded-md border border-slate-200 bg-slate-50 p-2 font-mono text-xs text-slate-500 dark:border-slate-800 dark:bg-slate-950/30 dark:text-slate-400">
                        {selectedEntity.uuid}
                      </p>
                    </div>

                    {/* Relationships */}
                    <div className="border-t border-slate-200 pt-4 dark:border-slate-800">
                      <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-950 dark:text-slate-50">
                        <Network size={16} aria-hidden="true" />
                        {t('project.graph.entities.detail.relationships', {
                          count: relationships.length,
                        })}
                      </h3>
                      {relationships.length > 0 ? (
                        <div className="space-y-2 max-h-96 overflow-y-auto">
                          {relationships.map((rel) => (
                            <div
                              key={rel.edge_id}
                              className="rounded-md border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-950/30"
                            >
                              <div className="flex items-center gap-2 mb-1">
                                <span
                                  className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                                    rel.direction === 'outgoing'
                                      ? 'bg-success-bg text-status-text-success dark:bg-success-bg-dark dark:text-status-text-success-dark'
                                      : 'bg-info-bg text-status-text-info dark:bg-info-bg-dark dark:text-status-text-info-dark'
                                  }`}
                                >
                                  {rel.direction === 'outgoing' ? '→' : '←'}
                                </span>
                                <span className="text-sm font-medium text-slate-900 dark:text-slate-100">
                                  {rel.relation_type}
                                </span>
                              </div>
                              {rel.fact && (
                                <div className="text-xs text-slate-600 dark:text-slate-400 mt-1">
                                  {rel.fact}
                                </div>
                              )}
                              <div className="mt-2 border-t border-slate-200 pt-2 dark:border-slate-800">
                                <div className="text-xs text-slate-500 dark:text-slate-400">
                                  {t('project.graph.entities.detail.related')}{' '}
                                  <span className="font-medium text-slate-700 dark:text-slate-300">
                                    {rel.related_entity.name}
                                  </span>
                                  <span
                                    className={`ml-1 px-1 py-0.5 rounded text-2xs ${getEntityTypeColor(
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
                        <p className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                          <Unlink size={16} aria-hidden="true" />
                          {t('project.graph.entities.detail.no_relationships')}
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div
                  className="sticky top-4 rounded-md bg-white px-6 py-16 text-center shadow-[0_0_0_1px_rgba(15,23,42,0.10)] dark:bg-surface-dark dark:shadow-[0_0_0_1px_rgba(148,163,184,0.16)]"
                  data-testid="entities-detail"
                >
                  <div className="mx-auto mb-4 flex h-10 w-10 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-500 dark:border-slate-800 dark:bg-slate-900/50 dark:text-slate-400">
                    <Pointer size={18} aria-hidden="true" />
                  </div>
                  <p className="text-base font-semibold text-slate-950 dark:text-slate-50">
                    {t('project.graph.entities.detail.select_prompt')}
                  </p>
                  <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                    {t('project.graph.entities.detail.click_prompt')}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    );
  }
);

// Create compound component with sub-components
const EntitiesListMemo = memo(EntitiesListInner);
EntitiesListMemo.displayName = 'EntitiesList';

// Create compound component object
const EntitiesListCompoundObj = EntitiesListMemo as unknown as EntitiesListCompound;
EntitiesListCompoundObj.Header = HeaderMarker;
EntitiesListCompoundObj.Filters = FiltersMarker;
EntitiesListCompoundObj.Stats = StatsMarker;
EntitiesListCompoundObj.List = ListMarker;
EntitiesListCompoundObj.Pagination = PaginationMarker;
EntitiesListCompoundObj.Detail = DetailMarker;
EntitiesListCompoundObj.Root = EntitiesListMemo;

// Export compound component
export const EntitiesList = EntitiesListCompoundObj;

export default EntitiesList;
