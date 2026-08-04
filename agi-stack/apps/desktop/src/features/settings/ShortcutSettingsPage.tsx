import { useMemo, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Cross2Icon, KeyboardIcon, MagnifyingGlassIcon } from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import {
  detectShortcutPlatform,
  shortcutChordFor,
  shortcutChordSegments,
  type ShortcutPlatform,
} from '../navigation/keyboardShortcutModel';
import {
  filterShortcutGroups,
  keypressCombo,
} from '../navigation/keyboardShortcutSearchModel';
import { SettingsPage } from './SettingsCorePages';
import '../navigation/KeyboardShortcutsDialog.css';
import './ShortcutSettingsPage.css';

function currentShortcutPlatform(): ShortcutPlatform {
  if (typeof navigator === 'undefined') return detectShortcutPlatform();
  return detectShortcutPlatform(navigator.userAgent, navigator.platform);
}

// Read-only, searchable reference over the same KEYBOARD_SHORTCUTS catalog
// that drives KeyboardShortcutsDialog; remapping is a documented follow-up
// because dispatch is hardcoded in App.tsx/composer keydown handlers.
export function ShortcutSettingsPage({
  platform = currentShortcutPlatform(),
}: {
  platform?: ShortcutPlatform;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [combo, setCombo] = useState<string | null>(null);
  const groups = useMemo(
    () =>
      filterShortcutGroups({
        query,
        combo,
        platform,
        resolveLabel: (definition) => t(definition.labelKey),
      }),
    [combo, platform, query, t],
  );

  const handleSearchKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape' && combo) {
      event.preventDefault();
      event.stopPropagation();
      setCombo(null);
      return;
    }
    if (!event.metaKey && !event.ctrlKey && !event.altKey) return;
    const captured = keypressCombo(event.nativeEvent);
    if (!captured) return;
    event.preventDefault();
    setCombo(captured);
  };

  return (
    <SettingsPage
      eyebrow={t('settings.preferences')}
      title={t('settings.shortcutsTitle')}
      description={t('settings.shortcutsSubtitle')}
      className="settings-preference-page settings-shortcuts-page"
    >
      <section className="settings-panel settings-shortcuts-panel">
        <header>
          <KeyboardIcon />
          <span>
            <strong>{t('settings.shortcutsCatalog')}</strong>
            <small>{t('settings.shortcutsCatalogDescription')}</small>
          </span>
        </header>
        <div className="settings-shortcuts-search-row">
          <label className="settings-shortcuts-search">
            <MagnifyingGlassIcon />
            <input
              value={query}
              onChange={(event) => setQuery(event.currentTarget.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder={t('settings.shortcutSearchPlaceholder')}
              aria-label={t('settings.shortcutSearchPlaceholder')}
            />
          </label>
          {combo ? (
            <span className="settings-shortcuts-combo-chip">
              <kbd className="shortcuts-kbd">{combo}</kbd>
              <button
                type="button"
                aria-label={t('settings.shortcutComboClear')}
                title={t('settings.shortcutComboClear')}
                onClick={() => setCombo(null)}
              >
                <Cross2Icon />
              </button>
            </span>
          ) : null}
        </div>
        <p className="settings-shortcuts-hint">{t('settings.shortcutSearchHint')}</p>
        {groups.length > 0 ? (
          groups.map(({ group, shortcuts }) => (
            <section className="shortcuts-group" key={group}>
              <h3 className="shortcuts-group__title">{t(`shortcuts.group.${group}`)}</h3>
              <ul className="shortcuts-group__list">
                {shortcuts.map((definition) => (
                  <li className="shortcuts-row" key={definition.id}>
                    <span className="shortcuts-row__label">{t(definition.labelKey)}</span>
                    <span className="shortcuts-row__chord">
                      {shortcutChordSegments(shortcutChordFor(definition, platform)).map(
                        (segment) => (
                          <kbd className="shortcuts-kbd" key={segment}>
                            {segment}
                          </kbd>
                        ),
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))
        ) : (
          <p className="settings-shortcuts-empty" role="status">
            {t('settings.noShortcutMatches')}
          </p>
        )}
        <p className="settings-shortcuts-note">{t('settings.shortcutsReadOnlyNote')}</p>
      </section>
    </SettingsPage>
  );
}
