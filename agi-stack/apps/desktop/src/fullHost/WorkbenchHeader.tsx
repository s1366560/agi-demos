import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { useI18n } from '../i18n';
import { headerItemActive, workbenchHeaderGroups } from './workbenchModel';
import type { WorkbenchHeaderSlot } from '../../../../packages/plugin-slots/src/workbenchHeader';

export type WorkbenchHeaderGroupView = {
  readonly id: string;
  readonly label: string;
  readonly current: boolean;
  readonly items: readonly {
    readonly id: string;
    readonly label: string;
    readonly path: string;
    readonly active: boolean;
  }[];
};

/**
 * The scrollport only contains the group buttons. Its dropdown is a sibling, so
 * `overflow-x: auto` cannot clip the menu vertically.
 */
export function WorkbenchHeaderFrame({
  label,
  groups,
  openId,
  menuStyle,
  navRef,
  onToggle,
  onSelect,
}: {
  label: string;
  groups: readonly WorkbenchHeaderGroupView[];
  openId: string | null;
  menuStyle?: CSSProperties;
  navRef?: (node: HTMLElement | null) => void;
  onToggle(id: string, button: HTMLButtonElement): void;
  onSelect(path: string): void;
}) {
  const open = groups.find((group) => group.id === openId);
  return (
    <nav className="desktop-workbench-header" aria-label={label} ref={navRef}>
      <div className="desktop-workbench-header-scroll">
        {groups.map((group) => (
          <div className="desktop-workbench-group" key={group.id}>
            <button
              type="button"
              data-header-group={group.id}
              aria-expanded={group.id === openId}
              aria-current={group.current ? 'true' : undefined}
              onClick={(event) => onToggle(group.id, event.currentTarget)}
            >
              {group.label}
            </button>
          </div>
        ))}
      </div>
      {open ? (
        <div
          className="desktop-workbench-menu"
          role="group"
          aria-label={open.label}
          style={menuStyle}
        >
          {open.items.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-current={item.active ? 'page' : undefined}
              onClick={() => onSelect(item.path)}
            >
              {item.label}
            </button>
          ))}
        </div>
      ) : null}
    </nav>
  );
}

function headerGroupSelector(id: string): string {
  return `[data-header-group="${CSS.escape(id)}"]`;
}

function menuPosition(nav: HTMLElement, button: HTMLButtonElement): CSSProperties {
  const navRect = nav.getBoundingClientRect();
  const buttonRect = button.getBoundingClientRect();
  return {
    top: buttonRect.bottom - navRect.top + 4,
    left: buttonRect.left - navRect.left,
  };
}

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
  const nav = useRef<HTMLElement>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [menuStyle, setMenuStyle] = useState<CSSProperties>();
  const groups = workbenchHeaderGroups(items).map((group) => ({
    id: group.id,
    label: t(group.items[0]?.groupLabel ?? group.id),
    current: group.items.some((item) => headerItemActive(item, pathname)),
    items: group.items.map((item) => ({
      id: item.id,
      label: t(item.label),
      path: item.path,
      active: headerItemActive(item, pathname),
    })),
  }));
  useEffect(() => {
    if (!open) return;
    const root = nav.current;
    const scrolling = root?.querySelector('.desktop-workbench-header-scroll');
    const button = root?.querySelector<HTMLButtonElement>(headerGroupSelector(open));
    if (root && button) setMenuStyle(menuPosition(root, button));
    const place = () => {
      const current = nav.current;
      const trigger = current?.querySelector<HTMLButtonElement>(headerGroupSelector(open));
      if (current && trigger) setMenuStyle(menuPosition(current, trigger));
    };
    scrolling?.addEventListener('scroll', place, { passive: true });
    window.addEventListener('resize', place);
    const dismiss = (event: PointerEvent) => {
      if (event.target instanceof Node && nav.current?.contains(event.target)) return;
      setOpen(null);
    };
    document.addEventListener('pointerdown', dismiss);
    return () => {
      scrolling?.removeEventListener('scroll', place);
      window.removeEventListener('resize', place);
      document.removeEventListener('pointerdown', dismiss);
    };
  }, [open]);
  if (!groups.length) return null;
  return (
    <WorkbenchHeaderFrame
      label={t('featureDirectory.title')}
      groups={groups}
      openId={open}
      menuStyle={menuStyle}
      navRef={(node) => {
        nav.current = node;
      }}
      onToggle={(id, button) => {
        const next = open === id ? null : id;
        if (next && nav.current) setMenuStyle(menuPosition(nav.current, button));
        setOpen(next);
      }}
      onSelect={(path) => {
        setOpen(null);
        onNavigate(path);
      }}
    />
  );
}
