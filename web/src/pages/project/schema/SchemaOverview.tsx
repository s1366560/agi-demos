import { useCallback, useMemo, useState, memo } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, Link } from 'react-router-dom';

import { Code, Copy, Download, Search, Plus, Box, Network, ArrowRight, Share2 } from 'lucide-react';

import { useProjectBasePath } from '@/hooks/useProjectBasePath';

import { downloadJson } from '@/utils/downloadJson';

import { message } from '@/components/ui/lazyAntd';

import { useSchemaData } from '../../../hooks/useSwr';

import type { EdgeMapping, SchemaEdgeType, SchemaEntityType } from '@/types/memory';

import type { TFunction } from 'i18next';

interface SchemaEntityOverview extends SchemaEntityType {
  schema?: Record<string, unknown> | undefined;
  source?: string | undefined;
}

interface SchemaEdgeOverview extends SchemaEdgeType {
  schema?: Record<string, unknown> | undefined;
  source?: string | undefined;
}

type SchemaMappingOverview = EdgeMapping;

function schemaEntries(schema?: Record<string, unknown>): Array<[string, unknown]> {
  return Object.entries(schema ?? {});
}

function schemaValueLabel(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'object' && value !== null && 'type' in value) {
    const typeValue = (value as { type?: unknown }).type;
    if (typeof typeValue === 'string') return typeValue;
  }
  return 'unknown';
}

function schemaValueSearchText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (value === null || value === undefined) return '';
  try {
    return JSON.stringify(value);
  } catch {
    return '';
  }
}

function schemaRecordSearchText(schema?: Record<string, unknown>): string {
  return schemaEntries(schema)
    .map(([key, value]) => `${key} ${schemaValueSearchText(value)}`)
    .join(' ');
}

function matchesEntity(entity: SchemaEntityOverview, query: string): boolean {
  const haystack = [
    entity.name,
    entity.display_name,
    entity.description,
    entity.source,
    entity.status,
    schemaRecordSearchText(entity.schema ?? entity.properties),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  return haystack.includes(query);
}

function matchesEdge(
  edge: SchemaEdgeOverview,
  mappings: SchemaMappingOverview[],
  query: string
): boolean {
  const edgeMappings = mappings
    .filter((mapping) => mapping.edge_type === edge.name)
    .map((mapping) => `${mapping.source_type} ${mapping.target_type} ${mapping.source ?? ''}`)
    .join(' ');
  const haystack = [
    edge.name,
    edge.display_name,
    edge.description,
    edge.source,
    edge.status,
    edge.source_entity_type,
    edge.target_entity_type,
    schemaRecordSearchText(edge.schema ?? edge.properties),
    edgeMappings,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  return haystack.includes(query);
}

// Memoized entity card component to prevent unnecessary re-renders
interface EntityCardProps {
  entity: SchemaEntityOverview;
  t: TFunction;
}

const EntityCard = memo(({ entity, t }: EntityCardProps) => {
  const entries = schemaEntries(entity.schema ?? entity.properties);
  const hiddenCount = Math.max(entries.length - 4, 0);

  return (
    <div className="group relative flex flex-col gap-4 rounded-xl border border-slate-200 dark:border-surface-dark-alt bg-white dark:bg-surface-dark p-5 hover:border-emerald-500/50 dark:hover:border-emerald-500/30 transition-[color,background-color,border-color,box-shadow,opacity,transform] hover:shadow-lg hover:shadow-emerald-900/5">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="size-10 rounded-full bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-surface-dark-alt flex items-center justify-center text-slate-700 dark:text-white font-bold text-sm">
            {entity.name.slice(0, 2).toUpperCase()}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-slate-900 dark:text-white font-bold text-base group-hover:text-emerald-600 dark:group-hover:text-emerald-400 transition-colors">
                {entity.name}
              </h4>
              {entity.source === 'generated' && (
                <span className="text-2xs uppercase tracking-wider text-purple-600 dark:text-purple-400 font-bold bg-purple-100 dark:bg-purple-500/20 px-1.5 py-0.5 rounded">
                  {t('project.schema.overview.auto')}
                </span>
              )}
            </div>
            <p className="text-slate-500 dark:text-text-muted text-sm">
              {entity.description ?? t('project.schema.overview.entity_types.no_description')}
            </p>
          </div>
        </div>
      </div>
      <div className="h-px w-full bg-slate-100 dark:bg-surface-dark-alt"></div>
      <div className="flex flex-col gap-2">
        <p className="text-xs font-semibold text-slate-400 dark:text-text-muted-light uppercase tracking-wider">
          {t('project.schema.overview.entity_types.attributes')}
        </p>
        <div className="flex flex-wrap gap-2">
          {entries.slice(0, 4).map(([key, val]) => (
            <span
              key={key}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-surface-dark-alt text-xs font-mono text-slate-500 dark:text-text-muted"
            >
              <span
                className={`size-1.5 rounded-full ${key === 'name' ? 'bg-emerald-500' : 'bg-blue-500'}`}
              ></span>
              {key}: {schemaValueLabel(val)}
            </span>
          ))}
          {hiddenCount > 0 && (
            <span className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-slate-50 dark:bg-background-dark/50 border border-slate-200 dark:border-surface-dark-alt border-dashed text-xs font-medium text-slate-400 dark:text-text-muted-light">
              {t('project.schema.overview.entity_types.more', {
                count: hiddenCount,
              })}
            </span>
          )}
        </div>
      </div>
    </div>
  );
});
EntityCard.displayName = 'EntityCard';

// Memoized edge card component
interface EdgeCardProps {
  edge: SchemaEdgeOverview;
  mappings: SchemaMappingOverview[];
  t: TFunction;
}

const EdgeCard = memo(({ edge, mappings, t }: EdgeCardProps) => (
  <div className="group relative flex flex-col gap-4 rounded-xl border border-slate-200 dark:border-surface-dark-alt bg-white dark:bg-surface-dark p-5 hover:border-blue-500/50 dark:hover:border-primary/50 transition-[color,background-color,border-color,box-shadow,opacity,transform] hover:shadow-lg hover:shadow-blue-900/5">
    <div className="flex items-start justify-between">
      <div className="flex items-center gap-3">
        <div className="size-10 rounded-full bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-surface-dark-alt flex items-center justify-center">
          <Share2 className="text-blue-600 dark:text-primary w-5 h-5" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h4 className="text-slate-900 dark:text-white font-bold text-base group-hover:text-blue-600 dark:group-hover:text-primary transition-colors">
              {edge.name}
            </h4>
            {edge.source === 'generated' && (
              <span className="text-2xs uppercase tracking-wider text-purple-600 dark:text-purple-400 font-bold bg-purple-100 dark:bg-purple-500/20 px-1.5 py-0.5 rounded">
                {t('project.schema.overview.auto')}
              </span>
            )}
          </div>
          <p className="text-slate-500 dark:text-text-muted text-sm font-mono">
            {t('project.schema.overview.relationship_types.source_target')}
          </p>
        </div>
      </div>
    </div>
    <EdgeMappings edgeName={edge.name} mappings={mappings} t={t} />
    <EdgeAttributes edge={edge} t={t} />
  </div>
));
EdgeCard.displayName = 'EdgeCard';

// Memoized edge mappings component
interface EdgeMappingsProps {
  edgeName: string;
  mappings: SchemaMappingOverview[];
  t: TFunction;
}

const EdgeMappings = memo(({ edgeName, mappings, t }: EdgeMappingsProps) => {
  const filteredMappings = useMemo(
    () => mappings.filter((m) => m.edge_type === edgeName),
    [mappings, edgeName]
  );

  if (filteredMappings.length === 0) {
    return (
      <div className="flex items-center justify-center p-3 rounded-lg bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-surface-dark-alt border-dashed">
        <span className="text-xs text-slate-400 dark:text-text-muted-light italic">
          {t('project.schema.overview.relationship_types.no_active_mappings')}
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {filteredMappings.map((map) => (
        <div
          key={map.id}
          className="flex items-center gap-2 p-2 rounded-lg bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-surface-dark-alt"
        >
          <span className="px-2 py-1 rounded bg-white dark:bg-surface-dark-alt text-xs font-bold text-slate-700 dark:text-white border border-slate-200 dark:border-transparent shadow-sm">
            {map.source_type}
          </span>
          <div className="flex-1 flex flex-col items-center gap-1 relative">
            <div className="h-px w-full bg-slate-300 dark:bg-text-muted-light"></div>
            {map.source === 'generated' && (
              <span className="absolute -top-2 text-[8px] uppercase tracking-wider text-purple-600 dark:text-purple-400 font-bold bg-white dark:bg-background-dark px-1">
                {t('project.schema.overview.auto')}
              </span>
            )}
          </div>
          <ArrowRight className="text-slate-400 dark:text-text-muted-light w-4 h-4" />
          <span className="px-2 py-1 rounded bg-white dark:bg-surface-dark-alt text-xs font-bold text-slate-700 dark:text-white border border-slate-200 dark:border-transparent shadow-sm">
            {map.target_type}
          </span>
        </div>
      ))}
    </div>
  );
});
EdgeMappings.displayName = 'EdgeMappings';

// Memoized edge attributes component
interface EdgeAttributesProps {
  edge: SchemaEdgeOverview;
  t: TFunction;
}

const EdgeAttributes = memo(({ edge, t }: EdgeAttributesProps) => {
  const entries = schemaEntries(edge.schema);

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs font-semibold text-slate-400 dark:text-text-muted-light uppercase tracking-wider">
        {t('project.schema.overview.relationship_types.edge_attributes')}
      </p>
      <div className="flex flex-wrap gap-2">
        {entries.slice(0, 4).map(([key, val]) => (
          <span
            key={key}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-surface-dark-alt text-xs font-mono text-slate-500 dark:text-text-muted"
          >
            {key}: {schemaValueLabel(val)}
          </span>
        ))}
        {entries.length === 0 && (
          <span className="text-slate-400 dark:text-text-muted text-xs italic">
            {t('project.schema.overview.relationship_types.no_attributes')}
          </span>
        )}
      </div>
    </div>
  );
});
EdgeAttributes.displayName = 'EdgeAttributes';

export default function SchemaOverview() {
  const { projectId } = useParams<{ projectId: string }>();
  const { t } = useTranslation();
  const { projectBasePath } = useProjectBasePath();
  const {
    entities = [],
    edges = [],
    mappings = [],
    isLoading,
    error,
    mutate,
  } = useSchemaData(projectId);
  const [isJsonVisible, setIsJsonVisible] = useState(false);
  const [isCopyingJson, setIsCopyingJson] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const schemaJson = useMemo(
    () =>
      JSON.stringify(
        {
          project_id: projectId ?? null,
          generated_at: new Date().toISOString(),
          entities,
          edges,
          mappings,
        },
        null,
        2
      ),
    [edges, entities, mappings, projectId]
  );

  const normalizedSearchQuery = searchQuery.trim().toLowerCase();
  const filteredEntities = useMemo(() => {
    if (normalizedSearchQuery.length === 0) return entities;
    return entities.filter((entity) => matchesEntity(entity, normalizedSearchQuery));
  }, [entities, normalizedSearchQuery]);
  const filteredEdges = useMemo(() => {
    if (normalizedSearchQuery.length === 0) return edges;
    return edges.filter((edge) => matchesEdge(edge, mappings, normalizedSearchQuery));
  }, [edges, mappings, normalizedSearchQuery]);

  const handleCopyJson = useCallback(async () => {
    setIsCopyingJson(true);
    try {
      await navigator.clipboard.writeText(schemaJson);
      void message.success(t('project.schema.overview.copy_success'));
    } catch {
      void message.error(t('project.schema.overview.copy_failed'));
    } finally {
      setIsCopyingJson(false);
    }
  }, [schemaJson, t]);

  const handleDownloadJson = useCallback(() => {
    downloadJson(`memstack-schema-${projectId ?? 'project'}.json`, schemaJson);
  }, [projectId, schemaJson]);

  if (isLoading) {
    return (
      <div className="p-8 text-center text-slate-500 dark:text-gray-500" role="status">
        {t('common.loading')}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div
          role="alert"
          className="flex flex-col items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-6 py-10 text-center dark:border-red-500/30 dark:bg-red-500/10"
        >
          <p className="text-sm text-red-600 dark:text-red-400">
            {t('project.schema.overview.load_error', 'Failed to load the project schema.')}
          </p>
          <button
            type="button"
            onClick={() => {
              void mutate.entities();
              void mutate.edges();
              void mutate.mappings();
            }}
            className="inline-flex h-9 items-center rounded-lg bg-slate-950 px-4 text-sm font-medium text-slate-50 transition-colors hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950/20 dark:bg-slate-50 dark:text-slate-950 dark:hover:bg-slate-200 dark:focus-visible:ring-slate-50/20"
          >
            {t('common.retry', 'Retry')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-background-dark text-slate-900 dark:text-white overflow-hidden">
      <div className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
        <div className="max-w-[1600px] mx-auto flex flex-col gap-8">
          {/* Page Heading & Actions */}
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
            <div className="flex flex-col gap-2">
              <h1 className="text-slate-900 dark:text-white text-3xl font-bold tracking-tight">
                {t('project.schema.overview.title')}
              </h1>
              <p className="text-slate-500 dark:text-text-muted text-base max-w-2xl">
                {t('project.schema.overview.subtitle')}
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-slate-200 dark:border-surface-dark-alt bg-white dark:bg-background-dark text-slate-700 dark:text-white text-sm font-semibold hover:bg-slate-50 dark:hover:bg-surface-dark-alt transition-colors shadow-sm"
                aria-controls="schema-json-panel"
                aria-expanded={isJsonVisible}
                onClick={() => {
                  setIsJsonVisible((visible) => !visible);
                }}
              >
                <Code className="w-5 h-5" />
                {t('project.schema.overview.view_json')}
              </button>
              <button
                type="button"
                className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-blue-600 dark:bg-primary text-white text-sm font-semibold hover:bg-blue-700 transition-colors shadow-lg shadow-blue-900/20"
                onClick={handleDownloadJson}
              >
                <Download className="w-5 h-5" />
                {t('project.schema.overview.export_schema')}
              </button>
            </div>
          </div>

          {isJsonVisible && (
            <section
              id="schema-json-panel"
              aria-label={t('project.schema.overview.json_panel_label')}
              className="rounded-xl border border-slate-200 dark:border-surface-dark-alt bg-white dark:bg-surface-dark shadow-sm overflow-hidden"
            >
              <div className="flex flex-col gap-3 border-b border-slate-200 dark:border-surface-dark-alt px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 className="text-base font-bold text-slate-900 dark:text-white">
                    {t('project.schema.overview.json_panel_title')}
                  </h3>
                  <p className="mt-1 text-sm text-slate-500 dark:text-text-muted">
                    {t('project.schema.overview.json_panel_description')}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="inline-flex items-center gap-2 rounded-lg border border-slate-200 dark:border-surface-dark-alt px-3 py-2 text-sm font-semibold text-slate-700 dark:text-white hover:bg-slate-50 dark:hover:bg-surface-dark-alt disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={isCopyingJson}
                    onClick={() => {
                      void handleCopyJson();
                    }}
                  >
                    <Copy className="w-4 h-4" />
                    {t('project.schema.overview.copy_json')}
                  </button>
                  <button
                    type="button"
                    className="inline-flex items-center gap-2 rounded-lg border border-slate-200 dark:border-surface-dark-alt px-3 py-2 text-sm font-semibold text-slate-700 dark:text-white hover:bg-slate-50 dark:hover:bg-surface-dark-alt"
                    onClick={handleDownloadJson}
                  >
                    <Download className="w-4 h-4" />
                    {t('common.download')}
                  </button>
                  <button
                    type="button"
                    className="inline-flex items-center rounded-lg border border-transparent px-3 py-2 text-sm font-semibold text-slate-500 hover:bg-slate-50 hover:text-slate-900 dark:text-text-muted dark:hover:bg-background-dark dark:hover:text-white"
                    onClick={() => {
                      setIsJsonVisible(false);
                    }}
                  >
                    {t('common.close')}
                  </button>
                </div>
              </div>
              <pre
                tabIndex={0}
                aria-label={t('project.schema.overview.json_code_label')}
                className="max-h-[420px] overflow-auto bg-slate-950 p-4 text-xs leading-relaxed text-slate-100 sm:text-sm"
              >
                <code>{schemaJson}</code>
              </pre>
            </section>
          )}

          {/* Search & Filters */}
          <div className="w-full">
            <div className="relative group">
              <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                <Search className="text-slate-400 dark:text-text-muted group-focus-within:text-slate-600 dark:group-focus-within:text-white transition-colors w-5 h-5" />
              </div>
              <input
                className="w-full h-12 pl-12 pr-4 bg-white dark:bg-surface-dark-alt border border-slate-200 dark:border-transparent focus:border-blue-500 dark:focus:border-primary/50 focus:ring-2 focus:ring-blue-500/30 dark:focus:ring-primary/30 rounded-xl text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-text-muted text-sm font-medium transition-[color,background-color,border-color,box-shadow,opacity,transform] outline-none shadow-sm"
                placeholder={t('project.schema.overview.search_placeholder')}
                aria-label={t('project.schema.overview.search_placeholder')}
                type="text"
                value={searchQuery}
                onChange={(event) => {
                  setSearchQuery(event.target.value);
                }}
              />
            </div>
          </div>

          {/* Main Grid */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
            {/* Entity Types Section */}
            <section className="flex flex-col gap-5">
              <div className="flex flex-col gap-3 pb-2 border-b border-slate-200 dark:border-surface-dark-alt sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="size-8 rounded-lg bg-emerald-50 dark:bg-emerald-500/10 flex items-center justify-center border border-emerald-200 dark:border-emerald-500/20">
                    <Box className="text-emerald-600 dark:text-emerald-500 w-5 h-5" />
                  </div>
                  <h3 className="text-slate-900 dark:text-white text-lg font-bold">
                    {t('project.schema.overview.entity_types.title')}
                  </h3>
                  <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-surface-dark-alt text-slate-500 dark:text-text-muted text-xs font-mono">
                    {t('project.schema.overview.entity_types.defined', {
                      count: filteredEntities.length,
                    })}
                  </span>
                </div>
                <Link
                  to={`${projectBasePath}/schema/entities`}
                  className="text-slate-500 dark:text-text-muted hover:text-slate-900 dark:hover:text-white text-sm font-medium flex items-center gap-1 transition-colors"
                >
                  <Plus className="w-5 h-5" /> {t('project.schema.overview.entity_types.new')}
                </Link>
              </div>
              <div className="flex flex-col gap-4">
                {filteredEntities.map((entity) => (
                  <EntityCard key={entity.id} entity={entity} t={t} />
                ))}
                {filteredEntities.length === 0 && (
                  <div className="text-center p-8 text-slate-500 dark:text-text-muted bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-surface-dark-alt">
                    {normalizedSearchQuery.length > 0
                      ? t('project.schema.overview.no_results')
                      : t('project.schema.overview.entity_types.empty')}
                  </div>
                )}
              </div>
            </section>

            {/* Relationship Types Section */}
            <section className="flex flex-col gap-5">
              <div className="flex flex-col gap-3 pb-2 border-b border-slate-200 dark:border-surface-dark-alt sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="size-8 rounded-lg bg-blue-50 dark:bg-primary/10 flex items-center justify-center border border-blue-200 dark:border-primary/20">
                    <Network className="text-blue-600 dark:text-primary w-5 h-5" />
                  </div>
                  <h3 className="text-slate-900 dark:text-white text-lg font-bold">
                    {t('project.schema.overview.relationship_types.title')}
                  </h3>
                  <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-surface-dark-alt text-slate-500 dark:text-text-muted text-xs font-mono">
                    {t('project.schema.overview.relationship_types.defined', {
                      count: filteredEdges.length,
                    })}
                  </span>
                </div>
                <Link
                  to={`${projectBasePath}/schema/edges`}
                  className="text-slate-500 dark:text-text-muted hover:text-slate-900 dark:hover:text-white text-sm font-medium flex items-center gap-1 transition-colors"
                >
                  <Plus className="w-5 h-5" /> {t('project.schema.overview.relationship_types.new')}
                </Link>
              </div>
              <div className="flex flex-col gap-4">
                {filteredEdges.map((edge) => (
                  <EdgeCard key={edge.id} edge={edge} mappings={mappings} t={t} />
                ))}
                {filteredEdges.length === 0 && (
                  <div className="text-center p-8 text-slate-500 dark:text-text-muted bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-surface-dark-alt">
                    {normalizedSearchQuery.length > 0
                      ? t('project.schema.overview.no_results')
                      : t('project.schema.overview.relationship_types.empty')}
                  </div>
                )}
              </div>
            </section>
          </div>
          <div className="h-10"></div>
        </div>
      </div>
    </div>
  );
}
