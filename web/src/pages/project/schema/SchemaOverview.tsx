import { useMemo, memo } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, Link } from 'react-router-dom';

import {
  Code,
  Download,
  Search,
  Plus,
  MoreVertical,
  Box,
  Network,
  ArrowRight,
  Share2,
} from 'lucide-react';

import { useProjectBasePath } from '@/hooks/useProjectBasePath';

import { useSchemaData } from '../../../hooks/useSwr';

// Memoized entity card component to prevent unnecessary re-renders
interface EntityCardProps {
  entity: any;
  t: (key: string, params?: any) => string;
}

const EntityCard = memo(({ entity, t }: EntityCardProps) => (
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
                {String(t('project.schema.overview.auto'))}
              </span>
            )}
          </div>
          <p className="text-slate-500 dark:text-text-muted text-sm">
            {entity.description || String(t('project.schema.overview.entity_types.no_description'))}
          </p>
        </div>
      </div>
      <button className="text-slate-400 dark:text-text-muted-light hover:text-slate-900 dark:hover:text-white transition-colors">
        <MoreVertical className="w-5 h-5" />
      </button>
    </div>
    <div className="h-px w-full bg-slate-100 dark:bg-surface-dark-alt"></div>
    <div className="flex flex-col gap-2">
      <p className="text-xs font-semibold text-slate-400 dark:text-text-muted-light uppercase tracking-wider">
        {String(t('project.schema.overview.entity_types.attributes'))}
      </p>
      <div className="flex flex-wrap gap-2">
        {Object.entries(entity.schema || {})
          .slice(0, 4)
          .map(([key, val]: [string, any]) => (
            <span
              key={key}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-surface-dark-alt text-xs font-mono text-slate-500 dark:text-text-muted"
            >
              <span
                className={`size-1.5 rounded-full ${key === 'name' ? 'bg-emerald-500' : 'bg-blue-500'}`}
              ></span>
              {key}: {typeof val === 'string' ? val : val.type}
            </span>
          ))}
        {Object.keys(entity.schema || {}).length > 4 && (
          <span className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-slate-50 dark:bg-background-dark/50 border border-slate-200 dark:border-surface-dark-alt border-dashed text-xs font-medium text-slate-400 dark:text-text-muted-light">
            {String(
              t('project.schema.overview.entity_types.more', {
                count: Object.keys(entity.schema || {}).length - 4,
              })
            )}
          </span>
        )}
      </div>
    </div>
  </div>
));
EntityCard.displayName = 'EntityCard';

// Memoized edge card component
interface EdgeCardProps {
  edge: any;
  mappings: any[];
  t: (key: string, params?: any) => string;
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
                {String(t('project.schema.overview.auto'))}
              </span>
            )}
          </div>
          <p className="text-slate-500 dark:text-text-muted text-sm font-mono">
            {t('project.schema.overview.relationship_types.source_target')}
          </p>
        </div>
      </div>
      <button className="text-slate-400 dark:text-text-muted-light hover:text-slate-900 dark:hover:text-white transition-colors">
        <MoreVertical className="w-5 h-5" />
      </button>
    </div>
    <EdgeMappings edgeName={edge.name} mappings={mappings} t={t} />
    <EdgeAttributes edge={edge} t={t} />
  </div>
));
EdgeCard.displayName = 'EdgeCard';

// Memoized edge mappings component
interface EdgeMappingsProps {
  edgeName: string;
  mappings: any[];
  t: (key: string, params?: any) => string;
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
          {String(t('project.schema.overview.relationship_types.no_active_mappings'))}
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
                {String(t('project.schema.overview.auto'))}
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
  edge: any;
  t: (key: string, params?: any) => string;
}

const EdgeAttributes = memo(({ edge, t }: EdgeAttributesProps) => (
  <div className="flex flex-col gap-2">
    <p className="text-xs font-semibold text-slate-400 dark:text-text-muted-light uppercase tracking-wider">
      {String(t('project.schema.overview.relationship_types.edge_attributes'))}
    </p>
    <div className="flex flex-wrap gap-2">
      {Object.entries(edge.schema || {})
        .slice(0, 4)
        .map(([key, val]: [string, any]) => (
          <span
            key={key}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-slate-50 dark:bg-background-dark border border-slate-200 dark:border-surface-dark-alt text-xs font-mono text-slate-500 dark:text-text-muted"
          >
            {key}: {typeof val === 'string' ? val : val.type}
          </span>
        ))}
      {Object.keys(edge.schema || {}).length === 0 && (
        <span className="text-slate-400 dark:text-text-muted text-xs italic">
          {String(t('project.schema.overview.relationship_types.no_attributes'))}
        </span>
      )}
    </div>
  </div>
));
EdgeAttributes.displayName = 'EdgeAttributes';

export default function SchemaOverview() {
  const { projectId } = useParams<{ projectId: string }>();
  const { t } = useTranslation();
  const { projectBasePath } = useProjectBasePath();
  const { entities = [], edges = [], mappings = [], isLoading } = useSchemaData(projectId);

  if (isLoading) {
    return (
      <div className="p-8 text-center text-slate-500 dark:text-gray-500">{t('common.loading')}</div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-slate-50 dark:bg-background-dark text-slate-900 dark:text-white overflow-hidden">
      <div className="flex-1 overflow-y-auto p-8">
        <div className="max-w-[1600px] mx-auto flex flex-col gap-8">
          {/* Page Heading & Actions */}
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
            <div className="flex flex-col gap-2">
              <h2 className="text-slate-900 dark:text-white text-3xl font-bold tracking-tight">
                {t('project.schema.overview.title')}
              </h2>
              <p className="text-slate-500 dark:text-text-muted text-base max-w-2xl">
                {t('project.schema.overview.subtitle')}
              </p>
            </div>
            <div className="flex gap-3">
              <button className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-slate-200 dark:border-surface-dark-alt bg-white dark:bg-background-dark text-slate-700 dark:text-white text-sm font-semibold hover:bg-slate-50 dark:hover:bg-surface-dark-alt transition-colors shadow-sm">
                <Code className="w-5 h-5" />
                {t('project.schema.overview.view_json')}
              </button>
              <button className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-blue-600 dark:bg-primary text-white text-sm font-semibold hover:bg-blue-700 transition-colors shadow-lg shadow-blue-900/20">
                <Download className="w-5 h-5" />
                {t('project.schema.overview.export_schema')}
              </button>
            </div>
          </div>

          {/* Search & Filters */}
          <div className="w-full">
            <div className="relative group">
              <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                <Search className="text-slate-400 dark:text-text-muted group-focus-within:text-slate-600 dark:group-focus-within:text-white transition-colors w-5 h-5" />
              </div>
              <input
                className="w-full h-12 pl-12 pr-4 bg-white dark:bg-surface-dark-alt border border-slate-200 dark:border-transparent focus:border-blue-500 dark:focus:border-primary/50 focus:ring-0 rounded-xl text-slate-900 dark:text-white placeholder-slate-400 dark:placeholder-text-muted text-sm font-medium transition-[color,background-color,border-color,box-shadow,opacity,transform] outline-none shadow-sm"
                placeholder={t('project.schema.overview.search_placeholder')}
                type="text"
              />
              <div className="absolute inset-y-0 right-2 flex items-center">
                <button className="px-2 py-1 text-xs font-medium text-slate-500 dark:text-text-muted bg-slate-100 dark:bg-background-dark rounded border border-slate-200 dark:border-surface-dark-alt">
                  CMD + K
                </button>
              </div>
            </div>
          </div>

          {/* Main Grid */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
            {/* Entity Types Section */}
            <section className="flex flex-col gap-5">
              <div className="flex items-center justify-between pb-2 border-b border-slate-200 dark:border-surface-dark-alt">
                <div className="flex items-center gap-3">
                  <div className="size-8 rounded-lg bg-emerald-50 dark:bg-emerald-500/10 flex items-center justify-center border border-emerald-200 dark:border-emerald-500/20">
                    <Box className="text-emerald-600 dark:text-emerald-500 w-5 h-5" />
                  </div>
                  <h3 className="text-slate-900 dark:text-white text-lg font-bold">
                    {t('project.schema.overview.entity_types.title')}
                  </h3>
                  <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-surface-dark-alt text-slate-500 dark:text-text-muted text-xs font-mono">
                    {t('project.schema.overview.entity_types.defined', { count: entities.length })}
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
                {entities.map((entity) => (
                  <EntityCard key={entity.id} entity={entity} t={t} />
                ))}
                {entities.length === 0 && (
                  <div className="text-center p-8 text-slate-500 dark:text-text-muted bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-surface-dark-alt">
                    {t('project.schema.overview.entity_types.empty')}
                  </div>
                )}
              </div>
            </section>

            {/* Relationship Types Section */}
            <section className="flex flex-col gap-5">
              <div className="flex items-center justify-between pb-2 border-b border-slate-200 dark:border-surface-dark-alt">
                <div className="flex items-center gap-3">
                  <div className="size-8 rounded-lg bg-blue-50 dark:bg-primary/10 flex items-center justify-center border border-blue-200 dark:border-primary/20">
                    <Network className="text-blue-600 dark:text-primary w-5 h-5" />
                  </div>
                  <h3 className="text-slate-900 dark:text-white text-lg font-bold">
                    {t('project.schema.overview.relationship_types.title')}
                  </h3>
                  <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-surface-dark-alt text-slate-500 dark:text-text-muted text-xs font-mono">
                    {t('project.schema.overview.relationship_types.defined', {
                      count: edges.length,
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
                {edges.map((edge) => (
                  <EdgeCard key={edge.id} edge={edge} mappings={mappings} t={t} />
                ))}
                {edges.length === 0 && (
                  <div className="text-center p-8 text-slate-500 dark:text-text-muted bg-white dark:bg-surface-dark rounded-xl border border-slate-200 dark:border-surface-dark-alt">
                    {t('project.schema.overview.relationship_types.empty')}
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
