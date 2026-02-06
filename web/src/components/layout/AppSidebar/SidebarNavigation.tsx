/**
 * SidebarNavigation Component
 *
 * Navigation section with collapsible groups and navigation items.
 */

import { ChevronDown } from 'lucide-react';

import { useSidebarContext } from './SidebarContext';
import { SidebarNavItem } from './SidebarNavItem';

import type { SidebarConfig } from '@/config/navigation';

export interface SidebarNavigationProps {
  /** Navigation configuration */
  config: SidebarConfig;
}

/**
 * Render a collapsible navigation group
 */
function NavGroupSection({
  group,
  isOpen,
  onToggle,
}: {
  group: { id: string; title: string; items: any[]; collapsible?: boolean; defaultOpen?: boolean };
  isOpen: boolean;
  onToggle?: () => void;
}) {
  const { isCollapsed, basePath, t } = useSidebarContext();

  if (isCollapsed) {
    return (
      <div className="space-y-1">
        {group.items.map((item) => (
          <SidebarNavItem
            key={item.id}
            item={item}
            collapsed={isCollapsed}
            basePath={basePath}
            t={t}
          />
        ))}
      </div>
    );
  }

  // Non-collapsible group
  if (group.collapsible === false) {
    return (
      <div className="space-y-1">
        {group.title && !isCollapsed && (
          <p className="px-3 text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
            {t(group.title)}
          </p>
        )}
        <div className="space-y-1">
          {group.items.map((item) => (
            <SidebarNavItem
              key={item.id}
              item={item}
              collapsed={isCollapsed}
              basePath={basePath}
              t={t}
            />
          ))}
        </div>
      </div>
    );
  }

  // Collapsible group
  return (
    <div className="space-y-1">
      {/* Group header with collapse toggle */}
      {group.title && !isCollapsed && (
        <button
          onClick={onToggle}
          className="flex items-center justify-between w-full px-3 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
          type="button"
        >
          <span>{t(group.title)}</span>
          <ChevronDown className={`w-3 h-3 transition-transform ${isOpen ? '' : '-rotate-90'}`} />
        </button>
      )}

      {/* Group items */}
      {(!isCollapsed || isOpen) && (
        <div className="space-y-1">
          {group.items.map((item) => (
            <SidebarNavItem
              key={item.id}
              item={item}
              collapsed={isCollapsed}
              basePath={basePath}
              t={t}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * SidebarNavigation component - renders navigation groups
 */
export function SidebarNavigation({ config }: SidebarNavigationProps) {
  const { isCollapsed, openGroups, onGroupToggle, basePath, t } = useSidebarContext();

  return (
    <nav
      data-testid="sidebar-navigation"
      data-path={basePath}
      className="flex-1 overflow-y-auto custom-scrollbar px-3 py-4 space-y-4 shrink-0"
    >
      {config.groups.map((group) => (
        <NavGroupSection
          key={group.id}
          group={group}
          isOpen={openGroups[group.id] ?? group.defaultOpen ?? true}
          onToggle={() => onGroupToggle(group.id)}
        />
      ))}

      {/* Bottom Section */}
      {config.bottom && config.bottom.length > 0 && (
        <div className="px-3 py-2 border-t border-slate-100 dark:border-slate-800">
          {config.bottom.map((item) => (
            <SidebarNavItem
              key={item.id}
              item={item}
              collapsed={isCollapsed}
              basePath={basePath}
              t={t}
            />
          ))}
        </div>
      )}
    </nav>
  );
}
