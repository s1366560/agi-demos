import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { PlusIcon } from '@radix-ui/react-icons';

type ComposerMenu = 'files' | 'mode' | 'model' | 'effort';

type ComposerControlsProps = {
  disabledHint?: string | null;
  effortLabel?: string;
  modeLabel?: string;
  modelLabel?: string;
};

export function ComposerControls({
  disabledHint,
  effortLabel = 'Medium',
  modeLabel = 'Autopilot',
  modelLabel = 'Local model',
}: ComposerControlsProps) {
  const [openMenu, setOpenMenu] = useState<ComposerMenu | null>(null);
  const [mode, setMode] = useState(modeLabel);
  const [model, setModel] = useState(modelLabel);
  const [effort, setEffort] = useState(effortLabel);
  const trayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMode(modeLabel);
  }, [modeLabel]);

  useEffect(() => {
    setModel(modelLabel);
  }, [modelLabel]);

  useEffect(() => {
    setEffort(effortLabel);
  }, [effortLabel]);

  useEffect(() => {
    if (!openMenu) return;

    const closeIfOutsideTray = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (trayRef.current?.contains(target)) return;
      setOpenMenu(null);
    };

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setOpenMenu(null);
    };

    window.addEventListener('pointerdown', closeIfOutsideTray, true);
    window.addEventListener('focusin', closeIfOutsideTray);
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      window.removeEventListener('pointerdown', closeIfOutsideTray, true);
      window.removeEventListener('focusin', closeIfOutsideTray);
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [openMenu]);

  const toggleMenu = (menu: ComposerMenu) => {
    setOpenMenu((current) => (current === menu ? null : menu));
  };

  return (
    <div
      className="composer-control-tray"
      ref={trayRef}
      role="toolbar"
      aria-label="Message composer tools"
    >
      <div className="composer-control">
        <button
          className="composer-add-button"
          type="button"
          aria-label="Add files or folders"
          aria-haspopup="menu"
          aria-expanded={openMenu === 'files'}
          onClick={() => toggleMenu('files')}
        >
          <PlusIcon />
        </button>
        {openMenu === 'files' ? (
          <ComposerPopover title="Add context">
            <button type="button" role="menuitem" disabled={Boolean(disabledHint)}>
              Add files
            </button>
            <button type="button" role="menuitem" disabled={Boolean(disabledHint)}>
              Add folders
            </button>
            <button type="button" role="menuitem" disabled={Boolean(disabledHint)}>
              Reference workspace
            </button>
            {disabledHint ? <p>{disabledHint}</p> : null}
          </ComposerPopover>
        ) : null}
      </div>

      <ComposerSelectControl
        compactLabel="Mode"
        label={mode}
        open={openMenu === 'mode'}
        title="Mode"
        controlLabel={`Mode: ${mode}, Command + Shift + M`}
        options={Array.from(new Set([modeLabel, 'Ask', 'Plan']))}
        selected={mode}
        onToggle={() => toggleMenu('mode')}
        onSelect={(value) => {
          setMode(value);
          setOpenMenu(null);
        }}
      />
      <ComposerSelectControl
        compactLabel={compactComposerLabel(model)}
        label={model}
        open={openMenu === 'model'}
        title="Model"
        controlLabel={`Select model, ${model}`}
        options={Array.from(new Set([modelLabel, 'Workspace model', 'Cloud model']))}
        selected={model}
        onToggle={() => toggleMenu('model')}
        onSelect={(value) => {
          setModel(value);
          setOpenMenu(null);
        }}
      />
      <ComposerSelectControl
        compactLabel={compactComposerLabel(effort)}
        label={effort}
        open={openMenu === 'effort'}
        title="Effort"
        controlLabel={`Reasoning effort: ${effort}`}
        options={Array.from(new Set(['Low', 'Medium', 'High', effortLabel]))}
        selected={effort}
        onToggle={() => toggleMenu('effort')}
        onSelect={(value) => {
          setEffort(value);
          setOpenMenu(null);
        }}
      />
    </div>
  );
}

function ComposerSelectControl({
  compactLabel,
  label,
  open,
  title,
  controlLabel,
  options,
  selected,
  onToggle,
  onSelect,
}: {
  compactLabel: string;
  label: string;
  open: boolean;
  title: string;
  controlLabel: string;
  options: string[];
  selected: string;
  onToggle: () => void;
  onSelect: (value: string) => void;
}) {
  return (
    <div className="composer-control">
      <button
        className="composer-mode-button"
        data-compact-label={compactLabel}
        type="button"
        aria-label={controlLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={onToggle}
      >
        {label}
      </button>
      {open ? (
        <ComposerPopover title={title}>
          {options.map((option) => (
            <button
              className={selected === option ? 'selected' : ''}
              type="button"
              role="menuitemradio"
              aria-checked={selected === option}
              key={option}
              onClick={() => onSelect(option)}
            >
              {option}
            </button>
          ))}
        </ComposerPopover>
      ) : null}
    </div>
  );
}

function ComposerPopover({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="composer-popover" role="menu" aria-label={title}>
      <strong>{title}</strong>
      {children}
    </div>
  );
}

function compactComposerLabel(label: string): string {
  const withoutSuffix = label.replace(/\s+model$/i, '');
  if (withoutSuffix.toLowerCase() === 'medium') {
    return 'Med';
  }
  if (withoutSuffix.includes('·')) {
    return withoutSuffix.split(/\s+/)[0] ?? withoutSuffix;
  }
  return withoutSuffix;
}
