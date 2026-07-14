import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react';
import { PlusIcon } from '@radix-ui/react-icons';

type ComposerMenu = 'files' | 'mode' | 'model' | 'effort' | 'runtime';

type ComposerControlsProps = {
  disabledHint?: string | null;
  effortLabel?: string;
  modeLabel?: string;
  modelLabel?: string;
  runtimeTargetLabel?: string;
  runtimeTargetOptions?: string[];
  onAddFiles?: () => void;
  onModeChange?: (value: string) => void;
  onModelChange?: (value: string) => void;
  onEffortChange?: (value: string) => void;
  onRuntimeTargetChange?: (value: string) => void;
};

export function ComposerControls({
  effortLabel = 'Medium',
  modeLabel = 'Autopilot',
  modelLabel = 'Local model',
  runtimeTargetLabel = 'Local Rust Core',
  runtimeTargetOptions = ['Local Rust Core', 'Staging Runtime'],
  onAddFiles,
  onModeChange,
  onModelChange,
  onEffortChange,
  onRuntimeTargetChange,
}: ComposerControlsProps) {
  const [openMenu, setOpenMenu] = useState<ComposerMenu | null>(null);
  const [mode, setMode] = useState(modeLabel);
  const [model, setModel] = useState(modelLabel);
  const [effort, setEffort] = useState(effortLabel);
  const [runtimeTarget, setRuntimeTarget] = useState(runtimeTargetLabel);
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
    setRuntimeTarget(runtimeTargetLabel);
  }, [runtimeTargetLabel]);

  useEffect(() => {
    if (!openMenu) return;

    const closeIfOutsideTray = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (trayRef.current?.contains(target)) return;
      setOpenMenu(null);
    };

    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
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
      {onAddFiles ? (
        <div className="composer-control">
          <button
            className="composer-add-button"
            type="button"
            aria-label="Add files or folders"
            onClick={onAddFiles}
          >
            <PlusIcon />
          </button>
        </div>
      ) : null}

      {onModeChange ? (
        <ComposerSelectControl
          disabled={false}
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
            onModeChange(value);
            setOpenMenu(null);
          }}
        />
      ) : null}
      {onModelChange ? (
        <ComposerModelCombobox
          disabled={false}
          compactLabel={compactComposerLabel(model)}
          open={openMenu === 'model'}
          controlLabel={`Select model, ${model}`}
          options={Array.from(new Set([modelLabel, 'Workspace model', 'Cloud model']))}
          selected={model}
          onToggle={() => toggleMenu('model')}
          onInput={(value) => {
            setModel(value);
            onModelChange(value);
          }}
          onSelect={(value) => {
            setModel(value);
            onModelChange(value);
            setOpenMenu(null);
          }}
        />
      ) : null}
      {onEffortChange ? (
        <ComposerSelectControl
          disabled={false}
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
            onEffortChange(value);
            setOpenMenu(null);
          }}
        />
      ) : null}
      {onRuntimeTargetChange ? (
        <ComposerSelectControl
          disabled={false}
          compactLabel={compactComposerLabel(runtimeTarget)}
          label={runtimeTarget}
          open={openMenu === 'runtime'}
          title="Runtime target"
          controlLabel={`Runtime target: ${runtimeTarget}`}
          options={Array.from(new Set([runtimeTarget, ...runtimeTargetOptions]))}
          selected={runtimeTarget}
          onToggle={() => toggleMenu('runtime')}
          onSelect={(value) => {
            setRuntimeTarget(value);
            onRuntimeTargetChange(value);
            setOpenMenu(null);
          }}
        />
      ) : null}
    </div>
  );
}

function ComposerModelCombobox({
  disabled,
  compactLabel,
  open,
  controlLabel,
  options,
  selected,
  onToggle,
  onInput,
  onSelect,
}: {
  disabled: boolean;
  compactLabel: string;
  open: boolean;
  controlLabel: string;
  options: string[];
  selected: string;
  onToggle: () => void;
  onInput: (value: string) => void;
  onSelect: (value: string) => void;
}) {
  const listboxId = 'composer-model-listbox';

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter' || event.key === ' ' || event.key === 'ArrowDown') {
      event.preventDefault();
      if (!open) onToggle();
    }
    if (event.key === 'Escape' && open) {
      event.preventDefault();
      onToggle();
    }
  };

  return (
    <div className="composer-control">
      <input
        className="composer-mode-button composer-model-combobox"
        data-compact-label={compactLabel}
        type="text"
        role="combobox"
        aria-label={controlLabel}
        aria-autocomplete="list"
        aria-controls={listboxId}
        aria-expanded={open}
        aria-haspopup="listbox"
        disabled={disabled}
        title={disabled ? 'Model selection is managed by the active runtime.' : undefined}
        value={selected}
        onChange={(event) => onInput(event.target.value)}
        onClick={() => {
          if (!disabled) onToggle();
        }}
        onKeyDown={handleKeyDown}
      />
      {open ? (
        <ComposerPopover id={listboxId} role="listbox" title="Select model">
          {options.map((option) => (
            <button
              className={selected === option ? 'selected' : ''}
              type="button"
              role="option"
              aria-selected={selected === option}
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

function ComposerSelectControl({
  disabled,
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
  disabled: boolean;
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
        disabled={disabled}
        title={disabled ? `${title} is managed by the active runtime.` : undefined}
        onClick={() => {
          if (!disabled) onToggle();
        }}
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

function ComposerPopover({
  id,
  role = 'menu',
  title,
  children,
}: {
  id?: string;
  role?: 'listbox' | 'menu';
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="composer-popover" id={id} role={role} aria-label={title}>
      <strong>{title}</strong>
      {children}
    </div>
  );
}

function compactComposerLabel(label: string): string {
  const withoutSuffix = label.replace(/\s+model$/i, '');
  if (withoutSuffix === 'Local Rust Core') {
    return 'Local';
  }
  if (withoutSuffix === 'Staging Runtime') {
    return 'Staging';
  }
  if (withoutSuffix.toLowerCase() === 'medium') {
    return 'Med';
  }
  if (withoutSuffix.includes('·')) {
    return withoutSuffix.split(/\s+/)[0] ?? withoutSuffix;
  }
  return withoutSuffix;
}
