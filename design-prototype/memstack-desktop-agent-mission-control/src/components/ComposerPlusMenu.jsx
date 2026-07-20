import { useEffect, useRef, useState } from 'react';
import {
  CameraIcon,
  ChatBubbleIcon,
  ChevronRightIcon,
  ComponentInstanceIcon,
  ImageIcon,
  MagicWandIcon,
  PersonIcon,
  PlusIcon,
  SlashIcon,
  UploadIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../i18n';
import { managementCatalog } from '../managementData';

const COMMANDS = [
  ['/plan', 'Draft or revise the plan before acting'],
  ['/review', 'Run an independent review of current work'],
  ['/verify', 'Re-run verification and attach evidence'],
  ['/summarize', 'Summarize progress and open questions'],
];

export function ComposerPlusMenu({ sessions = [], onAdd, compact = false }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function onKeyDown(event) {
      if (event.key === 'Escape') close();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open]);

  function close() {
    setOpen(false);
    setExpanded(null);
  }

  function pick(kind, label) {
    onAdd({ kind, label });
    close();
  }

  function handleFiles(event) {
    Array.from(event.target.files ?? []).forEach((file) => onAdd({ kind: 'attachment', label: file.name }));
    event.target.value = '';
    close();
  }

  const categories = [
    { id: 'attachments', label: t('Attachments'), Icon: UploadIcon },
    {
      id: 'agents',
      label: t('Agents'),
      Icon: PersonIcon,
      items: managementCatalog.agents.map((agent) => ({
        key: agent.id,
        label: `@${agent.name}`,
        detail: agent.meta,
        disabled: agent.status === 'paused',
      })),
    },
    {
      id: 'skills',
      label: t('Skills'),
      Icon: MagicWandIcon,
      items: managementCatalog.skills.map((skill) => ({
        key: skill.id,
        label: `${t('Skill')} · ${skill.name}`,
        detail: skill.meta,
      })),
    },
    {
      id: 'plugins',
      label: t('Plugins'),
      Icon: ComponentInstanceIcon,
      items: managementCatalog.plugins
        .filter((plugin) => plugin.status !== 'available')
        .map((plugin) => ({
          key: plugin.id,
          label: `${t('Plugin')} · ${plugin.name}`,
          detail: plugin.meta,
        })),
    },
    {
      id: 'commands',
      label: t('Commands'),
      Icon: SlashIcon,
      items: COMMANDS.map(([label, detail]) => ({ key: label, label, detail: t(detail) })),
    },
    {
      id: 'sessions',
      label: t('Existing threads'),
      Icon: ChatBubbleIcon,
      items: sessions.map((session) => ({
        key: session.id,
        label: `${t('Thread')} · ${session.title}`,
        detail: session.meta ? t(session.meta) : undefined,
      })),
    },
  ];

  return (
    <div className="plus-menu-anchor">
      <button
        type="button"
        className={compact ? undefined : 'picker-chip'}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('Add context and tools')}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <PlusIcon />
        {t('Add')}
      </button>
      {open ? (
        <>
          <div className="plus-menu-backdrop" onClick={close} aria-hidden="true" />
          <div className="plus-menu" role="menu" aria-label={t('Add context and tools')}>
            <div className="plus-menu-header">{t('Add context and tools')}</div>
            {categories.map(({ id, label, Icon, items }) => (
              <div className="plus-menu-group" key={id}>
                <button
                  type="button"
                  className={`plus-menu-category${expanded === id ? ' expanded' : ''}`}
                  aria-expanded={expanded === id}
                  onClick={() => setExpanded((current) => (current === id ? null : id))}
                >
                  <Icon />
                  <span>{label}</span>
                  <ChevronRightIcon className="chevron" />
                </button>
                {expanded === id ? (
                  <div className="plus-menu-items">
                    {id === 'attachments' ? (
                      <>
                        <button type="button" className="plus-menu-item" onClick={() => fileInputRef.current?.click()}>
                          <b><ImageIcon />{t('Files & photos')}</b>
                          <small>{t('Upload from this device')}</small>
                        </button>
                        <button type="button" className="plus-menu-item" onClick={() => pick('attachment', `${t('Screenshot')} · ${new Date().toTimeString().slice(0, 5)}`)}>
                          <b><CameraIcon />{t('Screenshot')}</b>
                          <small>{t('Capture the current screen')}</small>
                        </button>
                      </>
                    ) : items.length ? (
                      items.map((item) => (
                        <button
                          type="button"
                          className="plus-menu-item"
                          key={item.key}
                          disabled={item.disabled}
                          onClick={() => pick(id, item.label)}
                        >
                          <b>{item.label}</b>
                          {item.detail ? <small>{item.detail}</small> : null}
                        </button>
                      ))
                    ) : (
                      <div className="plus-menu-empty">{t('No other threads')}</div>
                    )}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </>
      ) : null}
      <input ref={fileInputRef} type="file" multiple hidden tabIndex={-1} aria-hidden="true" onChange={handleFiles} />
    </div>
  );
}
