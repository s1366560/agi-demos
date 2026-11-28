import type { CommandInfo, SkillResponse, SlashItem } from '../../../../../web/src/types/agent';
import { usePageVoiceControls } from './WebVoiceControls';
import {readChatCatalog} from './chatCatalog';
import { LlmOverrideView } from '../web/chat/LlmOverrideView';
import type { LLMConfigOverrides } from '../../../../../web/src/types/memory';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { BookOpen, ListChecks, Paperclip, Terminal, Zap } from 'lucide-react';

import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import type { PromptTemplateData } from '../../../../../web/src/services/templateService';
import { AttachmentChip } from '../web/chat/AttachmentChip';
import { ComposerPlusMenuView, type MenuEntry } from '../web/chat/ComposerPlusMenuView';
import { ModelSwitchView } from '../web/chat/ModelSwitchView';
import { PermissionModeSwitcherView } from '../web/chat/PermissionModeSwitcherView';
import { PromptTemplateLibraryView } from '../web/chat/PromptTemplateLibraryView';
import { SendControl } from '../web/chat/SendControl';
import { ThinkingLevelSwitcherView } from '../web/chat/ThinkingLevelSwitcherView';
import type { AgentPermissionMode, AgentThinkingLevel } from '../web/chat/composerOptions';
import type { Chat } from './useChat';

interface MenuCatalog {
  commands: CommandInfo[];
  skills: SkillResponse[];
}
interface Settings {
  llm_overrides: LLMConfigOverrides;
  approval_mode: AgentPermissionMode;
  reasoning_effort: AgentThinkingLevel;
  llm_model_override: string | null;
  mode: 'plan' | 'build';
}
interface Models {
  models: string[];
  default_model: string | null;
}

export function WebComposerControls({
  scope,
  chat,
  onPlanModeChange, onSlashSelect, onSubmit,
}: {
  scope: RichPageContext;
  chat: Chat;
  onSlashSelect: (item:SlashItem)=>void;
  onSubmit:()=>void;
  onPlanModeChange: (active: boolean) => void;
}) {
  const { t } = useTranslation();
  const input = useRef<HTMLInputElement>(null);
  const [menu, setMenu] = useState(false);
  const [catalog, setCatalog] = useState<MenuCatalog>({ commands: [], skills: [] });
  const [fetching, setFetching] = useState(false);
  const overrideQueue = useRef(Promise.resolve());
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [templates, setTemplates] = useState<PromptTemplateData[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [settings, setSettings] = useState<Settings>();
  const [models, setModels] = useState<Models>();
  const [loadingModels, setLoadingModels] = useState(false);
  const [saving, setSaving] = useState(false);
  const voice = usePageVoiceControls(chat, !!scope.voiceAvailable);
  const available = scope.commands;
  const isCloud = (chat.selectedRow?.execution_target ?? chat.target) === 'cloud';
  const selected = chat.selected || null;
  const requests = useRef<AbortController | null>(null);
  const report = useRef(chat.report);
  report.current = chat.report;
  useEffect(() => {
    const controller = new AbortController();
    requests.current = controller;
    setSettings(undefined);
    setSaving(false);
    setLoadingModels(false);
    if (selected && available.includes('chat-composer-read')) {
      void window.memstack
        .invoke('chat-composer-read', { conversation_id: selected }, { signal: controller.signal })
        .then((data) => {
          if (!controller.signal.aborted) setSettings(data as Settings);
        })
        .catch((error) => {
          if (!controller.signal.aborted) report.current(error);
        });
    }
    return () => controller.abort();
  }, [selected, available]);

  useEffect(() => {
    if (!templatesOpen || !available.includes('chat-project-context')) return;
    const controller = new AbortController();
    setLoadingTemplates(true);
    void window.memstack
      .invoke('chat-project-context', { view: 'templates' }, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted)
          setTemplates((data as { templates: PromptTemplateData[] }).templates);
      })
      .catch((error) => {
        if (!controller.signal.aborted) report.current(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingTemplates(false);
      });
    return () => controller.abort();
  }, [templatesOpen, available]);

  useEffect(() => {
    if (!menu || !available.includes('chat-project-context')) return;
    const controller = new AbortController();
    setFetching(true);
    void readChatCatalog(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setCatalog(data as MenuCatalog);
      })
      .catch((error) => {
        if (!controller.signal.aborted) report.current(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setFetching(false);
      });
    return () => controller.abort();
  }, [menu, available]);
  function updateOverrides(value: LLMConfigOverrides) {
    const signal = requests.current?.signal;
    if (!signal || !selected || !available.includes('chat-composer-save')) return;
    overrideQueue.current = overrideQueue.current
      .then(async () => {
        if (signal.aborted) return;
        const data = await window.memstack.invoke(
          'chat-composer-save',
          { conversation_id: selected, llm_overrides: value },
          { signal }
        );
        if (!signal.aborted) setSettings(data as Settings);
      })
      .catch((error) => {
        if (!signal.aborted) report.current(error);
      });
  }
  async function save<K extends keyof Settings>(key: K, value: Settings[K]) {
    const signal = requests.current?.signal;
    if (!selected || !signal || saving || !available.includes('chat-composer-save')) return;
    setSaving(true);
    try {
      const result = await window.memstack.invoke(
        'chat-composer-save',
        { conversation_id: selected, [key]: value },
        { signal }
      );
      if (!signal.aborted) setSettings(result as Settings);
    } catch (error) {
      if (!signal.aborted) chat.report(error);
    } finally {
      if (!signal.aborted) setSaving(false);
    }
  }
  async function loadModels() {
    const signal = requests.current?.signal;
    if (!signal || loadingModels || !available.includes('chat-models')) return;
    setLoadingModels(true);
    try {
      const result = await window.memstack.invoke('chat-models', {}, { signal });
      if (!signal.aborted) setModels(result as Models);
    } catch (error) {
      if (!signal.aborted) chat.report(error);
    } finally {
      if (!signal.aborted) setLoadingModels(false);
    }
  }
  const locked = chat.busy || saving || !settings || !available.includes('chat-composer-save');
  useEffect(() => {
    onPlanModeChange(settings?.mode === 'plan');
  }, [settings?.mode, onPlanModeChange]);
  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if (
        event.key !== 'Tab' ||
        !event.shiftKey ||
        locked ||
        !(event.target instanceof HTMLTextAreaElement) ||
        event.target.id !== 'agent-message-input'
      )
        return;
      event.preventDefault();
      void save('mode', settings?.mode === 'plan' ? 'build' : 'plan');
    }
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  });
  const entries: MenuEntry[] = [
    {
      id: 'action-attach',
      section: 'actions',
      label: t('agent.inputBar.attachFiles', 'Attach files (or drag & drop)'),
      keywords: 'attach upload file attachment paperclip',
      icon: <Paperclip size={16} />,
      disabled: !isCloud || chat.busy || !available.includes('chat-upload') || chat.files.length >= 10,
      active: chat.files.length > 0,
      onSelect: () => input.current?.click(),
    },
    {
      id: 'action-templates',
      section: 'actions',
      label: t('agent.inputBar.templates', 'Prompt templates'),
      keywords: 'template prompt library book',
      icon: <BookOpen size={16} />,
      onSelect: () => setTemplatesOpen(true),
    },
    ...voice.entries,
    {
      id: 'action-plan-mode',
      section: 'actions',
      label:
        settings?.mode === 'plan'
          ? t('agent.inputBar.exitPlanMode', 'Exit Plan Mode (Shift+Tab)')
          : t('agent.inputBar.enterPlanMode', 'Enter Plan Mode (Shift+Tab)'),
      keywords: 'plan mode list checks',
      icon: <ListChecks size={16} />,
      disabled: locked,
      active: settings?.mode === 'plan',
      onSelect: () => void save('mode', settings?.mode === 'plan' ? 'build' : 'plan'),
    },
    ...catalog.commands.map((cmd) => ({
      id: 'command-' + cmd.name,
      section: 'commands' as const,
      label: '/' + cmd.name,
      description: cmd.description,
      keywords: cmd.name,
      icon: <Terminal size={16} />,
      onSelect: () => onSlashSelect({kind:'command',data:cmd}),
    })),
    ...catalog.skills.map((skill) => ({
      id: 'skill-' + skill.id,
      section: 'commands' as const,
      label: '/' + skill.name,
      description: skill.description,
      keywords: skill.name,
      icon: <Zap size={16} />,
      onSelect: () => onSlashSelect({kind:'skill',data:skill}),
    })),
  ];
  return (
    <>
      <input
        type="file"
        multiple
        data-testid="chat-file-input"
        ref={input}
        hidden
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files ?? []);
          event.currentTarget.value = '';
          if (files.length) void chat.attachFiles(files);
        }}
      />
      {chat.files.map((file) => (
        <AttachmentChip
          key={file.id}
          file={{
            id: file.id,
            filename: file.filename,
            mimeType: file.mime_type,
            sizeBytes: file.size_bytes,
            status: 'uploaded',
            progress: 100,
          }}
          onRemove={chat.removeFile}
          onRetry={() => {}}
        />
      ))}
      <div
        data-testid="input-toolbar"
        className="mt-auto flex min-w-0 flex-shrink-0 flex-wrap items-center gap-1.5 px-2 pt-1 pb-1.5 sm:px-3"
      >
        <div className="flex min-w-0 flex-wrap items-center gap-1">
          <ComposerPlusMenuView
            commandsLoading={fetching}
            extraAction={
              <LlmOverrideView
                variant="row"
                disabled={locked}
                readOverrides={() => settings?.llm_overrides}
                onChange={updateOverrides}
              />
            }
            entries={entries}
            isOpen={menu}
            setIsOpen={setMenu}
            disabled={chat.busy}
          />
          <div className="hidden min-[460px]:block w-px h-4 bg-slate-200 dark:bg-slate-700 mx-0.5" />
          <PermissionModeSwitcherView
            mode={settings?.approval_mode ?? 'ask'}
            failed={false}
            disabled={locked}
            save={(value) => void save('approval_mode', value)}
          />
          <ThinkingLevelSwitcherView
            level={settings?.reasoning_effort ?? 'default'}
            disabled={locked}
            save={(value) => void save('reasoning_effort', value)}
          />
          <ModelSwitchView
            activeModelOverride={settings?.llm_model_override ?? null}
            defaultModel={models?.default_model ?? null}
            visibleModels={models?.models ?? []}
            modelsLoading={loadingModels}
            disabled={locked || !available.includes('chat-models')}
            onOpen={() => void loadModels()}
            onSelect={(value) => void save('llm_model_override', value)}
          />
        </div>
        <div
          data-testid="input-toolbar-actions"
          className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1"
        >
          {!!chat.draft.length && (
            <span
              className={`text-xs font-medium transition-colors tabular-nums ${chat.draft.length > 4000 ? 'text-amber-500' : 'text-slate-400'}`}
            >
              {chat.draft.length.toLocaleString()}
            </span>
          )}
          <SendControl
            canSend={!!chat.draft.trim() && !chat.busy && (isCloud || chat.hasDevice)}
            isStreaming={!!chat.run}
            handleSend={onSubmit}
            onAbort={() => void chat.stop()}
          />
        </div>
      </div>
      {voice.panel}
      <PromptTemplateLibraryView
        onSelect={chat.setDraft}
        visible={templatesOpen}
        onClose={() => setTemplatesOpen(false)}
        customTemplates={templates}
        customLoading={loadingTemplates}
      />
    </>
  );
}
