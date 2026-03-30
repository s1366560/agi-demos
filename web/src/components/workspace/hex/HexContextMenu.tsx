import { useEffect, useRef } from 'react';
import type { FC } from 'react';

export interface HexContextMenuProps {
  q: number;
  r: number;
  x: number;
  y: number;
  onClose: () => void;
  onAction?: (action: string, q: number, r: number) => void;
}

const ACTIONS = [
  { key: 'view_details', label: 'View Details' },
  { key: 'assign_agent', label: 'Assign Agent' },
  { key: 'add_corridor', label: 'Add Corridor' },
  { key: 'remove', label: 'Remove', danger: true },
];

export const HexContextMenu: FC<HexContextMenuProps> = ({ q, r, x, y, onClose, onAction }) => {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    
    const firstMenuItem = ref.current?.querySelector('[role="menuitem"]') as HTMLElement;
    if (firstMenuItem) {
      firstMenuItem.focus();
    }
    
    return () => { document.removeEventListener('mousedown', handleClickOutside); };
  }, [onClose]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!ref.current) return;
    
    if (e.key === 'Escape') {
      onClose();
      return;
    }

    const menuItems = Array.from(ref.current.querySelectorAll<HTMLElement>('[role="menuitem"]'));
    if (!menuItems.length) return;

    const currentIndex = menuItems.indexOf(document.activeElement as HTMLElement);

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const nextIndex = (currentIndex + 1) % menuItems.length;
      menuItems[nextIndex]?.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      const nextIndex = (currentIndex - 1 + menuItems.length) % menuItems.length;
      menuItems[nextIndex]?.focus();
    }
  };

  return (
    <div
      ref={ref}
      role="menu"
      aria-label="Hex cell actions"
      onKeyDown={handleKeyDown}
      className="fixed z-50 bg-white rounded-lg shadow-lg border border-slate-200 py-1 min-w-40"
      style={{ left: x, top: y }}
    >
      <div className="px-3 py-1.5 text-xs text-slate-400 font-medium">
        Hex ({q}, {r})
      </div>
      {ACTIONS.map((action) => (
        <button
          key={action.key}
          type="button"
          role="menuitem"
          className={`w-full text-left px-3 py-1.5 text-sm hover:bg-slate-50 ${action.danger ? 'text-red-500 hover:bg-red-50' : 'text-slate-700'}`}
          onClick={() => {
            if (onAction) {
              onAction(action.key, q, r);
            }
            onClose();
          }}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
};
