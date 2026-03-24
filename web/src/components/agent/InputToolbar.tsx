import { useState, memo } from 'react';

import { useTranslation } from 'react-i18next';

import { Popover } from 'antd';
import {
  Send,
  Square,
  Paperclip,
  BookOpen,
  Mic,
  MicOff,
  Phone,
  PhoneOff,
  ListChecks,
  Settings2,
} from 'lucide-react';

import type { ActiveModelCapabilities } from '@/hooks/useActiveModelCapabilities';

import { LazyButton, LazyTooltip } from '@/components/ui/lazyAntd';

import { AgentSwitcher } from './AgentSwitcher';
import { LlmOverridePopover } from './chat/LlmOverridePopover';
import { ModelSwitchPopover } from './chat/ModelSwitchPopover';
import { VoiceWaveform } from './chat/VoiceWaveform';

import type { PendingAttachment } from './FileUploader';

export interface InputToolbarProps {
  /** Ref to the hidden file input */
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  /** Current attachment list (for badge state) */
  attachments: readonly PendingAttachment[];
  /** Model capability flags */
  capabilities: ActiveModelCapabilities;
  /** Template library open state */
  templateLibraryVisible: boolean;
  setTemplateLibraryVisible: React.Dispatch<React.SetStateAction<boolean>>;
  /** Voice input state */
  isListening: boolean;
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
    templateLibraryVisible,
    setTemplateLibraryVisible,
    isListening,
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
    charCount,
    canSend,
    handleSend,
    onAbort,
  }) => {
    const { t } = useTranslation();
    const [overflowOpen, setOverflowOpen] = useState(false);

    const overflowContent = (
      <div className="flex flex-col gap-1 p-1 min-w-[200px]">
        <LlmOverridePopover
          conversationId={activeConversationId}
          disabled={!!(isStreaming || disabled)}
          capabilities={capabilities}
        />
        <ModelSwitchPopover
          conversationId={activeConversationId}
          projectId={projectId}
          disabled={!!(isStreaming || disabled)}
        />
      </div>
    );

    return (
      <div className="flex-shrink-0 px-3 pt-2 pb-2.5 flex items-center gap-1">
        {/* Left Actions */}
        <div className="flex items-center min-w-0 gap-1.5">
          {onAgentSelect && (
            <>
              <AgentSwitcher
                activeAgentId={activeAgentId}
                onSelect={onAgentSelect}
                disabled={!!(isStreaming || disabled)}
                className="h-8 max-w-[240px]"
              />
              <div className="w-px h-4 bg-slate-200 dark:bg-slate-700 mx-1" />
            </>
          )}

          <LazyTooltip
            title={
              capabilities.supportsAttachment
                ? t('agent.inputBar.attachFiles', 'Attach files (or drag & drop)')
                : t(
                    'agent.inputBar.attachNotSupported',
                    'Current model does not support file attachments'
                  )
            }
          >
            <LazyButton
              type="text"
              size="small"
              icon={<Paperclip size={18} />}
              onClick={() => fileInputRef.current?.click()}
              disabled={!capabilities.supportsAttachment}
              aria-label={t('agent.inputBar.attachFiles', 'Attach files (or drag & drop)')}
              className={`
                text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
                hover:bg-slate-100 dark:hover:bg-slate-700/50
                rounded-lg h-8 w-8 flex items-center justify-center
                ${attachments.length > 0 ? 'text-primary' : ''}
                ${!capabilities.supportsAttachment ? 'opacity-40 cursor-not-allowed' : ''}
              `}
            />
          </LazyTooltip>

          <LazyTooltip title={t('agent.inputBar.templates', 'Prompt templates')}>
            <LazyButton
              data-tour="prompt-templates"
              type="text"
              size="small"
              icon={<BookOpen size={18} />}
              onClick={() => {
                setTemplateLibraryVisible((v) => !v);
              }}
              aria-label={t('agent.inputBar.templates', 'Prompt templates')}
              className={`
                text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
                hover:bg-slate-100 dark:hover:bg-slate-700/50
                rounded-lg h-8 w-8 flex items-center justify-center
                ${templateLibraryVisible ? 'text-primary bg-primary/5' : ''}
              `}
            />
          </LazyTooltip>

          <LazyTooltip
            title={
              isListening
                ? t('agent.inputBar.stopVoice', 'Stop voice input')
                : t('agent.inputBar.startVoice', 'Voice input')
            }
          >
            <LazyButton
              type="text"
              size="small"
              icon={isListening ? <MicOff size={18} /> : <Mic size={18} />}
              onClick={toggleVoiceInput}
              disabled={voiceCallStatus !== 'idle'}
              aria-label={
                isListening
                  ? t('agent.inputBar.stopVoice', 'Stop voice input')
                  : t('agent.inputBar.startVoice', 'Voice input')
              }
              className={`
                rounded-lg h-8 w-8 flex items-center justify-center transition-colors
                ${
                  isListening
                    ? 'text-red-500 bg-red-50 dark:bg-red-900/20'
                    : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50'
                }
              `}
            />
          </LazyTooltip>
          <VoiceWaveform active={isListening} />

          <LazyTooltip
            title={voiceCallStatus !== 'idle' ? 'End voice call' : 'Start voice call'}
          >
            <LazyButton
              type="text"
              size="small"
              icon={voiceCallStatus !== 'idle' ? <PhoneOff size={18} /> : <Phone size={18} />}
              onClick={handleVoiceCall}
              disabled={isStreaming || disabled || isListening}
              aria-label={voiceCallStatus !== 'idle' ? 'End voice call' : 'Start voice call'}
              className={`
                rounded-lg h-8 w-8 flex items-center justify-center transition-colors
                ${
                  voiceCallStatus !== 'idle'
                    ? 'text-green-500 bg-green-50 dark:bg-green-900/20 animate-pulse motion-reduce:animate-none'
                    : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50'
                }
              `}
            />
          </LazyTooltip>

          {/* Overflow menu for advanced controls */}
          <Popover
            content={overflowContent}
            trigger="click"
            open={overflowOpen}
            onOpenChange={setOverflowOpen}
            placement="topLeft"
            arrow={false}
            styles={{ content: { padding: 0 } }}
          >
            <LazyTooltip title={t('agent.inputBar.advancedSettings', 'Advanced settings')}>
              <button
                type="button"
                disabled={!!(isStreaming || disabled)}
                aria-label={t('agent.inputBar.advancedSettings', 'Advanced settings')}
                className={`
                  flex items-center justify-center h-8 w-8 rounded-lg transition-colors
                  text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
                  hover:bg-slate-100 dark:hover:bg-slate-700/50
                  disabled:opacity-40
                  ${overflowOpen ? 'text-primary bg-primary/5' : ''}
                `}
              >
                <Settings2 size={16} />
              </button>
            </LazyTooltip>
          </Popover>

          <div className="w-px h-4 bg-slate-200 dark:bg-slate-700 mx-1.5" />

          {onTogglePlanMode && (
            <LazyTooltip
              title={
                isPlanMode
                  ? t('agent.inputBar.exitPlanMode', 'Exit Plan Mode (Shift+Tab)')
                  : t('agent.inputBar.enterPlanMode', 'Enter Plan Mode (Shift+Tab)')
              }
            >
              <button
                type="button"
                onClick={onTogglePlanMode}
                disabled={isStreaming}
                aria-label={
                  isPlanMode
                    ? t('agent.inputBar.exitPlanMode', 'Exit Plan Mode (Shift+Tab)')
                    : t('agent.inputBar.enterPlanMode', 'Enter Plan Mode (Shift+Tab)')
                }
                className={`
                  flex items-center justify-center h-8 w-8 rounded-lg transition-colors
                  ${
                    isPlanMode
                      ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 hover:bg-blue-200 dark:hover:bg-blue-900/50'
                      : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50 disabled:opacity-40'
                  }
                `}
              >
                <ListChecks size={16} />
              </button>
            </LazyTooltip>
          )}
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Right Actions */}
        <div className="flex items-center gap-2">
          {charCount > 0 && (
            <span
              className={`text-xs font-medium transition-colors ${charCount > 4000 ? 'text-amber-500' : 'text-slate-400'}`}
            >
              {charCount.toLocaleString()}
            </span>
          )}

          {isStreaming ? (
            <LazyButton
              type="primary"
              danger
              size="small"
              icon={<Square size={14} className="fill-current" />}
              onClick={onAbort}
              className="rounded-xl flex items-center gap-1.5 h-8 px-3 shadow-sm"
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
              className={`
                rounded-xl flex items-center gap-1.5 h-8 px-3
                bg-gradient-to-r from-primary to-primary-600
                hover:from-primary-600 hover:to-primary-700
                shadow-md shadow-primary/20
                disabled:opacity-40 disabled:shadow-none disabled:cursor-not-allowed
                transition-colors duration-200
              `}
            >
              {t('agent.inputBar.send', 'Send')}
            </LazyButton>
          )}
        </div>
      </div>
    );
  }
);

InputToolbar.displayName = 'InputToolbar';
