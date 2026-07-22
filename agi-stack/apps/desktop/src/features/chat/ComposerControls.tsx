import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react';
import { CheckIcon, CubeIcon, MagnifyingGlassIcon, PlusIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';

type ComposerMenu = 'files' | 'mode' | 'model' | 'effort' | 'runtime';

export type ComposerModelOption = {
  value: string;
  modelId: string;
  providerLabel: string;
  description?: string;
  contextWindow?: string | null;
  roles?: string[];
};

type ComposerControlsProps = {
  disabledHint?: string | null;
  effortLabel?: string;
  modeLabel?: string;
  modelLabel?: string;
  modelOptions?: readonly ComposerModelOption[];
  modelValue?: string | null;
  modelPending?: boolean;
  modelError?: string | null;
  runtimeTargetLabel?: string;
  runtimeTargetOptions?: string[];
  onAddFiles?: () => void;
  onModeChange?: (value: string) => void;
  onModelChange?: (value: string) => Promise<void>;
  onModelReset?: () => Promise<void>;
  onEffortChange?: (value: string) => void;
  onRuntimeTargetChange?: (value: string) => void;
};

export function ComposerControls({
  effortLabel = 'Medium',
  modeLabel = 'Autopilot',
  modelLabel = 'Local model',
  modelOptions = [],
  modelValue = null,
  modelPending = false,
  modelError = null,
  runtimeTargetLabel = 'Local Rust Core',
  runtimeTargetOptions = ['Local Rust Core', 'Staging Runtime'],
  onAddFiles,
  onModeChange,
  onModelChange,
  onModelReset,
  onEffortChange,
  onRuntimeTargetChange,
}: ComposerControlsProps) {
  const [openMenu, setOpenMenu] = useState<ComposerMenu | null>(null);
  const [mode, setMode] = useState(modeLabel);
  const [effort, setEffort] = useState(effortLabel);
  const [runtimeTarget, setRuntimeTarget] = useState(runtimeTargetLabel);
  const trayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMode(modeLabel);
  }, [modeLabel]);

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
      {onModelChange && modelOptions.length ? (
        <ComposerModelSwitch
          disabled={modelPending}
          compactLabel={compactComposerLabel(modelLabel)}
          open={openMenu === 'model'}
          displayLabel={modelLabel}
          error={modelError}
          options={modelOptions}
          pending={modelPending}
          selected={modelValue}
          onToggle={() => toggleMenu('model')}
          onSelect={(value) => {
            void onModelChange(value)
              .then(() => setOpenMenu(null))
              .catch(() => undefined);
          }}
          onReset={onModelReset}
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

function ComposerModelSwitch({
  disabled,
  compactLabel,
  open,
  displayLabel,
  error,
  options,
  pending,
  selected,
  onToggle,
  onSelect,
  onReset,
}: {
  disabled: boolean;
  compactLabel: string;
  open: boolean;
  displayLabel: string;
  error: string | null;
  options: readonly ComposerModelOption[];
  pending: boolean;
  selected: string | null;
  onToggle: () => void;
  onSelect: (value: string) => void;
  onReset?: () => Promise<void>;
}) {
  const { t } = useI18n();
  const listboxId = useId();
  const [query, setQuery] = useState('');
  const normalizedQuery = query.trim().toLowerCase();
  const visibleOptions = useMemo(
    () =>
      normalizedQuery
        ? options.filter((option) =>
            `${option.modelId} ${option.providerLabel}`.toLowerCase().includes(normalizedQuery),
          )
        : options,
    [normalizedQuery, options],
  );

  useEffect(() => {
    if (!open) setQuery('');
  }, [open]);

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
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
      <button
        className="composer-mode-button composer-model-button"
        data-compact-label={compactLabel}
        type="button"
        aria-label={t('chat.selectModel', { model: displayLabel })}
        aria-controls={listboxId}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-busy={pending}
        disabled={disabled}
        title={displayLabel}
        onClick={() => {
          if (!disabled) onToggle();
        }}
        onKeyDown={handleKeyDown}
      >
        <CubeIcon aria-hidden="true" />
        <span>{displayLabel}</span>
      </button>
      {open ? (
        <div
          className="composer-popover composer-model-popover"
          id={listboxId}
          role="dialog"
          aria-label={t('chat.modelSwitcherTitle')}
        >
          <div className="composer-model-heading">
            <strong>{t('chat.modelSwitcherTitle')}</strong>
            {onReset ? (
              <button
                type="button"
                disabled={pending}
                onClick={() => {
                  void onReset().catch(() => undefined);
                }}
              >
                {t('chat.resetModelOverride')}
              </button>
            ) : null}
          </div>
          <label className="composer-model-search">
            <MagnifyingGlassIcon aria-hidden="true" />
            <input
              type="search"
              value={query}
              placeholder={t('chat.searchModels')}
              aria-label={t('chat.searchModels')}
              autoFocus
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <div className="composer-model-options" role="listbox">
            {visibleOptions.map((option) => (
              <button
                className={selected === option.value ? 'selected' : ''}
                type="button"
                role="option"
                aria-selected={selected === option.value}
                disabled={pending}
                key={option.value}
                onClick={() => onSelect(option.value)}
              >
                <span>
                  <b>
                    {option.modelId}
                    {option.roles?.map((role) => (
                      <em className="composer-model-role" key={role}>
                        {t(`task.modelRole.${role}`)}
                      </em>
                    ))}
                  </b>
                  <small>{option.description ?? option.providerLabel}</small>
                </span>
                {option.contextWindow ? (
                  <small className="composer-model-context">{option.contextWindow}</small>
                ) : null}
                {selected === option.value ? <CheckIcon aria-hidden="true" /> : null}
              </button>
            ))}
            {!visibleOptions.length ? <p>{t('chat.noModelsFound')}</p> : null}
          </div>
          {pending ? <p>{t('chat.switchingModel')}</p> : null}
          {error ? <p className="composer-model-error">{error}</p> : null}
        </div>
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
