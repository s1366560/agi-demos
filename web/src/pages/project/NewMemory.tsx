import React, { useCallback, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useParams, Link, useNavigate } from 'react-router-dom';

import {
  AlertCircle,
  Bold,
  CheckCircle,
  ChevronDown,
  Code,
  Italic,
  Link as LinkIcon,
  List,
  Loader2,
  Save,
  Sparkles,
  Type,
  X,
} from 'lucide-react';

import { useProjectBasePath } from '@/hooks/useProjectBasePath';

import { memoryAPI } from '../../services/api';
import { graphService } from '../../services/graphService';
import { subscribeToTaskEvents } from '../../services/taskStream';

interface TaskStatus {
  task_id: string;
  status: string;
  progress: number;
  message: string;
  result?: unknown;
}

type EditorMode = 'split' | 'edit' | 'preview';

interface MemoryDraft {
  title: string;
  content: string;
  tags: string[];
  savedAt: string;
}

const STATUS_MAP: Record<string, TaskStatus['status']> = {
  processing: 'running',
  pending: 'pending',
  completed: 'completed',
  failed: 'failed',
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const parseEventRecord = (data: unknown): Record<string, unknown> | null => {
  if (typeof data !== 'string') {
    return null;
  }

  try {
    const parsed = JSON.parse(data) as unknown;
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
};

const readString = (record: Record<string, unknown>, key: string): string | undefined => {
  const value = record[key];
  return typeof value === 'string' ? value : undefined;
};

const readNumber = (record: Record<string, unknown>, key: string, fallback: number): number => {
  const value = record[key];
  const parsed =
    typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
};

const clampProgress = (value: number): number => Math.max(0, Math.min(100, value));

const normalizeStatus = (status: string | undefined): TaskStatus['status'] => {
  const normalized = status?.toLowerCase();
  return normalized ? (STATUS_MAP[normalized] ?? normalized) : 'running';
};

const getResponseDetail = (error: unknown): string | undefined => {
  if (!isRecord(error) || !isRecord(error.response) || !isRecord(error.response.data)) {
    return undefined;
  }

  return typeof error.response.data.detail === 'string' ? error.response.data.detail : undefined;
};

export const NewMemory: React.FC = () => {
  const { t } = useTranslation();
  const translate = useCallback(
    (key: string, fallback: string) => {
      const value = t(key, fallback);
      return value === key ? fallback : value;
    },
    [t]
  );
  const { projectId } = useParams();
  const navigate = useNavigate();
  const { projectBasePath } = useProjectBasePath();
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [tags, setTags] = useState<string[]>(['meeting', 'strategy']);
  const [newTag, setNewTag] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [currentTask, setCurrentTask] = useState<TaskStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editorMode, setEditorMode] = useState<EditorMode>('split');
  const [draftSavedAt, setDraftSavedAt] = useState<string | null>(null);

  const draftStorageKey = `memstack:new-memory-draft:${projectId ?? 'default'}`;

  React.useEffect(() => {
    try {
      const rawDraft = window.localStorage.getItem(draftStorageKey);
      if (!rawDraft) return;

      const parsed = JSON.parse(rawDraft) as Partial<MemoryDraft>;
      if (typeof parsed.title === 'string') {
        setTitle(parsed.title);
      }
      if (typeof parsed.content === 'string') {
        setContent(parsed.content);
      }
      if (Array.isArray(parsed.tags) && parsed.tags.every((tag) => typeof tag === 'string')) {
        setTags(parsed.tags);
      }
      if (typeof parsed.savedAt === 'string') {
        setDraftSavedAt(parsed.savedAt);
      }
    } catch (error) {
      console.warn('Failed to load memory draft:', error);
    }
  }, [draftStorageKey]);

  const streamTaskStatus = useCallback(
    (taskId: string) => {
      subscribeToTaskEvents(taskId, {
        onProgress: (event) => {
          const data = parseEventRecord(event.data);
          if (!data) {
            console.warn('Invalid task progress payload');
            return;
          }

          const progress = clampProgress(readNumber(data, 'progress', 0));

          setCurrentTask({
            task_id: readString(data, 'id') ?? taskId,
            status: normalizeStatus(readString(data, 'status')),
            progress,
            message: readString(data, 'message') ?? t('project.memories.status.processing'),
          });
        },
        onCompleted: (event) => {
          const task = parseEventRecord(event.data);
          if (!task) {
            console.warn('Invalid task completion payload');
            return;
          }

          setCurrentTask({
            task_id: readString(task, 'id') ?? taskId,
            status: 'completed',
            progress: 100,
            message: readString(task, 'message') ?? t('project.memories.status.complete'),
            result: task.result,
          });

          // Close connection and navigate after a short delay
          setTimeout(() => {
            void navigate(`${projectBasePath}/memories`);
          }, 1500);
        },
        onFailed: (event) => {
          const task = parseEventRecord(event.data);
          console.error('Failed event:', task);
          setError(readString(task ?? {}, 'message') ?? t('project.memories.new.error.processing'));
          setIsSaving(false);
          setCurrentTask(null);
        },
        onError: (error) => {
          console.error('SSE connection error:', error);
          setError(
            t(
              'project.memories.new.error.taskUpdatesFailed',
              'Failed to connect to task updates. Please check if the task completed.'
            )
          );
          setIsSaving(false);
          setCurrentTask(null);
        },
      });
    },
    [navigate, projectBasePath, t]
  );

  const handleAddTag = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && newTag.trim()) {
      setTags([...tags, newTag.trim()]);
      setNewTag('');
    }
  };

  const removeTag = (tagToRemove: string) => {
    setTags(tags.filter((tag) => tag !== tagToRemove));
  };

  const insertMarkdown = (prefix: string, suffix: string = '') => {
    const textarea = textareaRef.current;
    if (!textarea) return;

    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const text = content;
    const before = text.substring(0, start);
    const selection = text.substring(start, end);
    const after = text.substring(end);

    const newText = before + prefix + selection + suffix + after;
    setContent(newText);

    setTimeout(() => {
      textarea.focus();
      textarea.setSelectionRange(start + prefix.length, end + prefix.length);
    }, 0);
  };

  const handleAIAssist = async () => {
    if (!content) return;
    setIsOptimizing(true);
    setError(null);
    try {
      const result = await graphService.optimizeContent({ content });
      setContent(result.content);
    } catch (error) {
      console.error('Failed to optimize content:', error);
      setError(
        t(
          'project.memories.new.error.aiOptimizeFailed',
          'AI optimization failed. Please try again.'
        )
      );
    } finally {
      setIsOptimizing(false);
    }
  };

  const handleSave = async () => {
    if (!projectId || !content) return;

    setIsSaving(true);
    setError(null);
    setCurrentTask(null);

    try {
      const response = await memoryAPI.create(projectId, {
        title,
        content,
        project_id: projectId,
        tags,
        content_type: 'text',
        metadata: {
          tags: tags,
          source: 'web_console',
        },
      });

      // If response contains task_id, start SSE streaming
      if (response.task_id) {
        streamTaskStatus(response.task_id);
      } else {
        // Fallback: no task ID, navigate directly
        void navigate(`${projectBasePath}/memories`);
        setIsSaving(false);
      }
    } catch (err: unknown) {
      console.error('Failed to create memory:', err);
      setError(
        getResponseDetail(err) ??
          t('project.memories.new.error.createFailed', 'Failed to create memory')
      );
      setIsSaving(false);
    }
  };

  const handleSaveDraft = () => {
    const savedAt = new Date().toISOString();
    const draft: MemoryDraft = {
      title,
      content,
      tags,
      savedAt,
    };

    try {
      window.localStorage.setItem(draftStorageKey, JSON.stringify(draft));
      setDraftSavedAt(savedAt);
      setError(null);
    } catch (error) {
      console.error('Failed to save memory draft:', error);
      setError(t('project.memories.new.error.createFailed', 'Failed to create memory'));
    }
  };

  const getEditorModeButtonClass = (mode: EditorMode): string =>
    `rounded px-3 py-1 text-xs font-medium transition-colors ${
      editorMode === mode
        ? 'bg-white dark:bg-slate-700 shadow-sm text-slate-900 dark:text-white'
        : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
    }`;

  const editorLayoutClass =
    editorMode === 'split'
      ? 'grid grid-cols-1 lg:grid-cols-2 h-[600px] divide-y lg:divide-y-0 lg:divide-x divide-slate-200 dark:divide-slate-800'
      : 'grid grid-cols-1 h-[600px]';
  const markdownButtonClass = `rounded p-1.5 text-slate-500 dark:text-slate-400 transition-colors ${
    editorMode === 'preview'
      ? 'opacity-50 cursor-not-allowed'
      : 'hover:bg-slate-100 hover:text-primary dark:hover:bg-slate-700'
  }`;
  const draftSavedTime = draftSavedAt
    ? new Date(draftSavedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <div className="flex min-h-[calc(100vh-6rem)] flex-col">
      {/* Top Header / Breadcrumbs - Integrated into page since layout handles main header */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-surface-light px-4 py-3 dark:border-slate-800 dark:bg-surface-dark sm:px-6">
        <div className="flex min-w-0 items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
          <Link
            to={`${projectBasePath}/memories`}
            className="truncate hover:text-primary transition-colors"
          >
            {t('project.memories.title')}
          </Link>
          <span>/</span>
          <span className="truncate font-medium text-slate-900 dark:text-white">
            {t('project.memories.new.title')}
          </span>
        </div>
        <div className="flex flex-wrap justify-end gap-2 sm:gap-3">
          <button
            type="button"
            onClick={handleSaveDraft}
            disabled={isSaving}
            className="rounded-lg border border-slate-300 bg-transparent px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800 sm:px-4"
          >
            {t('project.memories.new.save_draft')}
          </button>
          <button
            type="button"
            onClick={() => {
              void handleSave();
            }}
            disabled={isSaving || !content}
            className="flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-70 sm:px-4"
          >
            {isSaving ? (
              <Loader2 size={20} className="animate-spin motion-reduce:animate-none" />
            ) : (
              <Save size={20} />
            )}
            {t('project.memories.new.save_memory')}
          </button>
        </div>
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 overflow-y-auto bg-background-light dark:bg-background-dark p-6 lg:p-8">
        <div className="mx-auto max-w-6xl flex flex-col gap-6">
          {/* Page Heading */}
          <div>
            <h1 className="text-3xl font-black tracking-tight text-slate-900 dark:text-white">
              {t('project.memories.new.page_title')}
            </h1>
            <p className="mt-1 text-slate-500 dark:text-slate-400">
              {t('project.memories.new.page_subtitle')}
            </p>
          </div>

          {/* Progress Status Card */}
          {currentTask && (
            <div className="rounded-xl border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-900/20 p-6">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className="rounded-full bg-indigo-100 dark:bg-indigo-900/50 p-2">
                    {currentTask.status === 'completed' ? (
                      <CheckCircle size={24} className="text-indigo-600 dark:text-indigo-400" />
                    ) : (
                      <Loader2
                        size={24}
                        className="text-indigo-600 dark:text-indigo-400 animate-spin motion-reduce:animate-none"
                      />
                    )}
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                      {currentTask.status === 'completed'
                        ? t('project.memories.new.status.completed')
                        : t('project.memories.new.status.processing')}
                    </h3>
                    <p className="text-sm text-slate-600 dark:text-slate-400">
                      {currentTask.message}
                    </p>
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-2xl font-bold text-indigo-600 dark:text-indigo-400">
                    {currentTask.progress.toString()}%
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400">
                    {t('project.memories.new.status.complete')}
                  </div>
                </div>
              </div>

              {/* Progress Bar */}
              <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-2 overflow-hidden">
                <div
                  className="h-full bg-indigo-600 transition-[width] duration-300 ease-out dark:bg-indigo-400"
                  style={{ width: `${currentTask.progress.toString()}%` }}
                />
              </div>

              {currentTask.status === 'completed' && (
                <p className="mt-3 text-sm text-slate-600 dark:text-slate-400">
                  {t('project.memories.new.status.redirecting')}
                </p>
              )}
            </div>
          )}

          {/* Error Message */}
          {error && (
            <div className="rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-4">
              <div className="flex items-center gap-3">
                <AlertCircle size={24} className="text-red-600 dark:text-red-400" />
                <div className="flex-1">
                  <h4 className="font-semibold text-red-900 dark:text-red-100">
                    {t('project.memories.new.error.processing')}
                  </h4>
                  <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setError(null);
                    setCurrentTask(null);
                  }}
                  aria-label={t('project.memories.new.actions.dismiss_error')}
                  className="text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-200"
                >
                  <X size={16} />
                </button>
              </div>
            </div>
          )}

          {/* Main Entry Card */}
          <div className="flex flex-col overflow-hidden rounded-lg border border-slate-200 bg-surface-light shadow-sm dark:border-slate-800 dark:bg-surface-dark">
            {/* Metadata Inputs */}
            <div className="grid grid-cols-1 md:grid-cols-12 gap-6 p-6 border-b border-slate-100 dark:border-slate-800">
              {/* Title */}
              <div className="md:col-span-8">
                <label
                  htmlFor="memory-title"
                  className="mb-2 block text-sm font-medium text-slate-900 dark:text-white"
                >
                  {t('project.memories.new.form.title')}{' '}
                  <span className="text-slate-400 font-normal">({t('common.optional')})</span>
                </label>
                <input
                  id="memory-title"
                  type="text"
                  value={title}
                  onChange={(e) => {
                    setTitle(e.target.value);
                  }}
                  className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white placeholder:text-slate-400 focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-[color,background-color,border-color,box-shadow,opacity,transform]"
                  placeholder={t('project.memories.new.form.title_placeholder')}
                />
              </div>
              {/* Context */}
              <div className="md:col-span-4">
                <label
                  htmlFor="memory-context"
                  className="mb-2 block text-sm font-medium text-slate-900 dark:text-white"
                >
                  {t('project.memories.new.form.context')}
                </label>
                <div className="relative">
                  <select
                    id="memory-context"
                    className="w-full appearance-none rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary outline-none transition-[color,background-color,border-color,box-shadow,opacity,transform]"
                  >
                    <option>{t('project.memories.new.placeholders.context_option_1')}</option>
                    <option>{t('project.memories.new.placeholders.context_option_2')}</option>
                    <option>{t('project.memories.new.placeholders.context_option_3')}</option>
                  </select>
                  <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center px-3 text-slate-500">
                    <ChevronDown size={20} />
                  </div>
                </div>
              </div>
              {/* Tags */}
              <div className="md:col-span-12">
                <label
                  htmlFor="memory-tags"
                  className="mb-2 block text-sm font-medium text-slate-900 dark:text-white"
                >
                  {t('project.memories.new.form.tags')}
                </label>
                <div className="flex flex-wrap gap-2 rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 p-2 min-h-[46px]">
                  {tags.map((tag) => (
                    <span
                      key={tag}
                      className="flex items-center gap-1 rounded bg-slate-200 dark:bg-slate-700 px-2 py-1 text-sm font-medium text-slate-800 dark:text-slate-200"
                    >
                      #{tag}
                      <button
                        type="button"
                        onClick={() => {
                          removeTag(tag);
                        }}
                        aria-label={t('project.memories.new.actions.remove_tag', { tag })}
                        className="ml-1 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
                      >
                        <X size={14} />
                      </button>
                    </span>
                  ))}
                  <input
                    id="memory-tags"
                    type="text"
                    value={newTag}
                    onChange={(e) => {
                      setNewTag(e.target.value);
                    }}
                    onKeyDown={handleAddTag}
                    className="bg-transparent text-sm outline-none placeholder:text-slate-500 text-slate-900 dark:text-white min-w-25"
                    placeholder={t('project.memories.new.form.add_tag')}
                  />
                </div>
              </div>
            </div>

            {/* Editor Toolbar */}
            <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-[#1a1d26] px-4 py-2">
              <div className="flex items-center gap-1">
                <div className="flex items-center rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-1 shadow-sm">
                  <button
                    type="button"
                    onClick={() => {
                      insertMarkdown('**', '**');
                    }}
                    disabled={editorMode === 'preview'}
                    className={markdownButtonClass}
                    title={translate('project.memories.new.tooltips.bold', 'Bold')}
                    aria-label={translate('project.memories.new.tooltips.bold', 'Bold')}
                  >
                    <Bold size={20} />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      insertMarkdown('*', '*');
                    }}
                    disabled={editorMode === 'preview'}
                    className={markdownButtonClass}
                    title={translate('project.memories.new.tooltips.italic', 'Italic')}
                    aria-label={translate('project.memories.new.tooltips.italic', 'Italic')}
                  >
                    <Italic size={20} />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      insertMarkdown('### ');
                    }}
                    disabled={editorMode === 'preview'}
                    className={markdownButtonClass}
                    title={translate('project.memories.new.tooltips.heading', 'Heading')}
                    aria-label={translate('project.memories.new.tooltips.heading', 'Heading')}
                  >
                    <Type size={20} />
                  </button>
                </div>
                <div className="w-px h-6 bg-slate-300 dark:bg-slate-700 mx-2"></div>
                <div className="flex items-center rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 p-1 shadow-sm">
                  <button
                    type="button"
                    onClick={() => {
                      insertMarkdown('- ');
                    }}
                    disabled={editorMode === 'preview'}
                    className={markdownButtonClass}
                    title={translate('project.memories.new.tooltips.list', 'List')}
                    aria-label={translate('project.memories.new.tooltips.list', 'List')}
                  >
                    <List size={20} />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      insertMarkdown('[', '](url)');
                    }}
                    disabled={editorMode === 'preview'}
                    className={markdownButtonClass}
                    title={translate('project.memories.new.tooltips.link', 'Link')}
                    aria-label={translate('project.memories.new.tooltips.link', 'Link')}
                  >
                    <LinkIcon size={20} />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      insertMarkdown('```\n', '\n```');
                    }}
                    disabled={editorMode === 'preview'}
                    className={markdownButtonClass}
                    title={translate('project.memories.new.tooltips.code', 'Code Block')}
                    aria-label={translate('project.memories.new.tooltips.code', 'Code Block')}
                  >
                    <Code size={20} />
                  </button>
                </div>
              </div>
              {/* AI Features */}
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => {
                    void handleAIAssist();
                  }}
                  disabled={isOptimizing || !content}
                  className="flex items-center gap-1.5 rounded-lg bg-indigo-50 dark:bg-indigo-900/30 px-3 py-1.5 text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 transition-colors border border-indigo-100 dark:border-indigo-800 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isOptimizing ? (
                    <Loader2 size={16} className="animate-spin motion-reduce:animate-none" />
                  ) : (
                    <Sparkles size={16} />
                  )}
                  {isOptimizing
                    ? t('project.memories.new.ai.optimizing')
                    : t('project.memories.new.ai.assist')}
                </button>
                <div className="flex rounded-lg border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-100 dark:bg-slate-800">
                  <button
                    type="button"
                    onClick={() => {
                      setEditorMode('split');
                    }}
                    aria-pressed={editorMode === 'split'}
                    className={getEditorModeButtonClass('split')}
                  >
                    {t('project.memories.new.actions.split')}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setEditorMode('edit');
                    }}
                    aria-pressed={editorMode === 'edit'}
                    className={getEditorModeButtonClass('edit')}
                  >
                    {t('project.memories.new.actions.edit')}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setEditorMode('preview');
                    }}
                    aria-pressed={editorMode === 'preview'}
                    className={getEditorModeButtonClass('preview')}
                  >
                    {t('project.memories.new.actions.preview')}
                  </button>
                </div>
              </div>
            </div>

            {/* Editor Content Area */}
            <div className={editorLayoutClass}>
              {/* Left: Markdown Input */}
              {editorMode !== 'preview' && (
                <div className="flex flex-col h-full bg-white dark:bg-surface-dark relative">
                  <textarea
                    ref={textareaRef}
                    className="w-full h-full resize-none border-none p-6 outline-none text-slate-800 dark:text-slate-200 font-mono text-sm leading-relaxed bg-transparent focus:ring-0"
                    placeholder={t('project.memories.new.editor.placeholder')}
                    value={content}
                    onChange={(e) => {
                      setContent(e.target.value);
                    }}
                  ></textarea>
                  <div className="absolute bottom-4 right-4 text-xs text-slate-400 pointer-events-none">
                    {t('project.memories.new.editor.markdown_supported')}
                  </div>
                </div>
              )}
              {/* Right: Preview */}
              {editorMode !== 'edit' && (
                <div className="flex flex-col h-full bg-slate-50/50 dark:bg-[#1a1d26]/50 p-6 overflow-y-auto">
                  <div className="prose prose-sm dark:prose-invert max-w-none">
                    {content ? (
                      <div className="whitespace-pre-wrap">{content}</div>
                    ) : (
                      <>
                        <h1 className="text-2xl font-bold text-slate-900 dark:text-white mb-4">
                          {t('project.memories.new.placeholders.content_title')}
                        </h1>
                        <p className="text-slate-600 dark:text-slate-300 mb-4">
                          {t('project.memories.new.placeholders.content_intro')}
                        </p>
                        <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-100 mt-6 mb-2">
                          {t('project.memories.new.placeholders.content_heading')}
                        </h3>
                        <ul className="list-disc pl-5 space-y-1 text-slate-600 dark:text-slate-300 mb-4">
                          <li>{t('project.memories.new.placeholders.content_list_1')}</li>
                          <li>{t('project.memories.new.placeholders.content_list_2')}</li>
                          <li>{t('project.memories.new.placeholders.content_list_3')}</li>
                        </ul>
                        <div className="my-4 rounded-lg border border-slate-200 bg-slate-100 p-4 dark:border-slate-700 dark:bg-slate-800">
                          <p className="italic text-slate-700 dark:text-slate-300 m-0">
                            {t('project.memories.new.placeholders.content_quote')}
                          </p>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* Footer Status Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-500 dark:border-slate-800 dark:bg-surface-dark dark:text-slate-400 sm:px-6">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <span>
                  {draftSavedTime
                    ? t('project.memories.new.footer.draft_saved', { time: draftSavedTime })
                    : t('project.memories.new.footer.last_saved')}
                </span>
                <span className="flex items-center gap-1">
                  <span className="h-1.5 w-1.5 rounded-full bg-green-500"></span>
                  {t('project.memories.new.footer.online')}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <span>
                  {t('project.memories.new.footer.word_count', {
                    count: content.split(/\s+/).filter(Boolean).length,
                  })}
                </span>
                <span>
                  {t('project.memories.new.footer.char_count', { count: content.length })}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
