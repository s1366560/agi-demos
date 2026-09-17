import { memo } from 'react';

import { useTranslation } from 'react-i18next';

import { Send, Square, MicOff, PhoneOff } from 'lucide-react';

import type { ActiveModelCapabilities } from '@/hooks/useActiveModelCapabilities';

import { PluginSlotOutlet } from '@/components/plugins/PluginSlotOutlet';
import { LazyButton, LazyTooltip } from '@/components/ui/lazyAntd';

import { ModelSwitchPopover } from './chat/ModelSwitchPopover';
import { VoiceWaveform } from './chat/VoiceWaveform';
import { ComposerPlusMenu } from './ComposerPlusMenu';
import { PermissionModeSwitcher } from './PermissionModeSwitcher';
import { ThinkingLevelSwitcher } from './ThinkingLevelSwitcher';

import type { SlashItem } from '@/types/agent';

import type { PendingAttachment } from './FileUploader';
import type { WebOperationContextV2 } from '../../plugins/webOperationAdmissionV2';

export interface InputToolbarProps {
  /** Ref to the hidden file input */
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  /** Current attachment list (for badge state) */
  attachments: readonly PendingAttachment[];
  /** Model capability flags */
  capabilities: ActiveModelCapabilities;
  /** Template library open action */
  setTemplateLibraryVisible: React.Dispatch<React.SetStateAction<boolean>>;
  /** Voice input state */
  isListening: boolean;
  voiceAnalyser: AnalyserNode | null;
  voiceOperation: WebOperationContextV2 | null;
  toggleVoiceInput: () => Promise<void>;
  /** Voice call state */
  voiceCallStatus: string;
  handleVoiceCall: () => void;
  /** Conversation / project context */
  activeConversationId: string | null;
  projectId?: string | undefined;
  /** Streaming / disabled state */
  isStreaming: boolean;
  disabled?: boolean | undefined;
  /** Plan mode */
  onTogglePlanMode?: (() => void) | undefined;
  isPlanMode?: boolean | undefined;
  /** Agent switcher */
  onAgentSelect?: ((agentId: string) => void) | undefined;
  activeAgentId?: string | undefined;
  /** Slash command / skill selection from the + menu */
  onSlashSelect: (item: SlashItem) => void;
  /** Char count for the input */
  charCount: number;
  /** Whether send button should be enabled */
  canSend: boolean;
  /** Send / abort actions */
  handleSend: () => void;
  onAbort: () => void;
}

export const InputToolbar = memo<InputToolbarProps>(
  ({
    fileInputRef,
    attachments,
    capabilities,
    setTemplateLibraryVisible,
    isListening,
    voiceAnalyser,
    voiceOperation,
    toggleVoiceInput,
    voiceCallStatus,
    handleVoiceCall,
    activeConversationId,
    projectId,
    isStreaming,
    disabled,
    onTogglePlanMode,
    isPlanMode,
    onAgentSelect,
    activeAgentId,
    onSlashSelect,
    charCount,
    canSend,
    handleSend,
    onAbort,
  }) => {
    const { t } = useTranslation();

    return (
      <div
        data-testid="input-toolbar"
        className="mt-auto flex min-w-0 flex-shrink-0 flex-wrap items-center gap-1.5 px-2 pt-1 pb-1.5 sm:px-3"
      >
        {/* Left Actions: consolidated "+" plus the three inline controls */}
        <div className="flex min-w-0 flex-wrap items-center gap-1">
          <ComposerPlusMenu
            fileInputRef={fileInputRef}
            capabilities={capabilities}
            attachments={attachments}
            setTemplateLibraryVisible={setTemplateLibraryVisible}
            isListening={isListening}
            voiceCallStatus={voiceCallStatus}
            toggleVoiceInput={toggleVoiceInput}
            handleVoiceCall={handleVoiceCall}
            onTogglePlanMode={onTogglePlanMode}
            isPlanMode={isPlanMode}
            onAgentSelect={onAgentSelect}
            activeAgentId={activeAgentId}
            onSlashSelect={onSlashSelect}
            projectId={projectId}
            activeConversationId={activeConversationId}
            disabled={disabled}
          />

          <div className="hidden min-[460px]:block w-px h-4 bg-slate-200 dark:bg-slate-700 mx-0.5" />

          <PermissionModeSwitcher
            conversationId={activeConversationId}
            disabled={!!(isStreaming || disabled)}
          />

          <ThinkingLevelSwitcher
            conversationId={activeConversationId}
            projectId={projectId}
            disabled={!!(isStreaming || disabled)}
          />

          <ModelSwitchPopover
            conversationId={activeConversationId}
            projectId={projectId}
            disabled={!!(isStreaming || disabled)}
          />

          {/* Transient voice states stay visible while active so they can be stopped */}
          {isListening && (
            <LazyTooltip title={t('agent.inputBar.stopVoice', 'Stop voice input')}>
              <LazyButton
                type="text"
                size="small"
                icon={<MicOff size={18} />}
                onClick={toggleVoiceInput}
                aria-label={t('agent.inputBar.stopVoice', 'Stop voice input')}
                className="rounded-lg h-8 w-8 flex items-center justify-center text-red-500 bg-red-50 dark:bg-red-900/20"
              />
            </LazyTooltip>
          )}
          <VoiceWaveform active={isListening} analyser={voiceAnalyser} operation={voiceOperation} />
          {voiceCallStatus !== 'idle' && (
            <LazyTooltip title={t('agent.voiceCall.endCall', 'End call')}>
              <LazyButton
                type="text"
                size="small"
                icon={<PhoneOff size={18} />}
                onClick={handleVoiceCall}
                aria-label={t('agent.voiceCall.endCall', 'End call')}
                className="rounded-lg h-8 w-8 flex items-center justify-center text-green-500 bg-green-50 dark:bg-green-900/20 animate-pulse motion-reduce:animate-none"
              />
            </LazyTooltip>
          )}
        </div>

        {/* Right Actions */}
        <div
          data-testid="input-toolbar-actions"
          className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-1"
        >
          {charCount > 0 && (
            <LazyTooltip
              title={t('agent.inputBar.charLimitHint', {
                count: 4000,
                defaultValue: 'Messages over {{count}} characters may be truncated by the model',
              })}
            >
              <span
                className={`text-xs font-medium transition-colors tabular-nums ${charCount > 4000 ? 'text-amber-500' : 'text-slate-400'}`}
              >
                {charCount.toLocaleString()}
              </span>
            </LazyTooltip>
          )}

          {isStreaming ? (
            <LazyButton
              type="primary"
              danger
              size="small"
              icon={<Square size={14} className="fill-current" />}
              onClick={onAbort}
              className="flex h-8 items-center gap-1.5 rounded-lg px-3 shadow-sm"
            >
              {t('agent.inputBar.stop', 'Stop')}
            </LazyButton>
          ) : (
            <LazyButton
              type="primary"
              size="small"
              icon={<Send size={14} />}
              onClick={handleSend}
              disabled={!canSend}
              aria-label={t('agent.inputBar.send', 'Send message')}
              data-testid="send-button"
              className={`
                rounded-lg flex items-center gap-1.5 h-8 px-2 min-[1280px]:px-3
                bg-primary hover:bg-primary-600
                shadow-sm
                disabled:opacity-40 disabled:shadow-none disabled:cursor-not-allowed
                transition-colors duration-200
              `}
            >
              <span className="hidden min-[1280px]:inline">{t('agent.inputBar.send', 'Send')}</span>
            </LazyButton>
          )}
          {/* I3: plugin composer actions mount after the send control. */}
          <PluginSlotOutlet kind="composer_action" />
        </div>
      </div>
    );
  }
);

InputToolbar.displayName = 'InputToolbar';
