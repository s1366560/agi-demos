/**
 * InputBar - Chat input bar with inline file upload
 *
 * Features:
 * - Glass-morphism design with auto-resizing textarea
 * - Drag-and-drop file upload on the entire input card
 * - Paperclip button opens native file picker directly
 * - Inline attachment chips with progress / error states
 * - Plan mode toggle
 */

import { useState, useRef, useCallback, memo } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Send,
  Square,
  Paperclip,
  Wand2,
  X,
  FileText,
  Image as ImageIcon,
  File,
  Upload,
  Sparkles,
  AlertCircle,
  RotateCw,
  Zap,
  BookOpen,
  Mic,
  MicOff,
  MessageSquare,
  Terminal,
} from 'lucide-react';

import type { FileMetadata } from '@/services/sandboxUploadService';

import { LazyButton, LazyTooltip } from '@/components/ui/lazyAntd';

import { MentionPopover } from './chat/MentionPopover';
import { PromptTemplateLibrary } from './chat/PromptTemplateLibrary';
import { VoiceWaveform } from './chat/VoiceWaveform';
import { useFileUpload, type PendingAttachment } from './FileUploader';
import { SlashCommandDropdown } from './SlashCommandDropdown';

import type { MentionItem } from '@/services/mentionService';

import type { SkillResponse } from '@/types/agent';

import type { SlashCommandDropdownHandle } from './SlashCommandDropdown';
import type { MentionPopoverHandle } from './chat/MentionPopover';

interface InputBarProps {
  onSend: (content: string, fileMetadata?: FileMetadata[], forcedSkillName?: string) => void;
  onAbort: () => void;
  isStreaming: boolean;
  isPlanMode: boolean;
  onTogglePlanMode: () => void;
  disabled?: boolean;
  projectId?: string;
}

const getFileIcon = (mimeType: string) => {
  if (mimeType.startsWith('image/')) return <ImageIcon size={14} className="text-emerald-500" />;
  if (mimeType.includes('pdf') || mimeType.includes('document'))
    return <FileText size={14} className="text-red-500" />;
  return <File size={14} className="text-blue-500" />;
};

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

export const InputBar = memo<InputBarProps>(
  ({ onSend, onAbort, isStreaming, isPlanMode, onTogglePlanMode, disabled, projectId }) => {
    const { t } = useTranslation();
    const [content, setContent] = useState('');
    const [inputMode, setInputMode] = useState<'chat' | 'command'>('chat');
    const [isFocused, setIsFocused] = useState(false);
    const [isDragging, setIsDragging] = useState(false);
    const [selectedSkill, setSelectedSkill] = useState<SkillResponse | null>(null);
    const [slashDropdownVisible, setSlashDropdownVisible] = useState(false);
    const [slashQuery, setSlashQuery] = useState('');
    const [slashSelectedIndex, setSlashSelectedIndex] = useState(0);
    const [templateLibraryVisible, setTemplateLibraryVisible] = useState(false);
    const [isListening, setIsListening] = useState(false);
    const [mentionVisible, setMentionVisible] = useState(false);
    const [mentionQuery, setMentionQuery] = useState('');
    const [mentionSelectedIndex, setMentionSelectedIndex] = useState(0);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const mentionPopoverRef = useRef<MentionPopoverHandle>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const slashDropdownRef = useRef<SlashCommandDropdownHandle>(null);
    const dragCounter = useRef(0);
    const recognitionRef = useRef<any>(null);

    const { attachments, addFiles, removeAttachment, retryAttachment, clearAll } = useFileUpload({
      projectId,
      maxFiles: 10,
      maxSizeMB: 100,
    });

    const uploadedAttachments = attachments.filter(
      (a) => a.status === 'uploaded' && a.fileMetadata
    );
    const pendingCount = attachments.filter((a) => a.status === 'uploading').length;

    const canSend =
      !disabled &&
      !isStreaming &&
      (content.trim().length > 0 || uploadedAttachments.length > 0) &&
      pendingCount === 0;

    const handleSend = useCallback(() => {
      if (
        (!content.trim() && uploadedAttachments.length === 0) ||
        isStreaming ||
        disabled ||
        pendingCount > 0
      )
        return;
      const fileMetadataList = uploadedAttachments
        .filter((a) => a.fileMetadata !== undefined)
        .map((a) => a.fileMetadata!);
      const messageContent = inputMode === 'command'
        ? `[command] ${content.trim()}`
        : content.trim();
      onSend(
        messageContent,
        fileMetadataList.length > 0 ? fileMetadataList : undefined,
        selectedSkill?.name
      );
      setContent('');
      setSelectedSkill(null);
      setSlashDropdownVisible(false);
      setMentionVisible(false);
      setMentionQuery('');
      clearAll();
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }, [
      content,
      uploadedAttachments,
      isStreaming,
      disabled,
      pendingCount,
      onSend,
      clearAll,
      selectedSkill,
      inputMode,
    ]);

    const handleTemplateSelect = useCallback(
      (prompt: string) => {
        setContent(prompt);
        setTemplateLibraryVisible(false);
        setTimeout(() => textareaRef.current?.focus(), 50);
      },
      []
    );

    const handleMentionSelect = useCallback(
      (item: MentionItem) => {
        const textarea = textareaRef.current;
        if (!textarea) return;

        const cursorPos = textarea.selectionStart;
        const textBefore = content.slice(0, cursorPos);
        const textAfter = content.slice(cursorPos);

        // Find the "@" trigger position before cursor
        const atIndex = textBefore.lastIndexOf('@');
        if (atIndex === -1) return;

        const before = content.slice(0, atIndex);
        const replacement = `@${item.name} `;
        const newContent = before + replacement + textAfter;

        setContent(newContent);
        setMentionVisible(false);
        setMentionQuery('');

        // Restore cursor position after the inserted mention
        const newCursor = atIndex + replacement.length;
        setTimeout(() => {
          textarea.focus();
          textarea.setSelectionRange(newCursor, newCursor);
        }, 0);
      },
      [content]
    );

    // Voice input via Web Speech API
    const speechSupported =
      typeof window !== 'undefined' &&
      ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window);

    const toggleVoiceInput = useCallback(() => {
      if (isListening) {
        recognitionRef.current?.stop();
        setIsListening(false);
        return;
      }

      const SpeechRecognition =
        (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (!SpeechRecognition) return;

      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = document.documentElement.lang || 'en-US';

      let finalTranscript = '';

      recognition.onresult = (event: any) => {
        let interim = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const transcript = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            finalTranscript += transcript;
          } else {
            interim += transcript;
          }
        }
        setContent((prev) => {
          const base = prev.endsWith(finalTranscript) ? prev : prev + finalTranscript;
          return interim ? base + interim : base;
        });
      };

      recognition.onend = () => {
        setIsListening(false);
        recognitionRef.current = null;
      };

      recognition.onerror = () => {
        setIsListening(false);
        recognitionRef.current = null;
      };

      recognitionRef.current = recognition;
      recognition.start();
      setIsListening(true);
    }, [isListening]);

    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent) => {
        // Mention dropdown keyboard navigation
        if (mentionVisible) {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setMentionSelectedIndex((prev) => prev + 1);
            return;
          }
          if (e.key === 'ArrowUp') {
            e.preventDefault();
            setMentionSelectedIndex((prev) => Math.max(0, prev - 1));
            return;
          }
          if (e.key === 'Enter' || e.key === 'Tab') {
            e.preventDefault();
            const item = mentionPopoverRef.current?.getSelectedItem();
            if (item) {
              handleMentionSelect(item);
            }
            return;
          }
          if (e.key === 'Escape') {
            e.preventDefault();
            setMentionVisible(false);
            setMentionQuery('');
            return;
          }
        }

        // Slash-command keyboard navigation
        if (slashDropdownVisible) {
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            setSlashSelectedIndex((prev) => prev + 1);
            return;
          }
          if (e.key === 'ArrowUp') {
            e.preventDefault();
            setSlashSelectedIndex((prev) => Math.max(0, prev - 1));
            return;
          }
          if (e.key === 'Enter') {
            e.preventDefault();
            const skill = slashDropdownRef.current?.getSelectedSkill();
            if (skill) {
              handleSkillSelect(skill);
            }
            return;
          }
          if (e.key === 'Escape') {
            e.preventDefault();
            setSlashDropdownVisible(false);
            setContent('');
            return;
          }
        }

        if (
          e.key === 'Enter' &&
          !e.shiftKey &&
          !e.nativeEvent.isComposing &&
          !disabled &&
          !isStreaming
        ) {
          e.preventDefault();
          handleSend();
        }
      },
      [handleSend, handleMentionSelect, disabled, isStreaming, slashDropdownVisible, mentionVisible]
    );

    const handleInput = useCallback(
      (e: React.FormEvent<HTMLTextAreaElement>) => {
        const target = e.currentTarget;
        target.style.height = 'auto';
        const minHeight = 48;
        const newHeight = Math.max(minHeight, Math.min(target.scrollHeight, 400));
        target.style.height = `${newHeight}px`;
        const value = target.value;
        setContent(value);

        // Slash-command detection: "/" at start of input
        if (value.startsWith('/') && !selectedSkill) {
          const query = value.slice(1);
          // Only show dropdown for single-word slash query (no spaces = still typing skill name)
          if (!query.includes(' ')) {
            setSlashQuery(query);
            setSlashDropdownVisible(true);
            setSlashSelectedIndex(0);
            return;
          }
        }

        // Close slash dropdown if conditions no longer met
        if (slashDropdownVisible) {
          setSlashDropdownVisible(false);
        }

        // @-mention detection: find "@" before cursor followed by non-space chars
        const cursorPos = target.selectionStart;
        const textBefore = value.slice(0, cursorPos);
        const mentionMatch = textBefore.match(/@([^\s@]*)$/);
        if (mentionMatch) {
          setMentionQuery(mentionMatch[1]);
          setMentionVisible(true);
          setMentionSelectedIndex(0);
        } else if (mentionVisible) {
          setMentionVisible(false);
          setMentionQuery('');
        }
      },
      [selectedSkill, slashDropdownVisible, mentionVisible]
    );

    const handleSkillSelect = useCallback((skill: SkillResponse) => {
      setSelectedSkill(skill);
      setSlashDropdownVisible(false);
      setContent('');
      setSlashQuery('');
      // Focus textarea for typing the message
      textareaRef.current?.focus();
    }, []);

    const handleRemoveSkill = useCallback(() => {
      setSelectedSkill(null);
    }, []);

    // --- Paste files (Ctrl/Cmd+V with images or files) ---
    const handlePaste = useCallback(
      (e: React.ClipboardEvent) => {
        if (disabled) return;
        const items = e.clipboardData?.items;
        if (!items) return;

        const files: File[] = [];
        for (const item of items) {
          if (item.kind === 'file') {
            const file = item.getAsFile();
            if (file) files.push(file);
          }
        }

        if (files.length > 0) {
          e.preventDefault();
          const dt = new DataTransfer();
          files.forEach((f) => dt.items.add(f));
          addFiles(dt.files);
        }
      },
      [disabled, addFiles]
    );

    // --- Drag-and-drop on the entire input card ---
    const handleDragEnter = useCallback(
      (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        dragCounter.current += 1;
        if (!disabled && e.dataTransfer.types.includes('Files')) {
          setIsDragging(true);
        }
      },
      [disabled]
    );

    const handleDragOver = useCallback((e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
    }, []);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter.current -= 1;
      if (dragCounter.current <= 0) {
        dragCounter.current = 0;
        setIsDragging(false);
      }
    }, []);

    const handleDrop = useCallback(
      (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        dragCounter.current = 0;
        setIsDragging(false);
        if (!disabled && e.dataTransfer.files.length > 0) {
          addFiles(e.dataTransfer.files);
        }
      },
      [disabled, addFiles]
    );

    const handleFileInputChange = useCallback(
      (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files && e.target.files.length > 0) {
          addFiles(e.target.files);
        }
        e.target.value = '';
      },
      [addFiles]
    );

    const charCount = content.length;

    return (
      <div className="h-full flex flex-col p-4">
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileInputChange}
          className="hidden"
          disabled={disabled}
        />

        {/* Main input card */}
        <div
          data-tour="input-bar"
          onDragEnter={handleDragEnter}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`
            flex-1 flex flex-col min-h-0 rounded-2xl border relative
            bg-white/90 dark:bg-slate-800/90
            backdrop-blur-sm transition-all duration-300 ease-out shadow-lg
            ${
              isDragging
                ? 'border-primary/60 ring-2 ring-primary/20 shadow-primary/15'
                : isFocused
                  ? 'border-primary/40 shadow-primary/10 ring-2 ring-primary/10'
                  : 'border-slate-200/60 dark:border-slate-700/60 shadow-slate-200/50 dark:shadow-black/20'
            }
            ${disabled ? 'opacity-60 pointer-events-none' : ''}
          `}
        >
          {/* Drag overlay */}
          {isDragging && (
            <div className="absolute inset-0 z-20 rounded-2xl bg-primary/5 dark:bg-primary/10 flex items-center justify-center pointer-events-none">
              <div className="flex flex-col items-center gap-2 text-primary">
                <Upload size={28} strokeWidth={1.5} />
                <span className="text-sm font-medium">{t('agent.inputBar.dropToUpload', 'Drop files to upload')}</span>
              </div>
            </div>
          )}

          {/* Plan Mode Badge */}
          {isPlanMode && (
            <div className="px-4 pt-3 flex-shrink-0">
              <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/30 dark:to-indigo-900/20 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800/50 rounded-full text-xs font-medium">
                <Sparkles size={12} />
                {t('agent.inputBar.planModeActive', 'Plan Mode Active')}
              </div>
            </div>
          )}

          {/* Inline Attachment Chips */}
          {attachments.length > 0 && (
            <div className="px-4 pt-3 flex-shrink-0">
              <div className="flex flex-wrap gap-2">
                {attachments.map((file) => (
                  <AttachmentChip
                    key={file.id}
                    file={file}
                    onRemove={removeAttachment}
                    onRetry={retryAttachment}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Selected Skill Badge */}
          {selectedSkill && (
            <div className="px-4 pt-3 flex-shrink-0">
              <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-primary/5 to-primary/10 dark:from-primary/10 dark:to-primary/15 text-primary border border-primary/20 dark:border-primary/30 rounded-full text-xs font-medium">
                <Zap size={12} />
                <span>/{selectedSkill.name}</span>
                <button
                  type="button"
                  onClick={handleRemoveSkill}
                  className="ml-0.5 p-0.5 hover:bg-primary/10 rounded-full transition-colors"
                >
                  <X size={10} />
                </button>
              </div>
            </div>
          )}

          {/* Text Area */}
          <div className="flex-1 min-h-0 px-4 py-3 relative overflow-hidden">
            <SlashCommandDropdown
              ref={slashDropdownRef}
              query={slashQuery}
              visible={slashDropdownVisible}
              onSelect={handleSkillSelect}
              onClose={() => setSlashDropdownVisible(false)}
              selectedIndex={slashSelectedIndex}
              onSelectedIndexChange={setSlashSelectedIndex}
            />
            {projectId && (
              <MentionPopover
                ref={mentionPopoverRef}
                query={mentionQuery}
                projectId={projectId}
                visible={mentionVisible}
                onSelect={handleMentionSelect}
                onClose={() => {
                  setMentionVisible(false);
                  setMentionQuery('');
                }}
                selectedIndex={mentionSelectedIndex}
                onSelectedIndexChange={setMentionSelectedIndex}
              />
            )}
            <textarea
              ref={textareaRef}
              value={content}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              onFocus={() => setIsFocused(true)}
              onBlur={() => setIsFocused(false)}
              aria-label={
                isPlanMode
                  ? t('agent.inputBar.planPlaceholder', 'Describe what you want to plan in detail...')
                  : inputMode === 'command'
                    ? t('agent.inputBar.commandPlaceholder', 'Enter a command...')
                    : t('agent.inputBar.placeholder', "Ask me anything, or type '/' for commands...")
              }
              placeholder={
                isPlanMode
                  ? t('agent.inputBar.planPlaceholder', 'Describe what you want to plan in detail...')
                  : inputMode === 'command'
                    ? t('agent.inputBar.commandPlaceholder', 'Enter a command...')
                    : t('agent.inputBar.placeholder', "Ask me anything, or type '/' for commands...")
              }
              rows={2}
              data-testid="chat-input"
              className={`
                w-full h-full resize-none bg-transparent
                text-slate-800 dark:text-slate-100
                placeholder:text-slate-400 dark:placeholder:text-slate-500
                focus:outline-none text-[15px] leading-relaxed min-h-[48px]
                ${inputMode === 'command' ? 'font-mono' : ''}
              `}
            />
          </div>

          {/* Toolbar */}
          <div className="flex-shrink-0 px-3 pb-3 flex items-center gap-2">
            {/* Left Actions */}
            <div className="flex items-center gap-1">
              <LazyTooltip title={t('agent.inputBar.attachFiles', 'Attach files (or drag & drop)')}>
                <LazyButton
                  type="text"
                  size="small"
                  icon={<Paperclip size={18} />}
                  onClick={() => fileInputRef.current?.click()}
                  className={`
                    text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
                    hover:bg-slate-100 dark:hover:bg-slate-700/50
                    rounded-lg h-9 w-9 flex items-center justify-center
                    ${attachments.length > 0 ? 'text-primary' : ''}
                  `}
                />
              </LazyTooltip>

              <LazyTooltip title={t('agent.inputBar.templates', 'Prompt templates')}>
                <LazyButton
                  data-tour="prompt-templates"
                  type="text"
                  size="small"
                  icon={<BookOpen size={18} />}
                  onClick={() => setTemplateLibraryVisible((v) => !v)}
                  className={`
                    text-slate-500 hover:text-slate-700 dark:hover:text-slate-300
                    hover:bg-slate-100 dark:hover:bg-slate-700/50
                    rounded-lg h-9 w-9 flex items-center justify-center
                    ${templateLibraryVisible ? 'text-primary bg-primary/5' : ''}
                  `}
                />
              </LazyTooltip>

              {speechSupported && (
                <>
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
                      className={`
                        rounded-lg h-9 w-9 flex items-center justify-center transition-all
                        ${
                          isListening
                            ? 'text-red-500 bg-red-50 dark:bg-red-900/20'
                            : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50'
                        }
                      `}
                    />
                  </LazyTooltip>
                  <VoiceWaveform active={isListening} />
                </>
              )}

              <div className="w-px h-5 bg-slate-200 dark:bg-slate-700 mx-1" />

              <LazyTooltip
                title={
                  inputMode === 'command'
                    ? t('agent.inputBar.commandMode', 'Command')
                    : t('agent.inputBar.chatMode', 'Chat')
                }
              >
                <button
                  type="button"
                  onClick={() => setInputMode(inputMode === 'chat' ? 'command' : 'chat')}
                  className={`
                    flex items-center justify-center h-9 w-9 rounded-lg transition-all
                    ${
                      inputMode === 'command'
                        ? 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400'
                        : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50'
                    }
                  `}
                  title={t('agent.inputBar.modeToggle', 'Toggle input mode')}
                >
                  {inputMode === 'chat'
                    ? <MessageSquare size={16} />
                    : <Terminal size={16} />}
                </button>
              </LazyTooltip>

              <LazyTooltip title={isPlanMode ? t('agent.inputBar.exitPlanMode', 'Exit Plan Mode') : t('agent.inputBar.enterPlanMode', 'Enter Plan Mode')}>
                <LazyButton
                  type="text"
                  size="small"
                  onClick={onTogglePlanMode}
                  className={`
                    flex items-center gap-1.5 h-9 px-3 rounded-lg transition-all
                    ${
                      isPlanMode
                        ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800/50'
                        : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700/50'
                    }
                  `}
                >
                  <Wand2 size={16} />
                  <span className="text-sm font-medium">{t('agent.inputBar.plan', 'Plan')}</span>
                </LazyButton>
              </LazyTooltip>
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
                  className={`
                    rounded-xl flex items-center gap-1.5 h-8 px-3
                    bg-gradient-to-r from-primary to-primary-600
                    hover:from-primary-600 hover:to-primary-700
                    shadow-md shadow-primary/20
                    disabled:opacity-40 disabled:shadow-none disabled:cursor-not-allowed
                    transition-all duration-200
                  `}
                >
                  {t('agent.inputBar.send', 'Send')}
                </LazyButton>
              )}
            </div>
          </div>

          {/* Prompt Template Library popover */}
          <PromptTemplateLibrary
            visible={templateLibraryVisible}
            onSelect={handleTemplateSelect}
            onClose={() => setTemplateLibraryVisible(false)}
          />
        </div>
      </div>
    );
  }
);

InputBar.displayName = 'InputBar';

// --- Attachment Chip ---

const AttachmentChip = memo<{
  file: PendingAttachment;
  onRemove: (id: string) => void;
  onRetry: (id: string) => void;
}>(({ file, onRemove, onRetry }) => (
  <div
    className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs border transition-colors ${
      file.status === 'error'
        ? 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800/50'
        : 'bg-slate-50 dark:bg-slate-700/50 border-slate-200 dark:border-slate-600'
    }`}
  >
    {getFileIcon(file.mimeType)}
    <span className="max-w-[120px] truncate text-slate-700 dark:text-slate-300">
      {file.filename}
    </span>
    <span className="text-slate-400">{formatSize(file.sizeBytes)}</span>
    {file.status === 'uploading' && (
      <span className="text-blue-500 font-medium">{file.progress}%</span>
    )}
    {file.status === 'error' && (
      <>
        <LazyTooltip title={file.error}>
          <AlertCircle size={13} className="text-red-500 cursor-help" />
        </LazyTooltip>
        <button
          type="button"
          onClick={() => onRetry(file.id)}
          className="p-0.5 hover:bg-red-100 dark:hover:bg-red-900/30 rounded transition-colors"
        >
          <RotateCw size={12} className="text-red-500" />
        </button>
      </>
    )}
    <button
      type="button"
      onClick={() => onRemove(file.id)}
      disabled={file.status === 'uploading'}
      className="p-0.5 hover:bg-slate-200 dark:hover:bg-slate-600 rounded transition-colors ml-0.5 disabled:opacity-30"
    >
      <X size={12} className="text-slate-400 hover:text-slate-600" />
    </button>
  </div>
));

AttachmentChip.displayName = 'AttachmentChip';

export default InputBar;
