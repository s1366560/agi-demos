import { useEffect, useRef, useState } from 'react';
import { CheckIcon, ChevronDownIcon, LockClosedIcon } from '@radix-ui/react-icons';
import { AlertDialog, Button, Flex } from '@radix-ui/themes';

import { useI18n } from '../../i18n';
import { PERMISSION_PRESETS, type PermissionPreset } from './permissionPresetModel';

/**
 * Session-scoped approval autonomy dial (P1-2). Selecting "Full access" the
 * first time in a workspace requires an explicit one-time acknowledgement;
 * the parent owns persistence via the callbacks.
 */
export function PermissionPresetControl({
  preset,
  fullAccessAcknowledged,
  onPresetChange,
  onAcknowledgeFullAccess,
}: {
  preset: PermissionPreset;
  fullAccessAcknowledged: boolean;
  onPresetChange: (preset: PermissionPreset) => void;
  onAcknowledgeFullAccess: () => void;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [warningOpen, setWarningOpen] = useState(false);
  const confirmingRef = useRef(false);
  const trayRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeIfOutside = (event: Event) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (trayRef.current?.contains(target)) return;
      setOpen(false);
    };
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setOpen(false);
    };
    window.addEventListener('pointerdown', closeIfOutside, true);
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      window.removeEventListener('pointerdown', closeIfOutside, true);
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  const selectPreset = (next: PermissionPreset) => {
    setOpen(false);
    if (next === 'full' && !fullAccessAcknowledged) {
      setWarningOpen(true);
      return;
    }
    if (next !== preset) onPresetChange(next);
  };

  return (
    <div className="composer-control permission-preset-control" ref={trayRef}>
      <button
        className="composer-mode-button"
        type="button"
        aria-label={t('chat.permissionPreset.label')}
        aria-haspopup="menu"
        aria-expanded={open}
        title={t(`chat.permissionPreset.${preset}Description`)}
        onClick={() => setOpen((current) => !current)}
      >
        <LockClosedIcon aria-hidden="true" />
        {t('chat.permissionPreset.label')}: {t(`chat.permissionPreset.${preset}`)}
        <ChevronDownIcon aria-hidden="true" />
      </button>
      {open ? (
        <div
          className="composer-popover permission-preset-popover"
          role="menu"
          aria-label={t('chat.permissionPreset.label')}
        >
          <strong>{t('chat.permissionPreset.label')}</strong>
          {PERMISSION_PRESETS.map((candidate) => (
            <button
              className={candidate === preset ? 'selected' : ''}
              type="button"
              role="menuitemradio"
              aria-checked={candidate === preset}
              key={candidate}
              onClick={() => selectPreset(candidate)}
            >
              <span>
                <b>{t(`chat.permissionPreset.${candidate}`)}</b>
                <small>{t(`chat.permissionPreset.${candidate}Description`)}</small>
              </span>
              {candidate === preset ? <CheckIcon aria-hidden="true" /> : null}
            </button>
          ))}
        </div>
      ) : null}
      {warningOpen ? (
        <AlertDialog.Root
          open
          onOpenChange={(nextOpen) => {
            if (!nextOpen && !confirmingRef.current) setWarningOpen(false);
          }}
        >
          <AlertDialog.Content maxWidth="450px" aria-describedby="full-access-warning-description">
            <AlertDialog.Title>{t('chat.fullAccessWarning.title')}</AlertDialog.Title>
            <AlertDialog.Description id="full-access-warning-description" size="2">
              {t('chat.fullAccessWarning.body')}
            </AlertDialog.Description>
            <Flex gap="3" mt="4" justify="end">
              <AlertDialog.Cancel>
                <Button variant="soft" color="gray">
                  {t('common.cancel')}
                </Button>
              </AlertDialog.Cancel>
              <AlertDialog.Action>
                <Button
                  color="red"
                  onClick={() => {
                    confirmingRef.current = true;
                    onAcknowledgeFullAccess();
                    onPresetChange('full');
                    setWarningOpen(false);
                  }}
                >
                  {t('chat.fullAccessWarning.confirm')}
                </Button>
              </AlertDialog.Action>
            </Flex>
          </AlertDialog.Content>
        </AlertDialog.Root>
      ) : null}
    </div>
  );
}
