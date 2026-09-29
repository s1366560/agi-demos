import { timelineToolResultFailed } from '../chat/toolResultStatus';
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Cross2Icon } from '@radix-ui/react-icons';
import { useI18n } from '../../i18n';
import type { AgentTimelineItem } from '../../types';
import {
  buildTimelineStepDetails,
  serializeTimelineDetail,
  serializeRawTimelineDetail,
} from './timelineStepDetailsModel';
import { PlatformPluginToolResultSlots } from '../chat/PlatformPluginToolResultSlots';
import {
  ToolFileMetadataView,
  timelineFileMetadata,
  timelineSummary,
  timelineKind,
  timelineTitle,
} from '../chat/chatTimelinePresentation';
import { toolCallPresentationKind } from '../chat/chatTimelineModel';
import './TimelineStepDetails.css';

const tabs = ['overview', 'input', 'output', 'diagnostics'] as const;
type DetailTab = (typeof tabs)[number];

export function TimelineStepDetails({
  items,
  onClose,
  onOpenFile,
  showCloseButton = true,
}: {
  items: readonly AgentTimelineItem[];
  onClose: () => void;
  showCloseButton?: boolean;
  onOpenFile?: (path: string) => void;
}) {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<DetailTab>('overview');
  const [copyState, setCopyState] = useState<'copied' | 'copyFailed' | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const tabsRef = useRef<HTMLDivElement>(null);
  const model = useMemo(() => buildTimelineStepDetails(items), [items]);
  const resultItem = [...items]
    .reverse()
    .find((item) => item.type === 'observe' || item.type === 'tool_result');
  const fileMetadata = [...items].reverse().map(timelineFileMetadata).find(Boolean);
  const statusLabels: Record<string, string> = {
    running: 'session.toolStatus.running',
    executing: 'session.toolStatus.running',
    complete: 'session.toolStatus.complete',
    completed: 'session.toolStatus.complete',
    failed: 'session.toolStatus.failed',
    error: 'session.toolStatus.failed',
  };
  const identity = items[0]?.id;
  useEffect(() => {
    setActiveTab('overview');
    setCopyState(null);
    headingRef.current?.focus();
  }, [identity]);

  const copy = async (value: unknown, raw = false) => {
    try {
      await navigator.clipboard.writeText(
        raw ? serializeRawTimelineDetail(value) : serializeTimelineDetail(value),
      );
      setCopyState('copied');
    } catch {
      setCopyState('copyFailed');
    }
  };
  const handleTabKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next: number;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    setActiveTab(tabs[next]);
    tabsRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus();
  };
  const latest = items.at(-1);
  const overviewSummary =
    model.status === 'failed' && latest
      ? timelineSummary({ ...latest, isError: true }, timelineKind(latest), t)
      : (model.summary ?? t('timelineDetails.noSummary'));
  const payloads = activeTab === 'input' ? model.input : model.output;

  return (
    <section
      className="timeline-step-details"
      aria-label={t('timelineDetails.title')}
      onKeyDown={(event) => {
        if (event.key === 'Escape' && !event.defaultPrevented) {
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }
      }}
    >
      <header>
        <h2 ref={headingRef} tabIndex={-1}>
          {model.title ?? (latest ? timelineTitle(latest, t) : t('timelineDetails.title'))}
        </h2>
        {showCloseButton ? <button
          type="button"
          onClick={onClose}
          aria-label={t('common.close')}
          title={t('common.close')}
        >
          <Cross2Icon aria-hidden="true" />
        </button> : null}
      </header>
      <div
        ref={tabsRef}
        className="timeline-step-detail-tabs"
        role="tablist"
        aria-label={t('timelineDetails.title')}
      >
        {tabs.map((tab, index) => (
          <button
            key={tab}
            type="button"
            role="tab"
            id={`timeline-detail-tab-${tab}`}
            aria-selected={activeTab === tab}
            aria-controls="timeline-detail-panel"
            tabIndex={activeTab === tab ? 0 : -1}
            onKeyDown={(event) => handleTabKey(event, index)}
            onClick={() => setActiveTab(tab)}
          >
            {t(`timelineDetails.${tab}`)}
          </button>
        ))}
      </div>
      <div
        className="timeline-step-detail-content"
        role="tabpanel"
        id="timeline-detail-panel"
        aria-labelledby={`timeline-detail-tab-${activeTab}`}
        tabIndex={0}
      >
        {activeTab === 'overview' ? (
          <>
            {model.status ? (
              <p className="timeline-step-detail-status">
                {t(statusLabels[model.status] ?? 'timelineDetails.recorded')}
              </p>
            ) : null}
            <p>{overviewSummary}</p>
            {model.files.length ? (
              <ul className="timeline-step-detail-files">
                {model.files.map((path) => (
                  <li key={path}>
                    <code>{path}</code>
                    {onOpenFile ? (
                      <button type="button" onClick={() => onOpenFile(path)}>
                        {t('timelineDetails.openFile')}
                      </button>
                    ) : null}
                    <button type="button" onClick={() => void copy(path, true)}>
                      {t('timelineDetails.copyPath')}
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : activeTab === 'diagnostics' ? (
          <>
            {model.diagnostics.length ? (
              <dl className="timeline-step-detail-diagnostics">
                {model.diagnostics.map(({ key, value }) => (
                  <div key={key}>
                    <dt>{t(`timelineDetails.field.${key}`)}</dt>
                    <dd>
                      <pre>{serializeTimelineDetail(value)}</pre>
                    </dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p>{t('timelineDetails.noDiagnostics')}</p>
            )}
            <details className="timeline-step-raw-events">
              <summary>{t('timelineDetails.rawEvents')}</summary>
              <button type="button" onClick={() => void copy(model.events, true)}>
                {t('timelineDetails.copy')}
              </button>
              <pre>{serializeRawTimelineDetail(model.events)}</pre>
            </details>
          </>
        ) : (
          <>
            {activeTab === 'output' && fileMetadata ? (
              <ToolFileMetadataView metadata={fileMetadata} />
            ) : null}
            {activeTab === 'output' && resultItem ? (
              <PlatformPluginToolResultSlots
                resultId={resultItem.id}
                toolName={resultItem.toolName ?? items[0]?.toolName ?? ''}
                status={timelineToolResultFailed(resultItem) ? 'failed' : 'complete'}
                kind={toolCallPresentationKind({
                  call: items[0],
                  result: resultItem,
                })}
              />
            ) : null}
            {payloads.length ? (
              <>
                <button
                  type="button"
                  onClick={() => void copy(payloads.length === 1 ? payloads[0] : payloads)}
                >
                  {t('timelineDetails.copy')}
                </button>
                {payloads.map((value, index) => (
                  <pre key={index}>{serializeTimelineDetail(value)}</pre>
                ))}
              </>
            ) : (
              <p>{t('timelineDetails.noData')}</p>
            )}
          </>
        )}
      </div>
      {copyState ? (
        <p className="timeline-step-copy-status" role="status">
          {t(`timelineDetails.${copyState}`)}
        </p>
      ) : null}
    </section>
  );
}
