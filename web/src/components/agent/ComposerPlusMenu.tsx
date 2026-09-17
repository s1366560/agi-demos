/**
 * ComposerPlusMenu - the consolidated "+" menu for the chat composer.
 *
 * Every composer function that used to live as a standalone toolbar button is
 * collected here: quick actions (attachments, templates, voice, plan mode,
 * LLM parameters) plus the full plugin / agent / command catalogs. A search
 * field at the top filters all entries dynamically while typing.
 */

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { useTranslation } from 'react-i18next';

import {
  AppWindow,
  BookOpen,
  Bot,
  Check,
  ListChecks,
  Loader2,
  Mic,
  Paperclip,
  Phone,
  Plus,
  Search,
  Terminal,
  Zap,
} from 'lucide-react';

import { useDefinitions, useListDefinitions } from '@/stores/agentDefinitions';
import { useCanvasStore } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { useMCPAppStore } from '@/stores/mcpAppStore';

import { commandAPI } from '@/services/commandService';
import { skillAPI } from '@/services/skillService';


import type { ActiveModelCapabilities } from '@/hooks/useActiveModelCapabilities';

import { LlmOverridePopover } from './chat/LlmOverridePopover';

import type { CommandInfo, SkillResponse, SlashItem } from '@/types/agent';

import type { PendingAttachment } from './FileUploader';

type MenuSectionKey = 'actions' | 'plugins' | 'agents' | 'commands';

interface MenuEntry {
  id: string;
  section: MenuSectionKey;
  label: string;
  description?: string | undefined;
  /** Extra search surface (e.g. category, server name) - never displayed. */
  keywords: string;
  icon: ReactNode;
  disabled?: boolean | undefined;
  /** Check state shown on the right edge (active agent, plan mode). */
  active?: boolean | undefined;
  onSelect: () => void;
}

const SECTION_ORDER: MenuSectionKey[] = ['actions', 'plugins', 'agents', 'commands'];

export interface ComposerPlusMenuProps {
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  capabilities: ActiveModelCapabilities;
  attachments: readonly PendingAttachment[];
  setTemplateLibraryVisible: React.Dispatch<React.SetStateAction<boolean>>;
  isListening: boolean;
  voiceCallStatus: string;
  toggleVoiceInput: () => Promise<void>;
  handleVoiceCall: () => void;
  onTogglePlanMode?: (() => void) | undefined;
  isPlanMode?: boolean | undefined;
  onAgentSelect?: ((agentId: string) => void) | undefined;
  activeAgentId?: string | undefined;
  /** Reuses the InputBar slash-command selection (skill chip or /command send). */
  onSlashSelect: (item: SlashItem) => void;
  projectId?: string | undefined;
  activeConversationId: string | null;
  disabled?: boolean | undefined;
}

export const ComposerPlusMenu: React.FC<ComposerPlusMenuProps> = ({
  fileInputRef,
  capabilities,
  attachments,
  setTemplateLibraryVisible,
  isListening,
  voiceCallStatus,
  toggleVoiceInput,
  handleVoiceCall,
  onTogglePlanMode,
  isPlanMode,
  onAgentSelect,
  activeAgentId,
  onSlashSelect,
  projectId,
  activeConversationId,
  disabled = false,
}) => {
  const { t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [focusIndex, setFocusIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const itemRefs = useRef<Map<number, HTMLButtonElement>>(new Map());

  // --- Data sources -------------------------------------------------------
  const definitions = useDefinitions();
  const listDefinitions = useListDefinitions();

  const apps = useMCPAppStore((s) => s.apps);
  const pluginsLoading = useMCPAppStore((s) => s.loading);
  const fetchApps = useMCPAppStore((s) => s.fetchApps);

  const [commands, setCommands] = useState<CommandInfo[]>([]);
  const [skills, setSkills] = useState<SkillResponse[]>([]);
  const [commandsLoading, setCommandsLoading] = useState(false);
  const [definitionsLoading, setDefinitionsLoading] = useState(false);

  // Load catalogs when the menu opens (agents load eagerly only when empty).
  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCommandsLoading(true);
    void Promise.all([
      commandAPI.list().catch(() => ({ commands: [] as CommandInfo[] })),
      skillAPI.list({ status: 'active', limit: 50 }).catch(() => ({ skills: [] as SkillResponse[] })),
    ]).then(([cmdRes, skillRes]) => {
      if (cancelled) return;
      setCommands(Array.isArray(cmdRes.commands) ? cmdRes.commands : []);
      setSkills(Array.isArray(skillRes.skills) ? skillRes.skills : []);
      setCommandsLoading(false);
    });

    if (definitions.length === 0) {
      setDefinitionsLoading(true);
      listDefinitions()
        .catch((err: unknown) => {
          console.error('ComposerPlusMenu: load agent definitions failed', err);
        })
        .finally(() => {
          if (!cancelled) setDefinitionsLoading(false);
        });
    }

    if (projectId) {
      void fetchApps(projectId);
    }

    return () => {
      cancelled = true;
    };
  }, [isOpen, definitions.length, listDefinitions, fetchApps, projectId]);

  // Reset transient state on open.
  useEffect(() => {
    if (isOpen) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setQuery('');
      setFocusIndex(0);
      // Focus after the menu is attached so autoFocus semantics apply on every open.
      requestAnimationFrame(() => {
        searchRef.current?.focus();
      });
    }
  }, [isOpen]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  const closeMenu = useCallback(() => {
    setIsOpen(false);
  }, []);

  const enabledDefinitions = useMemo(() => definitions.filter((d) => d.enabled), [definitions]);

  const pluginList = useMemo(() => {
    if (!projectId) return [];
    return Object.values(apps).filter(
      (app) => app.status === 'ready' && app.project_id === projectId
    );
  }, [apps, projectId]);

  // --- Entry assembly -----------------------------------------------------
  // Entries never close over refs: the file-picker ref is only touched inside
  // the JSX event handlers (see the attach special case below).
  const entries = useMemo<MenuEntry[]>(() => {
    const actionEntries: MenuEntry[] = [
      {
        id: 'action-attach',
        section: 'actions',
        label: t('agent.inputBar.attachFiles', 'Attach files (or drag & drop)'),
        keywords: 'attach upload file attachment paperclip',
        icon: <Paperclip size={16} />,
        disabled: !capabilities.supportsAttachment,
        active: attachments.length > 0,
        onSelect: () => undefined,
      },
      {
        id: 'action-templates',
        section: 'actions',
        label: t('agent.inputBar.templates', 'Prompt templates'),
        keywords: 'template prompt library book',
        icon: <BookOpen size={16} />,
        onSelect: () => {
          setTemplateLibraryVisible(true);
        },
      },
      {
        id: 'action-voice-input',
        section: 'actions',
        label: isListening
          ? t('agent.inputBar.stopVoice', 'Stop voice input')
          : t('agent.inputBar.startVoice', 'Voice input'),
        keywords: 'voice mic speech dictation',
        icon: <Mic size={16} />,
        disabled: voiceCallStatus !== 'idle',
        active: isListening,
        onSelect: () => {
          void toggleVoiceInput();
        },
      },
      {
        id: 'action-voice-call',
        section: 'actions',
        label:
          voiceCallStatus !== 'idle'
            ? t('agent.voiceCall.endCall', 'End call')
            : t('agent.inputBar.startVoiceCall', 'Start voice call'),
        keywords: 'voice call phone realtime',
        icon: <Phone size={16} />,
        active: voiceCallStatus !== 'idle',
        onSelect: () => {
          handleVoiceCall();
        },
      },
    ];

    if (onTogglePlanMode) {
      actionEntries.push({
        id: 'action-plan-mode',
        section: 'actions',
        label: isPlanMode
          ? t('agent.inputBar.exitPlanMode', 'Exit Plan Mode (Shift+Tab)')
          : t('agent.inputBar.enterPlanMode', 'Enter Plan Mode (Shift+Tab)'),
        keywords: 'plan mode list checks',
        icon: <ListChecks size={16} />,
        active: isPlanMode,
        onSelect: () => {
          onTogglePlanMode();
        },
      });
    }

    const pluginEntries: MenuEntry[] = pluginList.map((app) => ({
      id: `plugin-${app.id}`,
      section: 'plugins' as const,
      label: app.ui_metadata.title || app.tool_name,
      description: app.server_name,
      keywords: `${app.server_name} ${app.tool_name} plugin mcp app canvas`,
      icon: <AppWindow size={16} />,
      onSelect: () => {
        const tabId = `mcp-app-${app.id}`;
        useCanvasStore.getState().openTab({
          id: tabId,
          title: app.ui_metadata.title || app.tool_name,
          type: 'mcp-app' as const,
          content: '',
          mcpAppId: app.id,
          mcpResourceUri: app.ui_metadata.resourceUri,
          mcpServerName: app.server_name,
          mcpProjectId: projectId,
          mcpToolName: app.tool_name,
          mcpAppUiMetadata: app.ui_metadata as unknown as Record<string, unknown>,
        });
        useLayoutModeStore.getState().setMode('canvas');
      },
    }));

    const agentEntries: MenuEntry[] = onAgentSelect
      ? enabledDefinitions.map((agent) => ({
          id: `agent-${agent.id}`,
          section: 'agents' as const,
          label: agent.display_name || agent.name,
          description:
            agent.source === 'database'
              ? t('agent.plusMenu.agentFromDatabase', 'Custom agent')
              : t('agent.plusMenu.agentBuiltin', 'Built-in agent'),
          keywords: `agent ${agent.name} ${agent.display_name ?? ''}`,
          icon: <Bot size={16} />,
          active: agent.id === activeAgentId,
          onSelect: () => {
            onAgentSelect(agent.id);
          },
        }))
      : [];

    const commandEntries: MenuEntry[] = [
      ...commands.map((cmd) => ({
        id: `command-${cmd.name}`,
        section: 'commands' as const,
        label: `/${cmd.name}`,
        description: cmd.description,
        keywords: `command slash ${cmd.name} ${cmd.category}`,
        icon: <Terminal size={16} />,
        onSelect: () => {
          onSlashSelect({ kind: 'command' as const, data: cmd });
        },
      })),
      ...skills.map((skill) => ({
        id: `skill-${skill.id}`,
        section: 'commands' as const,
        label: `/${skill.name}`,
        description: skill.description,
        keywords: `skill slash ${skill.name} ${skill.scope}`,
        icon: <Zap size={16} />,
        onSelect: () => {
          onSlashSelect({ kind: 'skill' as const, data: skill });
        },
      })),
    ];

    return [...actionEntries, ...pluginEntries, ...agentEntries, ...commandEntries];
  }, [
    t,
    capabilities.supportsAttachment,
    attachments.length,
    setTemplateLibraryVisible,
    isListening,
    voiceCallStatus,
    toggleVoiceInput,
    handleVoiceCall,
    onTogglePlanMode,
    isPlanMode,
    pluginList,
    projectId,
    onAgentSelect,
    enabledDefinitions,
    activeAgentId,
    commands,
    skills,
    onSlashSelect,
  ]);

  const filteredEntries = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((entry) => {
      const haystack = `${entry.label} ${entry.description ?? ''} ${entry.keywords}`.toLowerCase();
      return haystack.includes(q);
    });
  }, [entries, query]);

  // Clamp keyboard focus when the filtered list shrinks.
  useEffect(() => {
    if (filteredEntries.length === 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      if (focusIndex !== 0) setFocusIndex(0);
      return;
    }
    if (focusIndex >= filteredEntries.length) {
      setFocusIndex(filteredEntries.length - 1);
    }
  }, [filteredEntries.length, focusIndex]);

  // Scroll the focused entry into view.
  useEffect(() => {
    itemRefs.current.get(focusIndex)?.scrollIntoView({ block: 'nearest' });
  }, [focusIndex]);

  const selectEntry = useCallback(
    (entry: MenuEntry) => {
      if (entry.disabled) return;
      entry.onSelect();
      closeMenu();
    },
    [closeMenu]
  );

  const handleSearchKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>) => {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setFocusIndex((prev) =>
          filteredEntries.length === 0
            ? 0
            : Math.min(prev + 1, filteredEntries.length - 1)
        );
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setFocusIndex((prev) => Math.max(prev - 1, 0));
        return;
      }
      if (event.key === 'Enter') {
        const entry = filteredEntries[focusIndex];
        if (entry) {
          event.preventDefault();
          selectEntry(entry);
        }
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        closeMenu();
      }
    },
    [filteredEntries, focusIndex, selectEntry, closeMenu]
  );

  const sectionTitles: Record<MenuSectionKey, string> = useMemo(
    () => ({
      actions: t('agent.plusMenu.groupActions', 'Actions'),
      plugins: t('agent.plusMenu.groupPlugins', 'Plugins'),
      agents: t('agent.plusMenu.groupAgents', 'Agents'),
      commands: t('agent.plusMenu.groupCommands', 'Commands'),
    }),
    [t]
  );

  const sectionEmptyText: Partial<Record<MenuSectionKey, string>> = useMemo(
    () => ({
      plugins: pluginsLoading
        ? t('agent.plusMenu.loading', 'Loading…')
        : t('agent.plusMenu.noPlugins', 'No plugins available'),
      agents: definitionsLoading
        ? t('agent.plusMenu.loading', 'Loading…')
        : t('agent.noAgentsAvailable', 'No agents available'),
      commands: commandsLoading
        ? t('agent.plusMenu.loading', 'Loading…')
        : t('agent.slashCommand.noItems', 'No commands or skills available'),
    }),
    [t, pluginsLoading, definitionsLoading, commandsLoading]
  );

  let renderedIndex = -1;

  return (
    <div className="relative inline-block" ref={containerRef}>
      <button
        type="button"
        onClick={() => {
          if (!disabled) setIsOpen((v) => !v);
        }}
        disabled={disabled}
        title={t('agent.plusMenu.label', 'Add')}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        data-testid="composer-plus-button"
        className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 ${
          disabled
            ? 'cursor-not-allowed text-slate-300 dark:text-slate-600'
            : `text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700/50 ${
                isOpen ? 'text-primary bg-primary/5' : ''
              }`
        }`}
      >
        <Plus size={18} />
      </button>

      {isOpen && (
        <div
          role="menu"
          aria-label={t('agent.plusMenu.title', 'Add')}
          data-testid="composer-plus-menu"
          className="absolute bottom-full left-0 mb-2 z-50 flex w-[min(26rem,calc(100vw-2rem))] flex-col overflow-hidden rounded-lg border border-slate-200 bg-slate-50 shadow-lg shadow-slate-200/40 dark:border-slate-700 dark:bg-slate-800 dark:shadow-slate-950/20"
        >
          {/* Search */}
          <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2 dark:border-slate-700/50">
            <Search size={14} className="shrink-0 text-slate-400" />
            <input
              ref={searchRef}
              type="text"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setFocusIndex(0);
              }}
              onKeyDown={handleSearchKeyDown}
              placeholder={t('agent.plusMenu.searchPlaceholder', 'Search plugins, agents, commands…')}
              aria-label={t('agent.plusMenu.searchPlaceholder', 'Search plugins, agents, commands…')}
              data-testid="composer-plus-search"
              className="w-full bg-transparent text-sm text-slate-800 placeholder:text-content-tertiary focus:outline-none dark:text-slate-100"
            />
          </div>

          {/* Entries */}
          <div className="max-h-[min(24rem,50vh)] overflow-y-auto py-1">
            {filteredEntries.length === 0 ? (
              <div className="px-3 py-4 text-center text-xs text-slate-400">
                {t('agent.slashCommand.noMatch', 'No matches for "{{query}}"', { query })}
              </div>
            ) : (
              SECTION_ORDER.map((section) => {
                const sectionEntries = filteredEntries.filter((e) => e.section === section);
                if (sectionEntries.length === 0) return null;
                return (
                  <div key={section} role="group" aria-label={sectionTitles[section]}>
                    <div
                      role="presentation"
                      className="bg-slate-50/50 px-3 py-1.5 text-2xs font-semibold uppercase tracking-label text-content-tertiary dark:bg-slate-800/50"
                    >
                      {sectionTitles[section]}
                    </div>
                    {section === 'actions' && !query.trim() && (
                      <div className="px-1 py-0.5">
                        <LlmOverridePopover
                          conversationId={activeConversationId}
                          disabled={disabled}
                          capabilities={capabilities}
                          variant="row"
                        />
                      </div>
                    )}
                    {sectionEntries.map((entry) => {
                      renderedIndex += 1;
                      const entryIndex = renderedIndex;
                      const isFocused = entryIndex === focusIndex;
                      return (
                        <button
                          key={entry.id}
                          ref={(el) => {
                            if (el) itemRefs.current.set(entryIndex, el);
                            else itemRefs.current.delete(entryIndex);
                          }}
                          type="button"
                          role="menuitem"
                          disabled={entry.disabled}
                          onClick={() => {
                            if (entry.disabled) return;
                            if (entry.id === 'action-attach') {
                              fileInputRef.current?.click();
                            } else {
                              entry.onSelect();
                            }
                            closeMenu();
                          }}
                          onMouseEnter={() => {
                            setFocusIndex(entryIndex);
                          }}
                          aria-disabled={entry.disabled}
                          className={`w-full text-left px-3 py-2 flex items-center justify-between gap-2 rounded-md text-xs transition-colors duration-150 ${
                            entry.disabled
                              ? 'cursor-not-allowed text-slate-300 dark:text-slate-600'
                              : 'cursor-pointer'
                          } ${
                            isFocused && !entry.disabled
                              ? 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                              : 'text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700'
                          }`}
                        >
                          <div className="flex min-w-0 items-center gap-2.5">
                            <span className="shrink-0 text-slate-400 dark:text-slate-500">
                              {entry.icon}
                            </span>
                            <div className="flex min-w-0 flex-col">
                              <span className="truncate font-medium">{entry.label}</span>
                              {entry.description && (
                                <span className="truncate text-2xs text-slate-400 dark:text-slate-500">
                                  {entry.description}
                                </span>
                              )}
                            </div>
                          </div>
                          {entry.active && (
                            <Check
                              size={16}
                              className="shrink-0 text-blue-600 dark:text-blue-400"
                            />
                          )}
                        </button>
                      );
                    })}
                  </div>
                );
              })
            )}
            {/* Empty catalog sections (only visible when not searching). */}
            {!query.trim() &&
              SECTION_ORDER.map((section) => {
                if (filteredEntries.some((e) => e.section === section)) return null;
                const emptyText = sectionEmptyText[section];
                if (!emptyText) return null;
                return (
                  <div key={`empty-${section}`} role="group" aria-label={sectionTitles[section]}>
                    <div
                      role="presentation"
                      className="bg-slate-50/50 px-3 py-1.5 text-2xs font-semibold uppercase tracking-label text-content-tertiary dark:bg-slate-800/50"
                    >
                      {sectionTitles[section]}
                    </div>
                    <div className="flex items-center justify-center gap-2 px-3 py-3 text-xs italic text-slate-400">
                      {(section === 'plugins' && pluginsLoading) ||
                      (section === 'agents' && definitionsLoading) ||
                      (section === 'commands' && commandsLoading) ? (
                        <Loader2 size={14} className="animate-spin motion-reduce:animate-none" />
                      ) : null}
                      {emptyText}
                    </div>
                  </div>
                );
              })}
          </div>

          {/* Footer hints */}
          <div className="flex items-center gap-3 border-t border-slate-100 px-3 py-1.5 text-2xs text-slate-400 dark:border-slate-700/50">
            <span>
              <kbd className="rounded bg-slate-100 px-1 py-0.5 font-mono dark:bg-slate-700">
                &uarr;&darr;
              </kbd>{' '}
              {t('agent.slashCommand.hintNavigate', 'navigate')}
            </span>
            <span>
              <kbd className="rounded bg-slate-100 px-1 py-0.5 font-mono dark:bg-slate-700">
                Enter
              </kbd>{' '}
              {t('agent.slashCommand.hintSelect', 'select')}
            </span>
            <span>
              <kbd className="rounded bg-slate-100 px-1 py-0.5 font-mono dark:bg-slate-700">
                Esc
              </kbd>{' '}
              {t('agent.slashCommand.hintDismiss', 'dismiss')}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

ComposerPlusMenu.displayName = 'ComposerPlusMenu';
