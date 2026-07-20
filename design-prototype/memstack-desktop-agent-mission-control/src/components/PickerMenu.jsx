import { useEffect, useRef, useState } from 'react';
import { CheckIcon, ChevronDownIcon } from '@radix-ui/react-icons';

import { useI18n } from '../i18n';

// Codex-style dropdown picker: trigger chip + upward popover with described options.
export function PickerMenu({ label, value, options, onChange, footer }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const anchorRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function onKey(event) {
      if (event.key === 'Escape') setOpen(false);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <div className="picker-menu-anchor" ref={anchorRef}>
      <button className="picker-chip" type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((current) => !current)}>
        {label} <b>{t(value)}</b>
        <ChevronDownIcon />
      </button>
      {open ? (
        <>
          <div className="picker-menu-backdrop" onClick={() => setOpen(false)} />
          <div className="picker-menu" role="menu" aria-label={label}>
            <div className="picker-menu-header">{label}</div>
            <div className="picker-menu-items">
              {options.map((option) => {
                const selected = option.value === value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={selected}
                    className={selected ? 'selected' : ''}
                    onClick={() => {
                      onChange(option.value);
                      setOpen(false);
                    }}
                  >
                    <span className="picker-menu-check" aria-hidden="true">{selected ? <CheckIcon /> : null}</span>
                    <span className="picker-menu-item-text">
                      <b>
                        {t(option.value)}
                        {option.badge ? <em className="picker-menu-badge">{t(option.badge)}</em> : null}
                      </b>
                      {option.description ? <small>{t(option.description)}</small> : null}
                    </span>
                    {option.meta ? <span className="picker-menu-meta">{option.meta}</span> : null}
                  </button>
                );
              })}
            </div>
            {footer ? (
              <button type="button" className="picker-menu-footer" onClick={() => { setOpen(false); footer.onClick(); }}>
                {footer.icon}
                {t(footer.label)}
              </button>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
