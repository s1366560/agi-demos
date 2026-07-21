import { useEffect, useMemo, useRef, useState } from 'react';
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

import { useI18n } from '../../i18n';
import type {
  AgentConversation,
  ComposerContextItem,
  ComposerContextKind,
  ManagedAgentDefinition,
  ManagedPlugin,
  ManagedSkill,
} from '../../types';

const COMMANDS = [
  { id: '/plan', descriptionKey: 'composer.commandPlanDescription' },
  { id: '/review', descriptionKey: 'composer.commandReviewDescription' },
  { id: '/verify', descriptionKey: 'composer.commandVerifyDescription' },
  { id: '/summarize', descriptionKey: 'composer.commandSummarizeDescription' },
] as const;

type CatalogItem = {
  key: string;
  label: string;
  detail?: string;
  item: ComposerContextItem;
};

type Category = {
  id: 'attachments' | 'agents' | 'skills' | 'plugins' | 'commands' | 'threads';
  label: string;
  Icon: typeof UploadIcon;
  items?: CatalogItem[];
};

export type ComposerCatalogClient = {
  listManagedAgents: (signal?: AbortSignal) => Promise<ManagedAgentDefinition[]>;
  listManagedSkills: (signal?: AbortSignal) => Promise<ManagedSkill[]>;
  listManagedPlugins: (signal?: AbortSignal) => Promise<ManagedPlugin[]>;
};

type ComposerPlusMenuProps = {
  api: ComposerCatalogClient;
  conversations: readonly AgentConversation[];
  excludedConversationId?: string | null;
  compact?: boolean;
  onAdd: (item: ComposerContextItem) => void;
};

export function ComposerPlusMenu({
  api,
  conversations,
  excludedConversationId,
  compact = false,
  onAdd,
}: ComposerPlusMenuProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Category['id'] | null>(null);
  const [catalog, setCatalog] = useState<{
    agents: ManagedAgentDefinition[];
    skills: ManagedSkill[];
    plugins: ManagedPlugin[];
  } | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const anchorRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeIfOutside = (event: Event) => {
      const target = event.target;
      if (target instanceof Node && !anchorRef.current?.contains(target)) close();
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    window.addEventListener('pointerdown', closeIfOutside, true);
    window.addEventListener('focusin', closeIfOutside);
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      window.removeEventListener('pointerdown', closeIfOutside, true);
      window.removeEventListener('focusin', closeIfOutside);
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  useEffect(() => {
    if (!open || catalog) return;
    const controller = new AbortController();
    setCatalogError(null);
    void Promise.all([
      api.listManagedAgents(controller.signal),
      api.listManagedSkills(controller.signal),
      api.listManagedPlugins(controller.signal),
    ])
      .then(([agents, skills, plugins]) => setCatalog({ agents, skills, plugins }))
      .catch((caught) => {
        if (!controller.signal.aborted) {
          setCatalogError(caught instanceof Error ? caught.message : String(caught));
        }
      });
    return () => controller.abort();
  }, [api, catalog, open]);

  const categories = useMemo<Category[]>(() => {
    const resourceItem = (
      kind: ComposerContextKind,
      resourceId: string,
      label: string,
      detail?: string,
    ): CatalogItem => ({
      key: `${kind}:${resourceId}`,
      label,
      detail,
      item: { kind, resource_id: resourceId, label },
    });
    return [
      { id: 'attachments', label: t('composer.attachments'), Icon: UploadIcon },
      {
        id: 'agents',
        label: t('composer.agents'),
        Icon: PersonIcon,
        items: (catalog?.agents ?? [])
          .filter((agent) => agent.enabled !== false && agent.status !== 'disabled')
          .map((agent) =>
            resourceItem(
              'agent',
              agent.id,
              `@${agent.display_name?.trim() || agent.name}`,
              agent.model_name ?? undefined,
            ),
          ),
      },
      {
        id: 'skills',
        label: t('composer.skills'),
        Icon: MagicWandIcon,
        items: (catalog?.skills ?? [])
          .filter((skill) => skill.status === 'active')
          .map((skill) => resourceItem('skill', skill.id, skill.name, skill.description)),
      },
      {
        id: 'plugins',
        label: t('composer.plugins'),
        Icon: ComponentInstanceIcon,
        items: (catalog?.plugins ?? [])
          .filter((plugin) => plugin.enabled && plugin.discovered)
          .map((plugin) => resourceItem('plugin', plugin.id, plugin.name, plugin.version)),
      },
      {
        id: 'commands',
        label: t('composer.commands'),
        Icon: SlashIcon,
        items: COMMANDS.map((command) =>
          resourceItem('command', command.id, command.id, t(command.descriptionKey)),
        ),
      },
      {
        id: 'threads',
        label: t('composer.existingThreads'),
        Icon: ChatBubbleIcon,
        items: conversations
          .filter((conversation) => conversation.id !== excludedConversationId)
          .map((conversation) =>
            resourceItem('thread', conversation.id, conversation.title, conversation.summary ?? undefined),
          ),
      },
    ];
  }, [catalog, conversations, excludedConversationId, t]);

  function close() {
    setOpen(false);
    setExpanded(null);
  }

  function pick(item: ComposerContextItem) {
    onAdd(item);
    close();
  }

  function handleFiles(files: FileList | null) {
    for (const file of Array.from(files ?? [])) {
      onAdd({
        kind: 'attachment',
        resource_id: `file:${file.name}:${file.size}:${file.lastModified}`,
        label: file.name,
        metadata: {
          mime_type: file.type || 'application/octet-stream',
          size_bytes: file.size,
          last_modified_ms: file.lastModified,
        },
      });
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
    close();
  }

  return (
    <div className="plus-menu-anchor" ref={anchorRef}>
      <button
        className={compact ? 'composer-plus-compact' : 'picker-chip composer-plus-button'}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('composer.addContext')}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <PlusIcon aria-hidden="true" />
        {!compact ? t('composer.add') : null}
      </button>
      {open ? (
        <div className="plus-menu" role="menu" aria-label={t('composer.addContext')}>
          <div className="plus-menu-header">{t('composer.addContext')}</div>
          {categories.map(({ id, label, Icon, items }) => (
            <div className="plus-menu-group" key={id}>
              <button
                className={`plus-menu-category${expanded === id ? ' expanded' : ''}`}
                type="button"
                aria-expanded={expanded === id}
                onClick={() => setExpanded((current) => (current === id ? null : id))}
              >
                <Icon aria-hidden="true" />
                <span>{label}</span>
                <ChevronRightIcon className="chevron" aria-hidden="true" />
              </button>
              {expanded === id ? (
                <div className="plus-menu-items">
                  {id === 'attachments' ? (
                    <>
                      <button
                        className="plus-menu-item"
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                      >
                        <b><ImageIcon aria-hidden="true" />{t('composer.filesAndPhotos')}</b>
                        <small>{t('composer.filesAndPhotosDescription')}</small>
                      </button>
                      <button className="plus-menu-item" type="button" disabled>
                        <b><CameraIcon aria-hidden="true" />{t('composer.screenshot')}</b>
                        <small>{t('composer.screenshotUnavailable')}</small>
                      </button>
                    </>
                  ) : items?.length ? (
                    items.map((item) => (
                      <button
                        className="plus-menu-item"
                        type="button"
                        key={item.key}
                        onClick={() => pick(item.item)}
                      >
                        <b>{item.label}</b>
                        {item.detail ? <small>{item.detail}</small> : null}
                      </button>
                    ))
                  ) : (
                    <div className="plus-menu-empty">
                      {catalogError ?? (catalog ? t('composer.noResources') : t('composer.loadingResources'))}
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        hidden
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => handleFiles(event.target.files)}
      />
    </div>
  );
}
