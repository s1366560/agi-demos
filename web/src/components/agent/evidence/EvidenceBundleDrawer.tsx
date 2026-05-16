import React, { useMemo, useState } from 'react';

import { LazyDrawer, LazyEmpty, LazyTabs } from '@/components/ui/lazyAntd';

import { buildEvidenceBundle, EVIDENCE_TAB_ORDER, type EvidenceTab } from './evidenceBundle';

import type { Artifact } from '@/types/agent/config';

const TAB_LABEL: Record<EvidenceTab, string> = {
  testRuns: 'Test runs',
  diffs: 'Diffs',
  screenshots: 'Screenshots',
  logs: 'Logs',
};

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
  return (
    <a
      href={artifact.url ?? '#'}
      target={artifact.url ? '_blank' : undefined}
      rel="noreferrer"
      className="flex items-start gap-3 rounded-md px-3 py-2 hover:bg-[#fafafa] dark:hover:bg-slate-800/60 border border-transparent hover:border-[rgba(0,0,0,0.08)] dark:hover:border-slate-700"
    >
      <div className="flex-1 min-w-0">
        <div className="text-[13px] font-medium text-[#171717] dark:text-slate-100 truncate">
          {artifact.filename}
        </div>
        <div className="text-[11px] text-[#666] dark:text-slate-400 truncate">
          {artifact.mimeType} · {sizeKb} KB
          {artifact.sourceTool ? ` · ${artifact.sourceTool}` : ''}
        </div>
      </div>
      <span className="text-[11px] text-[#999] dark:text-slate-500 shrink-0">
        {new Date(artifact.createdAt).toLocaleTimeString()}
      </span>
    </a>
  );
};

const TabPanel: React.FC<{ items: readonly Artifact[] }> = ({ items }) => {
  if (items.length === 0) {
    return <LazyEmpty description="No evidence in this bucket yet." />;
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
  title = 'Evidence bundle',
}) => {
  const bundle = useMemo(() => buildEvidenceBundle(artifacts), [artifacts]);
  const initialTab: EvidenceTab = useMemo(() => {
    return EVIDENCE_TAB_ORDER.find((t) => bundle[t].length > 0) ?? 'testRuns';
  }, [bundle]);
  const [activeKey, setActiveKey] = useState<EvidenceTab>(initialTab);

  const items = EVIDENCE_TAB_ORDER.map((tab) => ({
    key: tab,
    label: `${TAB_LABEL[tab]} (${bundle[tab].length.toString()})`,
    children: <TabPanel items={bundle[tab]} />,
  }));

  return (
    <LazyDrawer
      title={`${title} · ${bundle.total.toString()}`}
      open={open}
      onClose={onClose}
      size={width}
      destroyOnHidden
      placement="right"
    >
      <LazyTabs
        activeKey={activeKey}
        onChange={(key: string) => {
          setActiveKey(key as EvidenceTab);
        }}
        items={items}
      />
    </LazyDrawer>
  );
};

export default EvidenceBundleDrawer;
