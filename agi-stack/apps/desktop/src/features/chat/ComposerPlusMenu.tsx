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
} from '../../types';
import { openFilesWithDesktopDialog } from '../runtime/nativeFileBridge';
import {
  loadComposerCatalog,
  type ComposerCatalog,
  type ComposerCatalogClient,
} from './composerCatalogModel';
import {
  desktopScreenshotFile,
  readDesktopScreenshotPreview,
  type DesktopScreenshotPreview,
} from './desktopScreenshotModel';

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
  id:
    | 'attachments'
    | 'agents'
    | 'agentDefinitions'
    | 'subagents'
    | 'skills'
    | 'plugins'
    | 'commands'
    | 'threads';
  label: string;
  Icon: typeof UploadIcon;
  items?: CatalogItem[];
};

type ComposerPlusMenuProps = {
  api: ComposerCatalogClient;
  conversations: readonly AgentConversation[];
  excludedConversationId?: string | null;
  compact?: boolean;
  onAdd: (item: ComposerContextItem) => void;
  onUploadFiles: (files: File[]) => void | Promise<void>;
  uploadingFileCount?: number;
};

export function ComposerPlusMenu({
  api,
  conversations,
  excludedConversationId,
  compact = false,
  onAdd,
  onUploadFiles,
  uploadingFileCount = 0,
}: ComposerPlusMenuProps) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<Category['id'] | null>(null);
  const [catalog, setCatalog] = useState<ComposerCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [screenshotPreview, setScreenshotPreview] =
    useState<DesktopScreenshotPreview | null>(null);
  const [screenshotBusy, setScreenshotBusy] = useState(false);
  const [screenshotError, setScreenshotError] = useState<string | null>(null);
  const [filePickerBusy, setFilePickerBusy] = useState(false);
  const [filePickerError, setFilePickerError] = useState<string | null>(null);
  const anchorRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const attachmentButtonRef = useRef<HTMLButtonElement>(null);
  const screenshotButtonRef = useRef<HTMLButtonElement>(null);
  const captureCurrentDisplay = window.__MEMSTACK_DESKTOP__?.captureCurrentDisplay;

  useEffect(() => {
    if (!open) return;
    const closeIfOutside = (event: Event) => {
      const target = event.target;
      if (target instanceof Node && !anchorRef.current?.contains(target)) close();
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      close(true);
    };
    window.addEventListener('pointerdown', closeIfOutside, true);
    window.addEventListener('focusin', closeIfOutside);
    document.addEventListener('keydown', closeOnEscape, true);
    return () => {
      window.removeEventListener('pointerdown', closeIfOutside, true);
      window.removeEventListener('focusin', closeIfOutside);
      document.removeEventListener('keydown', closeOnEscape, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open || catalog) return;
    const controller = new AbortController();
    setCatalogError(null);
    void loadComposerCatalog(api, controller.signal)
      .then(setCatalog)
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
      metadata?: ComposerContextItem['metadata'],
      keyScope: string = kind,
    ): CatalogItem => ({
      key: `${keyScope}:${resourceId}`,
      label,
      detail,
      item: { kind, resource_id: resourceId, label, ...(metadata ? { metadata } : {}) },
    });
    return [
      { id: 'attachments', label: t('composer.attachments'), Icon: UploadIcon },
      {
        id: 'agents',
        label: t('composer.agents'),
        Icon: PersonIcon,
        items: (catalog?.workspaceAgents ?? [])
          .filter((agent) => agent.is_active)
          .map((agent) =>
            resourceItem(
              'agent',
              agent.agent_id,
              `@${agent.display_name?.trim() || agent.agent_id}`,
              agent.label?.trim() || agent.description?.trim() || undefined,
              {
                mention_target: true,
                workspace_agent_id: agent.id,
              },
              'workspace-agent',
            ),
          ),
      },
      {
        id: 'agentDefinitions',
        label: t('composer.agentDefinitions'),
        Icon: PersonIcon,
        items: (catalog?.agents ?? [])
          .filter((agent) => agent.enabled !== false && agent.status !== 'disabled')
          .map((agent) =>
            resourceItem(
              'agent',
              agent.id,
              agent.display_name?.trim() || agent.name,
              agent.model_name ?? undefined,
              {
                mention_target: false,
                execution_slot: 'agent',
                execution_agent_id: agent.id,
              },
              'agent-definition',
            ),
          ),
      },
      {
        id: 'subagents',
        label: t('composer.subagents'),
        Icon: PersonIcon,
        items: (catalog?.subagents ?? [])
          .filter((agent) => agent.enabled)
          .map((agent) =>
            resourceItem(
              'agent',
              agent.id,
              agent.display_name?.trim() || agent.name,
              agent.model ?? undefined,
              {
                mention_target: false,
                execution_slot: 'subagent',
                execution_subagent_name: agent.name,
              },
              'subagent',
            ),
          ),
      },
      {
        id: 'skills',
        label: t('composer.skills'),
        Icon: MagicWandIcon,
        items: (catalog?.skills ?? [])
          .filter((skill) => skill.status === 'active')
          .map((skill) =>
            resourceItem('skill', skill.id, skill.name, skill.description, {
              execution_slot: 'skill',
              execution_skill_name: skill.name,
            }),
          ),
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
          resourceItem('command', command.id, command.id, t(command.descriptionKey), {
            execution_slot: 'command',
          }),
        ),
      },
      {
        id: 'threads',
        label: t('composer.existingThreads'),
        Icon: ChatBubbleIcon,
        items: conversations
          .filter((conversation) => conversation.id !== excludedConversationId)
          .map((conversation) =>
            resourceItem(
              'thread',
              conversation.id,
              conversation.title,
              conversation.summary ?? undefined,
            ),
          ),
      },
    ];
  }, [catalog, conversations, excludedConversationId, t]);

  function openMenu() {
    setCatalog(null);
    setCatalogError(null);
    setOpen(true);
  }

  function close(restoreFocus = false) {
    setOpen(false);
    setExpanded(null);
    setScreenshotPreview(null);
    setScreenshotError(null);
    setFilePickerError(null);
    if (restoreFocus) {
      window.requestAnimationFrame(() => triggerRef.current?.focus());
    }
  }

  function pick(item: ComposerContextItem) {
    onAdd(item);
    close();
  }

  async function pickAttachmentFiles() {
    setFilePickerBusy(true);
    setFilePickerError(null);
    try {
      const result = await openFilesWithDesktopDialog('attachment');
      if (result.status === 'selected') {
        await onUploadFiles([...result.files]);
      }
    } catch (caught) {
      setFilePickerError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setFilePickerBusy(false);
      window.requestAnimationFrame(() => attachmentButtonRef.current?.focus());
    }
  }

  async function captureScreenshot() {
    if (!captureCurrentDisplay) return;
    setScreenshotBusy(true);
    setScreenshotError(null);
    try {
      const capture = await captureCurrentDisplay();
      setScreenshotPreview(readDesktopScreenshotPreview(capture));
    } catch (caught) {
      setScreenshotError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setScreenshotBusy(false);
    }
  }

  async function confirmScreenshot() {
    if (!screenshotPreview) return;
    setScreenshotBusy(true);
    setScreenshotError(null);
    try {
      const file = desktopScreenshotFile(screenshotPreview);
      await onUploadFiles([file]);
      close(true);
    } catch (caught) {
      setScreenshotError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setScreenshotBusy(false);
    }
  }

  function cancelScreenshot() {
    setScreenshotPreview(null);
    setScreenshotError(null);
    window.requestAnimationFrame(() => screenshotButtonRef.current?.focus());
  }

  return (
    <div className="plus-menu-anchor" ref={anchorRef}>
      <button
        ref={triggerRef}
        className={compact ? 'composer-plus-compact' : 'picker-chip composer-plus-button'}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('composer.addContext')}
        onClick={() => (open ? close() : openMenu())}
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
                        ref={attachmentButtonRef}
                        className="plus-menu-item"
                        type="button"
                        disabled={filePickerBusy || uploadingFileCount > 0}
                        onClick={() => void pickAttachmentFiles()}
                      >
                        <b><ImageIcon aria-hidden="true" />{t('composer.filesAndPhotos')}</b>
                        <small>{t('composer.filesAndPhotosDescription')}</small>
                      </button>
                      {filePickerError ? (
                        <div className="plus-menu-empty" role="alert">
                          {t('composer.filePickerFailed', { error: filePickerError })}
                        </div>
                      ) : null}
                      <button
                        ref={screenshotButtonRef}
                        className="plus-menu-item"
                        type="button"
                        disabled={
                          !captureCurrentDisplay ||
                          screenshotBusy ||
                          uploadingFileCount > 0
                        }
                        onClick={() => void captureScreenshot()}
                      >
                        <b><CameraIcon aria-hidden="true" />{t('composer.screenshot')}</b>
                        <small>
                          {captureCurrentDisplay
                            ? t('composer.screenshotDescription')
                            : t('composer.screenshotUnavailable')}
                        </small>
                      </button>
                      {screenshotError ? (
                        <div className="plus-menu-empty" role="alert">
                          {t('composer.screenshotFailed', { error: screenshotError })}
                        </div>
                      ) : null}
                      {uploadingFileCount ? (
                        <div className="plus-menu-empty" role="status" aria-live="polite">
                          {t('composer.uploadingFiles', { count: uploadingFileCount })}
                        </div>
                      ) : null}
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
                      {catalogError ??
                        (catalog ? t('composer.noResources') : t('composer.loadingResources'))}
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          ))}
          {screenshotPreview ? (
            <section
              className="desktop-screenshot-preview"
              role="dialog"
              aria-modal="true"
              aria-labelledby="desktop-screenshot-preview-title"
            >
              <strong id="desktop-screenshot-preview-title">
                {t('composer.screenshotPreviewTitle')}
              </strong>
              <img
                src={screenshotPreview.dataUrl}
                alt={t('composer.screenshotPreviewAlt')}
              />
              <small>
                {t('composer.screenshotPreviewSize', {
                  width: screenshotPreview.width,
                  height: screenshotPreview.height,
                })}
              </small>
              <div>
                <button
                  type="button"
                  disabled={screenshotBusy}
                  onClick={cancelScreenshot}
                >
                  {t('composer.screenshotCancel')}
                </button>
                <button
                  type="button"
                  disabled={screenshotBusy}
                  onClick={() => void confirmScreenshot()}
                >
                  {t('composer.screenshotConfirm')}
                </button>
              </div>
            </section>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
