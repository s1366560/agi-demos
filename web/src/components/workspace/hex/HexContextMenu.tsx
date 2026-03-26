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
    return () => { document.removeEventListener('mousedown', handleClickOutside); };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="fixed z-50 bg-white rounded-lg shadow-lg border border-slate-200 py-1 min-w-[160px]"
      style={{ left: x, top: y }}
    >
      <div className="px-3 py-1.5 text-xs text-slate-400 font-medium">
        Hex ({q}, {r})
      </div>
      {ACTIONS.map((action) => (
        <button
          key={action.key}
          type="button"
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
