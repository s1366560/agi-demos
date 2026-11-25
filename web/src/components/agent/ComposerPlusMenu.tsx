/**
 * ComposerPlusMenu - the consolidated "+" menu for the chat composer.
 *
 * Every composer function that used to live as a standalone toolbar button is
 * collected here: quick actions (attachments, templates, voice, plan mode,
 * LLM parameters) plus the full plugin / agent / command catalogs. A search
 * field at the top filters all entries dynamically while typing.
 */

import React, { useEffect, useMemo, useState } from 'react';

import {
  ComposerPlusMenuView,
  type MenuEntry,
} from '@business/agent/ui/web/chat/ComposerPlusMenuView';
import { useTranslation } from 'react-i18next';

import {
  AppWindow,
  BookOpen,
  Bot,
  ListChecks,
  Mic,
  Paperclip,
  Phone,
  Terminal,
  Zap,
} from 'lucide-react';

import { useDefinitions, useListDefinitions } from '@business/agent/ui/web/stores/agentDefinitions';
import { useCanvasStore } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { useMCPAppStore } from '@/stores/mcpAppStore';

import { commandAPI } from '@/services/commandService';
import { skillAPI } from '@business/agent/ui/web/services/skillService';

import type { ActiveModelCapabilities } from '@/hooks/useActiveModelCapabilities';

import { useWebFeatureEnabledV2 } from '@/routes/v2/webFeatureAuthorityV2';

import { LlmOverridePopover } from './chat/LlmOverridePopover';

import type { CommandInfo, SkillResponse, SlashItem } from '@/types/agent';

import type { PendingAttachment } from './FileUploader';

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
  // --- Data sources -------------------------------------------------------
  const definitions = useDefinitions();
  const listDefinitions = useListDefinitions();

  const apps = useMCPAppStore((s) => s.apps);
  const pluginsLoading = useMCPAppStore((s) => s.loading);
  const fetchApps = useMCPAppStore((s) => s.fetchApps);

  const skillsEnabled = useWebFeatureEnabledV2('tenant-skills', 'command');
  const agentsEnabled = useWebFeatureEnabledV2('tenant-agent-definitions', 'command');
  const appsEnabled = useWebFeatureEnabledV2('tenant-mcp-servers', 'command');
  const commandsEnabled = useWebFeatureEnabledV2('tenant-agent-workspace', 'command');
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
      (commandsEnabled
        ? commandAPI.list()
        : Promise.resolve({ commands: [] as CommandInfo[] })
      ).catch(() => ({ commands: [] as CommandInfo[] })),
      (skillsEnabled
        ? skillAPI.list({ status: 'active', limit: 50 })
        : Promise.resolve({ skills: [] as SkillResponse[] })
      ).catch(() => ({ skills: [] as SkillResponse[] })),
    ]).then(([cmdRes, skillRes]) => {
      if (cancelled) return;
      setCommands(Array.isArray(cmdRes.commands) ? cmdRes.commands : []);
      setSkills(Array.isArray(skillRes.skills) ? skillRes.skills : []);
      setCommandsLoading(false);
    });

    if (agentsEnabled && definitions.length === 0) {
      setDefinitionsLoading(true);
      listDefinitions()
        .catch((err: unknown) => {
          console.error('ComposerPlusMenu: load agent definitions failed', err);
        })
        .finally(() => {
          if (!cancelled) setDefinitionsLoading(false);
        });
    }

    if (appsEnabled && projectId) {
      void fetchApps(projectId);
    }

    return () => {
      cancelled = true;
    };
  }, [
    isOpen,
    definitions.length,
    listDefinitions,
    fetchApps,
    projectId,
    skillsEnabled,
    agentsEnabled,
    appsEnabled,
    commandsEnabled,
  ]);

  const enabledDefinitions = useMemo(() => definitions.filter((d) => d.enabled), [definitions]);

  const pluginList = useMemo(() => {
    if (!projectId) return [];
    return Object.values(apps).filter(
      (app) => app.status === 'ready' && app.project_id === projectId
    );
  }, [apps, projectId]);

  // --- Entry assembly -----------------------------------------------------
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
        onSelect: () => fileInputRef.current?.click(),
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

    const planEntries: MenuEntry[] = onTogglePlanMode
      ? [
          {
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
          },
        ]
      : [];

    const pluginEntries: MenuEntry[] = (appsEnabled ? pluginList : []).map((app) => ({
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

    const agentEntries: MenuEntry[] =
      onAgentSelect && agentsEnabled
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
      ...(commandsEnabled ? commands : []).map((cmd) => ({
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
      ...(skillsEnabled ? skills : []).map((skill) => ({
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

    return [...actionEntries, ...planEntries, ...pluginEntries, ...agentEntries, ...commandEntries];
  }, [
    t,
    fileInputRef,
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
    skillsEnabled,
    agentsEnabled,
    appsEnabled,
    commandsEnabled,
    commands,
    skills,
    onSlashSelect,
  ]);

  return (
    <ComposerPlusMenuView
      entries={entries}
      isOpen={isOpen}
      setIsOpen={setIsOpen}
      disabled={disabled}
      pluginsLoading={pluginsLoading}
      definitionsLoading={definitionsLoading}
      commandsLoading={commandsLoading}
      extraAction={
        <LlmOverridePopover
          conversationId={activeConversationId}
          disabled={disabled}
          capabilities={capabilities}
          variant="row"
        />
      }
    />
  );
};
ComposerPlusMenu.displayName = 'ComposerPlusMenu';
