import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import {
  GearIcon,
  GridIcon,
  ListBulletIcon,
  MagnifyingGlassIcon,
  ReloadIcon,
} from '@radix-ui/react-icons';

import type { DesktopApiClient } from '../../api/client';
import type {
  DesktopSearchMode,
  DesktopSearchRequest,
  DesktopSearchResponse,
} from '../../api/searchContract';
import { useI18n } from '../../i18n';
import type { DesktopCapabilityAvailability } from '../runtime/capabilitySnapshot';
import {
  commaSeparatedSearchValues,
  DESKTOP_SEARCH_PAGE_SIZE,
  desktopSearchRequestIsComplete,
  nextDesktopSearchLimit,
  searchResponseMayCommit,
  toggleSelectedSearchResult,
} from './desktopSearchModel';
import { SearchResultCard, SearchState } from './DesktopSearchResult';
import './DesktopSearch.css';

type DesktopSearchProps = {
  api: Pick<DesktopApiClient, 'searchProject'>;
  tenantId: string;
  projectId: string;
  projectName: string | null;
  capability: DesktopCapabilityAvailability;
  capabilityLoading: boolean;
  onRetryCapability?: () => void;
  onOpenProjectSettings?: () => void;
};

type SearchViewMode = 'grid' | 'list';

const SEARCH_MODES: DesktopSearchMode[] = [
  'semantic',
  'graphTraversal',
  'temporal',
  'faceted',
  'community',
];

const MODE_LABEL_KEYS: Record<DesktopSearchMode, string> = {
  semantic: 'search.mode.semantic',
  graphTraversal: 'search.mode.graphTraversal',
  temporal: 'search.mode.temporal',
  faceted: 'search.mode.faceted',
  community: 'search.mode.community',
};

export function DesktopSearch({
  api,
  tenantId,
  projectId,
  projectName,
  capability,
  capabilityLoading,
  onRetryCapability,
  onOpenProjectSettings,
}: DesktopSearchProps) {
  const { t } = useI18n();
  const [mode, setMode] = useState<DesktopSearchMode>('semantic');
  const [query, setQuery] = useState('');
  const [startEntityUuid, setStartEntityUuid] = useState('');
  const [communityUuid, setCommunityUuid] = useState('');
  const [strategy, setStrategy] = useState('COMBINED_HYBRID_SEARCH_RRF');
  const [reranker, setReranker] = useState('bge');
  const [focalNodeUuid, setFocalNodeUuid] = useState('');
  const [maxDepth, setMaxDepth] = useState(2);
  const [relationshipTypes, setRelationshipTypes] = useState('');
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [entityTypes, setEntityTypes] = useState('');
  const [tags, setTags] = useState('');
  const [includeEpisodes, setIncludeEpisodes] = useState(true);
  const [configOpen, setConfigOpen] = useState(false);
  const [viewMode, setViewMode] = useState<SearchViewMode>('grid');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [response, setResponse] = useState<DesktopSearchResponse | null>(null);
  const [executedLimit, setExecutedLimit] = useState(DESKTOP_SEARCH_PAGE_SIZE);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [copyNotice, setCopyNotice] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const generationRef = useRef(0);
  const scopeRef = useRef({ tenantId, projectId });
  const lastRequestRef = useRef<DesktopSearchRequest | null>(null);

  useEffect(() => {
    const controller = abortRef.current;
    scopeRef.current = { tenantId, projectId };
    generationRef.current += 1;
    controller?.abort();
    abortRef.current = null;
    lastRequestRef.current = null;
    setLoading(false);
    setError(null);
    setHasSearched(false);
    setResponse(null);
    setExecutedLimit(DESKTOP_SEARCH_PAGE_SIZE);
    setSelectedIds([]);
    setCopyNotice(null);
  }, [capability.available, projectId, tenantId]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      generationRef.current += 1;
    },
    [],
  );

  const primaryInput = useMemo(() => {
    if (mode === 'graphTraversal') {
      return {
        label: t('search.input.startEntity'),
        placeholder: t('search.input.startEntityPlaceholder'),
        value: startEntityUuid,
        onChange: setStartEntityUuid,
      };
    }
    if (mode === 'community') {
      return {
        label: t('search.input.community'),
        placeholder: t('search.input.communityPlaceholder'),
        value: communityUuid,
        onChange: setCommunityUuid,
      };
    }
    return {
      label: t('search.input.query'),
      placeholder: t('search.input.queryPlaceholder'),
      value: query,
      onChange: setQuery,
    };
  }, [communityUuid, mode, query, startEntityUuid, t]);

  const resetSearchPresentation = (nextMode: DesktopSearchMode) => {
    abortRef.current?.abort();
    generationRef.current += 1;
    abortRef.current = null;
    lastRequestRef.current = null;
    setMode(nextMode);
    setLoading(false);
    setError(null);
    setHasSearched(false);
    setResponse(null);
    setExecutedLimit(DESKTOP_SEARCH_PAGE_SIZE);
    setSelectedIds([]);
    setCopyNotice(null);
  };

  const buildRequest = (limit: number): DesktopSearchRequest => {
    switch (mode) {
      case 'semantic':
        return {
          mode,
          query,
          strategy,
          focalNodeUuid: focalNodeUuid || null,
          reranker: reranker || null,
          limit,
        };
      case 'graphTraversal':
        return {
          mode,
          startEntityUuid,
          maxDepth,
          relationshipTypes: commaSeparatedSearchValues(relationshipTypes),
          limit,
        };
      case 'temporal':
        return {
          mode,
          query,
          since: optionalSearchDate(since),
          until: optionalSearchDate(until),
          limit,
        };
      case 'faceted':
        return {
          mode,
          query,
          entityTypes: commaSeparatedSearchValues(entityTypes),
          tags: commaSeparatedSearchValues(tags),
          since: optionalSearchDate(since),
          limit,
          offset: 0,
        };
      case 'community':
        return {
          mode,
          communityUuid,
          includeEpisodes,
          limit,
        };
    }
  };

  const executeSearch = async (request: DesktopSearchRequest) => {
    if (!capability.available) return;
    if (!tenantId.trim() || !projectId.trim()) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    const expectedAuthority = { generation, tenantId, projectId };
    lastRequestRef.current = request;
    setLoading(true);
    setError(null);
    setCopyNotice(null);

    try {
      const nextResponse = await api.searchProject(request, {
        tenantId,
        projectId,
        signal: controller.signal,
      });
      if (
        !searchResponseMayCommit(expectedAuthority, {
          generation: generationRef.current,
          ...scopeRef.current,
        })
      ) {
        return;
      }
      setResponse(nextResponse);
      setExecutedLimit(request.limit);
      setHasSearched(true);
      setSelectedIds([]);
    } catch (searchError) {
      if (controller.signal.aborted || isAbortError(searchError)) return;
      if (
        !searchResponseMayCommit(expectedAuthority, {
          generation: generationRef.current,
          ...scopeRef.current,
        })
      ) {
        return;
      }
      setError(t('search.error.requestFailed'));
      setHasSearched(true);
    } finally {
      if (
        searchResponseMayCommit(expectedAuthority, {
          generation: generationRef.current,
          ...scopeRef.current,
        })
      ) {
        setLoading(false);
        abortRef.current = null;
      }
    }
  };

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    try {
      const request = buildRequest(DESKTOP_SEARCH_PAGE_SIZE);
      if (!desktopSearchRequestIsComplete(request)) {
        setError(t('search.error.invalidInput'));
        setHasSearched(false);
        return;
      }
      void executeSearch(request);
    } catch {
      setError(t('search.error.invalidInput'));
      setHasSearched(false);
    }
  };

  const retrySearch = () => {
    const request = lastRequestRef.current;
    if (request) void executeSearch(request);
  };

  const loadMore = () => {
    const request = lastRequestRef.current;
    const nextLimit = nextDesktopSearchLimit(executedLimit);
    if (!request || nextLimit === null) return;
    void executeSearch(withSearchLimit(request, nextLimit));
  };

  const copyResultId = async (resultId: string) => {
    try {
      await navigator.clipboard.writeText(resultId);
      setCopyNotice(t('search.copy.success'));
    } catch {
      setCopyNotice(t('search.copy.unavailable'));
    }
  };

  if (!projectId.trim()) {
    return (
      <section className="desktop-search desktop-search--missing-project">
        <div className="desktop-search__state-card">
          <MagnifyingGlassIcon width="28" height="28" aria-hidden="true" />
          <h1>{t('search.noProject.title')}</h1>
          <p>{t('search.noProject.description')}</p>
          {onOpenProjectSettings ? (
            <button type="button" onClick={onOpenProjectSettings}>
              <GearIcon aria-hidden="true" />
              {t('search.noProject.action')}
            </button>
          ) : null}
        </div>
      </section>
    );
  }

  if (capabilityLoading) {
    return (
      <section className="desktop-search" aria-label={t('search.capability.loading.title')}>
        <SearchState
          icon={<MagnifyingGlassIcon width="28" height="28" aria-hidden="true" />}
          title={t('search.capability.loading.title')}
          description={t('search.capability.loading.description')}
        />
      </section>
    );
  }

  if (!capability.available) {
    return (
      <section
        className="desktop-search"
        aria-label={t('search.capability.unavailable.title')}
        data-reason-code={capability.reason_code ?? 'capability_snapshot_unavailable'}
      >
        <SearchState
          icon={<MagnifyingGlassIcon width="28" height="28" aria-hidden="true" />}
          title={t('search.capability.unavailable.title')}
          description={t('search.capability.unavailable.description')}
        />
        {onRetryCapability ? (
          <button type="button" className="desktop-search__load-more" onClick={onRetryCapability}>
            <ReloadIcon aria-hidden="true" />
            {t('search.retry')}
          </button>
        ) : null}
      </section>
    );
  }

  const results = response?.results ?? [];
  const hasMore =
    nextDesktopSearchLimit(executedLimit) !== null &&
    (response?.total === undefined ||
      response.total > results.length ||
      results.length >= executedLimit);

  return (
    <section className="desktop-search" aria-labelledby="desktop-search-title">
      <header className="desktop-search__header">
        <div>
          <span className="desktop-search__eyebrow">{t('search.eyebrow')}</span>
          <h1 id="desktop-search-title">{t('search.title')}</h1>
          <p>
            {t('search.description', {
              project: projectName ?? projectId,
            })}
          </p>
        </div>
        <span className="desktop-search__scope">{projectName ?? projectId}</span>
      </header>

      <form className="desktop-search__form" onSubmit={submitSearch}>
        <div className="desktop-search__modes" aria-label={t('search.modes')}>
          {SEARCH_MODES.map((searchMode) => (
            <button
              key={searchMode}
              type="button"
              aria-pressed={mode === searchMode}
              className={mode === searchMode ? 'is-active' : ''}
              onClick={() => resetSearchPresentation(searchMode)}
            >
              {t(MODE_LABEL_KEYS[searchMode])}
            </button>
          ))}
        </div>

        <label className="desktop-search__query">
          <span>{primaryInput.label}</span>
          <span className="desktop-search__query-control">
            <MagnifyingGlassIcon aria-hidden="true" />
            <input
              value={primaryInput.value}
              onChange={(event) => primaryInput.onChange(event.target.value)}
              placeholder={primaryInput.placeholder}
              autoComplete="off"
            />
            <button type="submit" disabled={loading}>
              {loading ? t('search.searching') : t('search.submit')}
            </button>
          </span>
        </label>

        <button
          type="button"
          className="desktop-search__config-toggle"
          aria-expanded={configOpen}
          onClick={() => setConfigOpen((current) => !current)}
        >
          <GearIcon aria-hidden="true" />
          {configOpen ? t('search.config.hide') : t('search.config.show')}
        </button>

        {configOpen ? (
          <SearchConfiguration
            mode={mode}
            strategy={strategy}
            reranker={reranker}
            focalNodeUuid={focalNodeUuid}
            maxDepth={maxDepth}
            relationshipTypes={relationshipTypes}
            since={since}
            until={until}
            entityTypes={entityTypes}
            tags={tags}
            includeEpisodes={includeEpisodes}
            onStrategyChange={setStrategy}
            onRerankerChange={setReranker}
            onFocalNodeUuidChange={setFocalNodeUuid}
            onMaxDepthChange={setMaxDepth}
            onRelationshipTypesChange={setRelationshipTypes}
            onSinceChange={setSince}
            onUntilChange={setUntil}
            onEntityTypesChange={setEntityTypes}
            onTagsChange={setTags}
            onIncludeEpisodesChange={setIncludeEpisodes}
          />
        ) : null}
      </form>

      <div className="desktop-search__results-toolbar">
        <div>
          <strong>{t('search.results.title')}</strong>
          <span>
            {hasSearched
              ? t('search.results.count', { count: results.length })
              : t('search.results.notStarted')}
          </span>
        </div>
        <div className="desktop-search__view-switch" aria-label={t('search.view.label')}>
          <button
            type="button"
            aria-pressed={viewMode === 'grid'}
            aria-label={t('search.view.grid')}
            title={t('search.view.grid')}
            onClick={() => setViewMode('grid')}
          >
            <GridIcon aria-hidden="true" />
          </button>
          <button
            type="button"
            aria-pressed={viewMode === 'list'}
            aria-label={t('search.view.list')}
            title={t('search.view.list')}
            onClick={() => setViewMode('list')}
          >
            <ListBulletIcon aria-hidden="true" />
          </button>
        </div>
      </div>

      <div className="desktop-search__feedback" aria-live="polite">
        {loading ? (
          <div className="desktop-search__loading" role="status">
            <span />
            <span />
            <span />
            <p>{t('search.loading')}</p>
          </div>
        ) : null}
        {error ? (
          <div className="desktop-search__error" role="alert">
            <p>{error}</p>
            {lastRequestRef.current ? (
              <button type="button" onClick={retrySearch}>
                <ReloadIcon aria-hidden="true" />
                {t('search.retry')}
              </button>
            ) : null}
          </div>
        ) : null}
        {copyNotice ? <span className="desktop-search__copy-notice">{copyNotice}</span> : null}
      </div>

      {!loading && !error && !hasSearched ? (
        <SearchState
          icon={<MagnifyingGlassIcon width="24" height="24" aria-hidden="true" />}
          title={t('search.start.title')}
          description={t('search.start.description')}
        />
      ) : null}
      {!loading && !error && hasSearched && results.length === 0 ? (
        <SearchState
          icon={<MagnifyingGlassIcon width="24" height="24" aria-hidden="true" />}
          title={t('search.empty.title')}
          description={t('search.empty.description')}
        />
      ) : null}

      {!loading && results.length > 0 ? (
        <>
          <div
            className={`desktop-search__results desktop-search__results--${viewMode}`}
            aria-label={t('search.results.title')}
          >
            {results.map((result, index) => (
              <SearchResultCard
                key={result.id ?? `${result.type}-${index}`}
                result={result}
                selectionId={result.id ?? `${result.type}-${index}`}
                selected={selectedIds.includes(result.id ?? `${result.type}-${index}`)}
                onToggle={() =>
                  setSelectedIds((current) =>
                    toggleSelectedSearchResult(current, result.id ?? `${result.type}-${index}`),
                  )
                }
                onCopy={result.id ? () => void copyResultId(result.id!) : null}
              />
            ))}
          </div>
          {hasMore ? (
            <button type="button" className="desktop-search__load-more" onClick={loadMore}>
              {t('search.loadMore')}
            </button>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

type SearchConfigurationProps = {
  mode: DesktopSearchMode;
  strategy: string;
  reranker: string;
  focalNodeUuid: string;
  maxDepth: number;
  relationshipTypes: string;
  since: string;
  until: string;
  entityTypes: string;
  tags: string;
  includeEpisodes: boolean;
  onStrategyChange: (value: string) => void;
  onRerankerChange: (value: string) => void;
  onFocalNodeUuidChange: (value: string) => void;
  onMaxDepthChange: (value: number) => void;
  onRelationshipTypesChange: (value: string) => void;
  onSinceChange: (value: string) => void;
  onUntilChange: (value: string) => void;
  onEntityTypesChange: (value: string) => void;
  onTagsChange: (value: string) => void;
  onIncludeEpisodesChange: (value: boolean) => void;
};

function SearchConfiguration(props: SearchConfigurationProps) {
  const { t } = useI18n();
  if (props.mode === 'semantic') {
    return (
      <div className="desktop-search__config">
        <label>
          {t('search.config.strategy')}
          <select
            value={props.strategy}
            onChange={(event) => props.onStrategyChange(event.target.value)}
          >
            <option value="COMBINED_HYBRID_SEARCH_RRF">
              {t('search.config.strategy.combined')}
            </option>
            <option value="FULL_TEXT_SEARCH">{t('search.config.strategy.fullText')}</option>
            <option value="VECTOR_SEARCH">{t('search.config.strategy.vector')}</option>
          </select>
        </label>
        <label>
          {t('search.config.reranker')}
          <select
            value={props.reranker}
            onChange={(event) => props.onRerankerChange(event.target.value)}
          >
            <option value="bge">BGE</option>
            <option value="rrf">RRF</option>
            <option value="">{t('search.config.none')}</option>
          </select>
        </label>
        <SearchTextField
          label={t('search.config.focalNode')}
          value={props.focalNodeUuid}
          onChange={props.onFocalNodeUuidChange}
        />
      </div>
    );
  }
  if (props.mode === 'graphTraversal') {
    return (
      <div className="desktop-search__config">
        <label>
          {t('search.config.maxDepth')}
          <input
            type="number"
            min="1"
            max="5"
            value={props.maxDepth}
            onChange={(event) => props.onMaxDepthChange(Number(event.target.value))}
          />
        </label>
        <SearchTextField
          label={t('search.config.relationshipTypes')}
          value={props.relationshipTypes}
          onChange={props.onRelationshipTypesChange}
        />
      </div>
    );
  }
  if (props.mode === 'temporal') {
    return (
      <div className="desktop-search__config">
        <SearchDateField
          label={t('search.config.since')}
          value={props.since}
          onChange={props.onSinceChange}
        />
        <SearchDateField
          label={t('search.config.until')}
          value={props.until}
          onChange={props.onUntilChange}
        />
      </div>
    );
  }
  if (props.mode === 'faceted') {
    return (
      <div className="desktop-search__config">
        <SearchTextField
          label={t('search.config.entityTypes')}
          value={props.entityTypes}
          onChange={props.onEntityTypesChange}
        />
        <SearchTextField
          label={t('search.config.tags')}
          value={props.tags}
          onChange={props.onTagsChange}
        />
        <SearchDateField
          label={t('search.config.since')}
          value={props.since}
          onChange={props.onSinceChange}
        />
      </div>
    );
  }
  return (
    <div className="desktop-search__config">
      <label className="desktop-search__checkbox">
        <input
          type="checkbox"
          checked={props.includeEpisodes}
          onChange={(event) => props.onIncludeEpisodesChange(event.target.checked)}
        />
        {t('search.config.includeEpisodes')}
      </label>
    </div>
  );
}

function SearchTextField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      {label}
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function SearchDateField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      {label}
      <input
        type="datetime-local"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function optionalSearchDate(value: string): string | null {
  if (!value.trim()) return null;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) throw new Error('Invalid search date');
  return new Date(timestamp).toISOString();
}

function withSearchLimit(request: DesktopSearchRequest, limit: number): DesktopSearchRequest {
  return { ...request, limit };
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}
