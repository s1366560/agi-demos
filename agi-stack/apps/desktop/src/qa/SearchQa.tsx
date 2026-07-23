import '@radix-ui/themes/styles.css';
import { useMemo, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';

import type {
  DesktopSearchRequest,
  DesktopSearchResponse,
  DesktopSearchType,
} from '../api/searchContract';
import { DesktopSearch } from '../features/search/DesktopSearch';
import { I18nProvider } from '../i18n';
import '../styles.css';
import './searchQa.css';

declare global {
  var __searchQaRoot: Root | undefined;
}

type SearchQaState = 'populated' | 'empty' | 'error' | 'no-project';

const SEARCH_TYPES: Record<DesktopSearchRequest['mode'], DesktopSearchType> = {
  semantic: 'advanced',
  graphTraversal: 'graph_traversal',
  temporal: 'temporal',
  faceted: 'faceted',
  community: 'community',
};

function SearchQa() {
  const [state, setState] = useState<SearchQaState>('populated');
  const api = useMemo(
    () => ({
      async searchProject(request: DesktopSearchRequest): Promise<DesktopSearchResponse> {
        document.documentElement.dataset.qaSearchRequest = JSON.stringify(request);
        if (state === 'error') throw new Error('QA search failure');
        const resultCount = state === 'empty' ? 0 : Math.min(6, request.limit);
        return {
          results: Array.from({ length: resultCount }, (_, index) => ({
            id: `${request.mode}-result-${index + 1}`,
            title: `${request.mode} result ${index + 1}`,
            content:
              'Authoritative project evidence with source context, searchable metadata, and a stable result identity.',
            score: 0.96 - index * 0.05,
            source: index % 2 === 0 ? 'Knowledge Graph' : 'Memory',
            type: index % 2 === 0 ? 'Concept' : 'Episode',
            createdAt: `2026-07-${String(20 - index).padStart(2, '0')}T10:00:00Z`,
            tags: ['verified', request.mode],
          })),
          total: state === 'empty' ? 0 : 75,
          searchType: SEARCH_TYPES[request.mode],
          limit: request.limit,
          offset: request.mode === 'faceted' ? request.offset : null,
          facets:
            request.mode === 'faceted'
              ? { entityTypes: { Concept: resultCount }, total: resultCount }
              : null,
        };
      },
    }),
    [state],
  );

  return (
    <Theme appearance="dark" accentColor="cyan" grayColor="slate" radius="medium" scaling="95%">
      <div className="search-qa-shell">
        <nav aria-label="Search QA states">
          {(['populated', 'empty', 'error', 'no-project'] as SearchQaState[]).map((nextState) => (
            <button
              type="button"
              className={state === nextState ? 'selected' : ''}
              onClick={() => setState(nextState)}
              key={nextState}
            >
              {nextState}
            </button>
          ))}
        </nav>
        <DesktopSearch
          key={state}
          api={api}
          tenantId="tenant-search-qa"
          projectId={state === 'no-project' ? '' : 'project-search-qa'}
          projectName={state === 'no-project' ? null : 'Desktop Search QA'}
          onOpenProjectSettings={() => {
            document.documentElement.dataset.qaSettingsOpened = 'true';
          }}
        />
      </div>
    </Theme>
  );
}

const container = document.getElementById('root');
if (!container) throw new Error('Missing root element');
globalThis.__searchQaRoot ??= createRoot(container);
globalThis.__searchQaRoot.render(
  <I18nProvider>
    <SearchQa />
  </I18nProvider>,
);
