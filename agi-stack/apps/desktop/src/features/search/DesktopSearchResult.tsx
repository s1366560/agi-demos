import type { ReactNode } from 'react';
import { CheckIcon, ClipboardCopyIcon } from '@radix-ui/react-icons';

import type { DesktopSearchResult } from '../../api/searchContract';
import { useI18n } from '../../i18n';

export function SearchState({
  icon,
  title,
  description,
}: {
  icon: ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="desktop-search__state-card">
      {icon}
      <h2>{title}</h2>
      <p>{description}</p>
    </div>
  );
}

export function SearchResultCard({
  result,
  selectionId,
  selected,
  onToggle,
  onCopy,
}: {
  result: DesktopSearchResult;
  selectionId: string;
  selected: boolean;
  onToggle: () => void;
  onCopy: (() => void) | null;
}) {
  const { t } = useI18n();
  return (
    <article className={`desktop-search__result ${selected ? 'is-selected' : ''}`}>
      <button
        type="button"
        className="desktop-search__select"
        aria-pressed={selected}
        aria-label={t('search.result.select', {
          title: result.title ?? selectionId,
        })}
        onClick={onToggle}
      >
        {selected ? <CheckIcon aria-hidden="true" /> : null}
      </button>
      <div className="desktop-search__result-meta">
        <span>{result.type}</span>
        {result.source ? <span>{result.source}</span> : null}
        {result.score !== null ? <span>{Math.round(result.score * 100)}%</span> : null}
      </div>
      <h2>{result.title ?? t('search.result.untitled')}</h2>
      <p>{result.content}</p>
      {result.tags.length > 0 ? (
        <div className="desktop-search__tags">
          {result.tags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
      ) : null}
      <footer>
        {result.createdAt ? (
          <time dateTime={result.createdAt}>{formatSearchDate(result.createdAt)}</time>
        ) : (
          <span />
        )}
        {onCopy ? (
          <button type="button" onClick={onCopy}>
            <ClipboardCopyIcon aria-hidden="true" />
            {t('search.result.copyId')}
          </button>
        ) : null}
      </footer>
    </article>
  );
}

function formatSearchDate(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(timestamp);
}
