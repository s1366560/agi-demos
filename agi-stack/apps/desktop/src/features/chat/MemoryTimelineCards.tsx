import { useMemo, useState } from 'react';
import {
  ArchiveIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CopyIcon,
  MagnifyingGlassIcon,
  StarFilledIcon,
  StarIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type { AgentTimelineItem } from '../../types';
import {
  memoryCapturePresentation,
  memoryPinStorageKey,
  memoryRecallPresentation,
  parseMemoryPinState,
  serializeMemoryPinState,
} from './memoryTimelineModel';
import type { MemoryRecallHit, MemoryRecallPresentation } from './memoryTimelineModel';

const MEMORY_SNIPPET_LIMIT = 220;

export function MemoryTimelineEvent({
  item,
  conversationId,
}: {
  item: AgentTimelineItem;
  conversationId: string | null;
}) {
  const { t } = useI18n();
  const recall = useMemo(() => memoryRecallPresentation(item), [item]);
  const capture = useMemo(() => memoryCapturePresentation(item), [item]);
  if (recall) {
    return (
      <MemoryRecallCard
        item={item}
        conversationId={conversationId}
        presentation={recall}
      />
    );
  }
  if (capture) {
    return (
      <article
        className="memory-captured-card"
        data-timeline-anchor-id={item.id}
        data-timeline-anchor-members={JSON.stringify([item.id])}
      >
        <ArchiveIcon aria-hidden="true" />
        <strong>{t('chat.memoryCapturedCount', { count: capture.count })}</strong>
        {capture.categories.length > 0 ? <span>{capture.categories.join(' · ')}</span> : null}
      </article>
    );
  }
  return null;
}

function MemoryRecallCard({
  item,
  conversationId,
  presentation,
}: {
  item: AgentTimelineItem;
  conversationId: string | null;
  presentation: MemoryRecallPresentation;
}) {
  const { t } = useI18n();
  const storageKey = memoryPinStorageKey(conversationId);
  const [expanded, setExpanded] = useState(false);
  const [activeSource, setActiveSource] = useState<string | null>(null);
  const [expandedMemories, setExpandedMemories] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const [pinnedMemories, setPinnedMemories] = useState<ReadonlySet<string>>(() =>
    readMemoryPins(storageKey),
  );
  const visibleMemories = useMemo(() => {
    const filtered = activeSource
      ? presentation.memories.filter((memory) => memory.source === activeSource)
      : presentation.memories;
    return [...filtered].sort((left, right) => {
      const leftPinned = pinnedMemories.has(left.key);
      const rightPinned = pinnedMemories.has(right.key);
      if (leftPinned !== rightPinned) return leftPinned ? -1 : 1;
      return (right.score ?? Number.NEGATIVE_INFINITY) -
        (left.score ?? Number.NEGATIVE_INFINITY) || left.originalIndex - right.originalIndex;
    });
  }, [activeSource, pinnedMemories, presentation.memories]);
  const pinnedCount = presentation.memories.filter((memory) =>
    pinnedMemories.has(memory.key),
  ).length;

  const togglePin = (memoryKey: string) => {
    const next = new Set(pinnedMemories);
    if (next.has(memoryKey)) next.delete(memoryKey);
    else next.add(memoryKey);
    setPinnedMemories(next);
    writeMemoryPins(storageKey, next);
  };
  const toggleMemory = (memoryKey: string) => {
    setExpandedMemories((current) => {
      const next = new Set(current);
      if (next.has(memoryKey)) next.delete(memoryKey);
      else next.add(memoryKey);
      return next;
    });
  };

  return (
    <article
      className="memory-recall-card"
      data-timeline-anchor-id={item.id}
      data-timeline-anchor-members={JSON.stringify([item.id])}
    >
      <button
        type="button"
        className="memory-recall-header"
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
      >
        <span className="memory-recall-chevron" aria-hidden="true">
          {expanded ? <ChevronDownIcon /> : <ChevronRightIcon />}
        </span>
        <span className="memory-recall-icon" aria-hidden="true">
          <MagnifyingGlassIcon />
        </span>
        <span className="memory-recall-title">
          <strong>{t('chat.memoryRecalledCount', { count: presentation.count })}</strong>
          <small>{t('chat.memoryRecallEvidence')}</small>
        </span>
        <span className="memory-recall-meta">
          {presentation.searchMs !== null ? (
            <span>{t('chat.memorySearchDuration', { duration: presentation.searchMs })}</span>
          ) : null}
          {pinnedCount > 0 ? (
            <span className="memory-pinned-count">
              <StarFilledIcon aria-hidden="true" />
              {t('chat.memoryPinnedCount', { count: pinnedCount })}
            </span>
          ) : null}
        </span>
      </button>
      {expanded ? (
        <div className="memory-recall-body">
          {presentation.sources.length > 1 ? (
            <div className="memory-source-filters" aria-label={t('chat.memorySourceFilter')}>
              <MemorySourceChip
                label={t('chat.memoryAllSources')}
                count={presentation.memories.length}
                active={activeSource === null}
                onClick={() => setActiveSource(null)}
              />
              {presentation.sources.map(({ source, count }) => (
                <MemorySourceChip
                  key={source}
                  label={source}
                  count={count}
                  active={activeSource === source}
                  onClick={() => setActiveSource((current) => (current === source ? null : source))}
                />
              ))}
            </div>
          ) : null}
          <ul className="memory-hit-list">
            {visibleMemories.map((memory) => (
              <MemoryHit
                key={memory.key}
                memory={memory}
                expanded={expandedMemories.has(memory.key)}
                pinned={pinnedMemories.has(memory.key)}
                onToggle={() => toggleMemory(memory.key)}
                onTogglePin={() => togglePin(memory.key)}
              />
            ))}
          </ul>
        </div>
      ) : null}
    </article>
  );
}

function MemoryHit({
  memory,
  expanded,
  pinned,
  onToggle,
  onTogglePin,
}: {
  memory: MemoryRecallHit;
  expanded: boolean;
  pinned: boolean;
  onToggle: () => void;
  onTogglePin: () => void;
}) {
  const { t } = useI18n();
  const truncated = memory.content.length > MEMORY_SNIPPET_LIMIT;
  const displayContent =
    expanded || !truncated
      ? memory.content
      : `${memory.content.slice(0, MEMORY_SNIPPET_LIMIT)}…`;
  const source = memory.source || t('chat.memoryUnknownSource');
  const category = memory.category || t('chat.memoryUnknownCategory');
  const copyMemory = () => {
    if (navigator.clipboard?.writeText) void navigator.clipboard.writeText(memory.content);
  };
  return (
    <li className={`memory-hit${pinned ? ' is-pinned' : ''}`}>
      <div className="memory-hit-meta">
        {memory.score !== null ? (
          <span title={t('chat.memoryScore', { score: memory.score.toFixed(2) })}>
            {memory.score.toFixed(2)}
          </span>
        ) : null}
        <span>{category}</span>
        <small>{t('chat.memoryViaSource', { source })}</small>
        <span className="memory-hit-actions">
          <button
            type="button"
            aria-label={t(pinned ? 'chat.unpinMemory' : 'chat.pinMemory')}
            title={t(pinned ? 'chat.unpinMemory' : 'chat.pinMemory')}
            onClick={onTogglePin}
          >
            {pinned ? <StarFilledIcon /> : <StarIcon />}
          </button>
          <button
            type="button"
            aria-label={t('chat.copyMemory')}
            title={t('chat.copyMemory')}
            onClick={copyMemory}
          >
            <CopyIcon />
          </button>
        </span>
      </div>
      <p>{displayContent}</p>
      {truncated ? (
        <button type="button" className="memory-hit-expand" onClick={onToggle}>
          {t(expanded ? 'chat.showLess' : 'chat.showFull')}
        </button>
      ) : null}
    </li>
  );
}

function MemorySourceChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={active ? 'is-active' : undefined}
      aria-pressed={active}
      onClick={onClick}
    >
      <span>{label}</span>
      <em>{count}</em>
    </button>
  );
}

function readMemoryPins(storageKey: string): Set<string> {
  try {
    return parseMemoryPinState(window.localStorage.getItem(storageKey));
  } catch {
    return new Set();
  }
}

function writeMemoryPins(storageKey: string, pinned: ReadonlySet<string>): void {
  try {
    window.localStorage.setItem(storageKey, serializeMemoryPinState(pinned));
  } catch {
    // The inspection card remains usable when the WebView denies local storage.
  }
}
