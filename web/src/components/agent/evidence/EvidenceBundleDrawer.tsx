import React, { useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { formatTimeOnly } from '@/utils/date';

import { LazyDrawer, LazyEmpty, LazyTabs } from '@/components/ui/lazyAntd';

import { buildEvidenceBundle, EVIDENCE_TAB_ORDER, type EvidenceTab } from './evidenceBundle';

import type { Artifact } from '@/types/agent/config';

import type { TFunction } from 'i18next';

const TAB_LABEL_KEYS: Record<EvidenceTab, { key: string; fallback: string }> = {
  testRuns: { key: 'agent.evidence.tabs.testRuns', fallback: 'Test runs' },
  diffs: { key: 'agent.evidence.tabs.diffs', fallback: 'Diffs' },
  screenshots: { key: 'agent.evidence.tabs.screenshots', fallback: 'Screenshots' },
  logs: { key: 'agent.evidence.tabs.logs', fallback: 'Logs' },
};

function getTabLabel(tab: EvidenceTab, t: TFunction): string {
  const entry = TAB_LABEL_KEYS[tab];
  return t(entry.key, { defaultValue: entry.fallback });
}

export interface EvidenceBundleDrawerProps {
  open: boolean;
  onClose: () => void;
  artifacts: readonly Artifact[];
  /** Drawer width in px. Defaults to 520. */
  width?: number;
  title?: string;
}

interface ItemRowProps {
  artifact: Artifact;
}

const ItemRow: React.FC<ItemRowProps> = ({ artifact }) => {
  const sizeKb = (artifact.sizeBytes / 1024).toFixed(1);
  const content = (
    <>
      <div className="flex-1 min-w-0">
        <div className="text-[13px] font-medium text-slate-900 dark:text-slate-100 truncate">
          {artifact.filename}
        </div>
        <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">
          {artifact.mimeType} · {sizeKb} KB
          {artifact.sourceTool ? ` · ${artifact.sourceTool}` : ''}
        </div>
      </div>
      <span className="text-[11px] text-slate-400 dark:text-slate-500 shrink-0">
        {formatTimeOnly(artifact.createdAt)}
      </span>
    </>
  );
  const rowClassName =
    'flex items-start gap-3 rounded-md border border-transparent px-3 py-2 hover:border-slate-200 hover:bg-slate-50 dark:hover:border-slate-700 dark:hover:bg-slate-800/60';

  if (!artifact.url) {
    return <div className={rowClassName}>{content}</div>;
  }

  return (
    <a href={artifact.url} target="_blank" rel="noreferrer" className={rowClassName}>
      {content}
    </a>
  );
};

const TabPanel: React.FC<{ items: readonly Artifact[] }> = ({ items }) => {
  const { t } = useTranslation();
  if (items.length === 0) {
    return (
      <LazyEmpty
        description={t('agent.evidence.emptyBucket', {
          defaultValue: 'No evidence in this bucket yet.',
        })}
      />
    );
  }
  return (
    <div className="flex flex-col gap-1 py-1">
      {items.map((a) => (
        <ItemRow key={a.id} artifact={a} />
      ))}
    </div>
  );
};

/**
 * A right-side drawer presenting the conversation's evidence bundle, sliced
 * into 4 tabs. Stateless: the parent owns visibility and the artifact source.
 */
export const EvidenceBundleDrawer: React.FC<EvidenceBundleDrawerProps> = ({
  open,
  onClose,
  artifacts,
  width = 520,
  title,
}) => {
  const { t } = useTranslation();
  const bundle = useMemo(() => buildEvidenceBundle(artifacts), [artifacts]);
  const initialTab: EvidenceTab = useMemo(() => {
    return EVIDENCE_TAB_ORDER.find((tab) => bundle[tab].length > 0) ?? 'testRuns';
  }, [bundle]);
  const [activeKey, setActiveKey] = useState<EvidenceTab>(initialTab);
  const visibleActiveKey = bundle[activeKey].length > 0 ? activeKey : initialTab;

  const drawerTitle = title ?? t('agent.evidence.bundleTitle', { defaultValue: 'Evidence bundle' });

  const items = EVIDENCE_TAB_ORDER.map((tab) => ({
    key: tab,
    label: `${getTabLabel(tab, t)} (${bundle[tab].length.toString()})`,
    children: <TabPanel items={bundle[tab]} />,
  }));

  return (
    <LazyDrawer
      title={`${drawerTitle} · ${bundle.total.toString()}`}
      open={open}
      onClose={onClose}
      size={width}
      destroyOnHidden
      placement="right"
    >
      <LazyTabs
        activeKey={visibleActiveKey}
        onChange={(key: string) => {
          setActiveKey(key as EvidenceTab);
        }}
        items={items}
      />
    </LazyDrawer>
  );
};

export default EvidenceBundleDrawer;
