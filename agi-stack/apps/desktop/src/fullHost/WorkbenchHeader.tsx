import { useState } from 'react';
import { useI18n } from '../i18n';
import {
  headerItemActive,
  workbenchHeaderGroups,
} from './workbenchModel';
import type { WorkbenchHeaderSlot } from '../../../../packages/plugin-slots/src/workbenchHeader';

export function WorkbenchHeader({
  items,
  pathname,
  onNavigate,
}: {
  items: readonly WorkbenchHeaderSlot[];
  pathname: string;
  onNavigate(path: string): void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState<string | null>(null);
  const groups = workbenchHeaderGroups(items);
  if (!groups.length) return null;
  return (
    <nav className="desktop-workbench-header" aria-label={t('featureDirectory.title')}>
      {groups.map((group) => {
        const label = t(group.items[0]?.groupLabel ?? group.id);
        const expanded = open === group.id;
        const current = group.items.some((item) => headerItemActive(item, pathname));
        return (
          <div className="desktop-workbench-group" key={group.id}>
            <button
              type="button"
              aria-expanded={expanded}
              aria-current={current ? 'true' : undefined}
              onClick={() => setOpen((value) => (value === group.id ? null : group.id))}
            >
              {label}
            </button>
            {expanded ? (
              <div role="group" aria-label={label}>
                {group.items.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    aria-current={headerItemActive(item, pathname) ? 'page' : undefined}
                    onClick={() => {
                      setOpen(null);
                      onNavigate(item.path);
                    }}
                  >
                    {t(item.label)}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </nav>
  );
}
