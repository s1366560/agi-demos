import { useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { CheckIcon, ChevronDownIcon } from '@radix-ui/react-icons';

export type PickerMenuOption = {
  value: string;
  label: string;
  description?: string;
  meta?: string | null;
  badges?: string[];
  disabled?: boolean;
};

type PickerMenuProps = {
  label: string;
  value: string;
  options: readonly PickerMenuOption[];
  disabled?: boolean;
  readOnly?: boolean;
  hideLabel?: boolean;
  onChange: (value: string) => void;
  footer?: { label: string; icon?: ReactNode; onClick: () => void };
};

export function PickerMenu({
  label,
  value,
  options,
  disabled = false,
  readOnly = false,
  hideLabel = false,
  onChange,
  footer,
}: PickerMenuProps) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return;
    const close = (event: Event) => {
      const target = event.target;
      if (target instanceof Node && !anchorRef.current?.contains(target)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('pointerdown', close, true);
    window.addEventListener('focusin', close);
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      window.removeEventListener('pointerdown', close, true);
      window.removeEventListener('focusin', close);
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  return (
    <div className="picker-menu-anchor" ref={anchorRef}>
      <button
        className="picker-chip"
        type="button"
        aria-controls={menuId}
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`${label} ${selected?.label ?? value}`}
        disabled={disabled || options.length === 0}
        onClick={() => setOpen((current) => !current)}
      >
        {hideLabel ? null : <span>{label}</span>}
        <b>{selected?.label ?? value}</b>
        <ChevronDownIcon aria-hidden="true" />
      </button>
      {open ? (
        <div className="picker-menu" id={menuId} role="menu" aria-label={label}>
          <div className="picker-menu-header">{label}</div>
          <div className="picker-menu-items">
            {options.map((option) => {
              const isSelected = option.value === value;
              return (
                <button
                  className={isSelected ? 'selected' : ''}
                  type="button"
                  role="menuitemradio"
                  aria-checked={isSelected}
                  disabled={option.disabled || (readOnly && !isSelected)}
                  key={option.value}
                  onClick={() => {
                    if (!readOnly) onChange(option.value);
                    setOpen(false);
                  }}
                >
                  <span className="picker-menu-check" aria-hidden="true">
                    {isSelected ? <CheckIcon /> : null}
                  </span>
                  <span className="picker-menu-copy">
                    <b>
                      {option.label}
                      {option.badges?.map((badge) => <em key={badge}>{badge}</em>)}
                    </b>
                    {option.description ? <small>{option.description}</small> : null}
                  </span>
                  {option.meta ? <span className="picker-menu-meta">{option.meta}</span> : null}
                </button>
              );
            })}
          </div>
          {footer ? (
            <button
              className="picker-menu-footer"
              type="button"
              onClick={() => {
                setOpen(false);
                footer.onClick();
              }}
            >
              {footer.icon}
              {footer.label}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
