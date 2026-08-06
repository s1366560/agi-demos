import {
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  MagnifyingGlassIcon,
} from '@radix-ui/react-icons';
import {
  useI18n,
} from '../../i18n';
import {
  type CommandPaletteItem,
} from '../../appShellTypes';

export function CommandPalette({
  inputRef,
  query,
  items,
  onQueryChange,
  onClose,
}: {
  inputRef: RefObject<HTMLInputElement | null>;
  query: string;
  items: CommandPaletteItem[];
  onQueryChange: (query: string) => void;
  onClose: (restoreFocus?: boolean) => void;
}) {
  const { t } = useI18n();
  const paletteRef = useRef<HTMLElement>(null);
  const enabledItems = useMemo(
    () => items.filter((item) => !item.disabled),
    [items],
  );
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const activeItem =
    enabledItems.find((item) => item.id === activeItemId) ?? enabledItems[0];
  const activeOptionId = activeItem
    ? `command-option-${activeItem.id}`
    : undefined;

  useEffect(() => {
    setActiveItemId((current) => {
      if (current && enabledItems.some((item) => item.id === current)) {
        return current;
      }
      return enabledItems[0]?.id ?? null;
    });
  }, [enabledItems]);

  useEffect(() => {
    if (!activeOptionId) return;
    document
      .getElementById(activeOptionId)
      ?.scrollIntoView({ block: 'nearest' });
  }, [activeOptionId]);

  useEffect(() => {
    const keepFocusInsidePalette = (event: FocusEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (paletteRef.current?.contains(target)) return;
      inputRef.current?.focus();
    };

    window.addEventListener('focusin', keepFocusInsidePalette);
    return () => window.removeEventListener('focusin', keepFocusInsidePalette);
  }, [inputRef]);

  const runItem = (item: CommandPaletteItem) => {
    if (item.disabled) return;
    item.onSelect();
    onClose(false);
  };

  const moveActiveItem = (delta: number) => {
    setActiveItemId((current) => {
      if (enabledItems.length === 0) return null;
      const currentIndex = enabledItems.findIndex(
        (item) => item.id === current,
      );
      const startIndex =
        currentIndex === -1 ? (delta > 0 ? -1 : 0) : currentIndex;
      const nextIndex =
        (startIndex + delta + enabledItems.length) % enabledItems.length;
      return enabledItems[nextIndex].id;
    });
  };

  const containTabFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.defaultPrevented || event.key !== 'Tab') return;
    const focusableElements = getCommandPaletteFocusableElements(
      paletteRef.current,
    );
    if (!focusableElements.length) return;
    const firstElement = focusableElements[0];
    const lastElement = focusableElements[focusableElements.length - 1];
    const activeElement = document.activeElement;

    if (event.shiftKey && activeElement === firstElement) {
      event.preventDefault();
      lastElement.focus();
      return;
    }
    if (!event.shiftKey && activeElement === lastElement) {
      event.preventDefault();
      firstElement.focus();
    }
  };

  return (
    <div className="command-palette-backdrop" onMouseDown={() => onClose(true)}>
      <section
        ref={paletteRef}
        className="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label={t('commandPalette.title')}
        onKeyDown={containTabFocus}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <label className="command-search">
          <MagnifyingGlassIcon aria-hidden="true" />
          <input
            ref={inputRef}
            value={query}
            aria-label={t('commandPalette.search')}
            placeholder={t('commandPalette.searchPlaceholder')}
            aria-activedescendant={activeOptionId}
            onChange={(event) => onQueryChange(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault();
                moveActiveItem(1);
              }
              if (event.key === 'ArrowUp') {
                event.preventDefault();
                moveActiveItem(-1);
              }
              if (event.key === 'Home' && enabledItems[0]) {
                event.preventDefault();
                setActiveItemId(enabledItems[0].id);
              }
              if (
                event.key === 'End' &&
                enabledItems[enabledItems.length - 1]
              ) {
                event.preventDefault();
                setActiveItemId(enabledItems[enabledItems.length - 1].id);
              }
              if (event.key === 'Enter' && activeItem) {
                event.preventDefault();
                runItem(activeItem);
              }
              if (event.key === 'Escape') {
                event.preventDefault();
                onClose(true);
              }
            }}
          />
        </label>
        <div
          className="command-list"
          role="listbox"
          aria-label={t('commandPalette.results')}
        >
          {items.length === 0 ? (
            <div className="command-empty" role="status">
              {t('commandPalette.empty')}
            </div>
          ) : (
            items.map((item) => (
              <button
                id={`command-option-${item.id}`}
                className={`command-row ${item.disabled ? 'disabled' : ''} ${
                  item.id === activeItem?.id ? 'selected' : ''
                }`}
                type="button"
                role="option"
                aria-selected={item.id === activeItem?.id}
                key={item.id}
                disabled={item.disabled}
                onMouseEnter={() => {
                  if (!item.disabled) {
                    setActiveItemId(item.id);
                  }
                }}
                onClick={() => runItem(item)}
              >
                <span className="command-icon" aria-hidden="true">
                  {item.icon}
                </span>
                <span className="command-copy">
                  <strong>{item.label}</strong>
                  <em>{item.description}</em>
                </span>
                {item.shortcut ? <kbd className="command-shortcut">{item.shortcut}</kbd> : null}
              </button>
            ))
          )}
        </div>
      </section>
    </div>
  );
}

export function getCommandPaletteFocusableElements(
  container: HTMLElement | null,
): HTMLElement[] {
  if (!container) return [];
  const selectors = [
    'button:not(:disabled)',
    'input:not(:disabled)',
    'textarea:not(:disabled)',
    'select:not(:disabled)',
    '[tabindex]:not([tabindex="-1"])',
  ].join(',');
  return Array.from(container.querySelectorAll<HTMLElement>(selectors)).filter(
    (element) => element.getAttribute('aria-hidden') !== 'true',
  );
}
