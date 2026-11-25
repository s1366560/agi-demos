import { FileCode2, FileText, StickyNote } from 'lucide-react';
import { useTranslation } from 'react-i18next';
export type EditableCanvasType = 'code' | 'markdown' | 'data';

export function CanvasWelcome({
  handleNew,
}: {
  handleNew: (type: EditableCanvasType, title: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="h-full flex flex-col items-center justify-center p-8 text-center">
      <div className="w-16 h-16 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-4">
        <FileCode2 size={28} className="text-slate-500 dark:text-slate-300" />
      </div>
      <h3 className="text-lg font-semibold text-slate-800 dark:text-slate-200 mb-2">
        {t('agent.canvas.emptyTitle', 'Canvas')}
      </h3>
      <p className="text-sm text-slate-500 dark:text-slate-400 max-w-xs leading-relaxed mb-6">
        {t(
          'agent.canvas.emptyDescription',
          'Code, documents, and previews from the agent will appear here. Ask the agent to generate or edit content.'
        )}
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => {
            handleNew('code', 'untitled.py');
          }}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-primary text-white hover:bg-primary-600 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
        >
          <FileCode2 size={14} />
          {t('agent.canvas.newCode', 'New Code')}
        </button>
        <button
          type="button"
          onClick={() => {
            handleNew('markdown', 'untitled.md');
          }}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
        >
          <FileText size={14} />
          {t('agent.canvas.newMarkdown', 'New Markdown')}
        </button>
        <button
          type="button"
          onClick={() => {
            handleNew('data', 'notes.txt');
          }}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
        >
          <StickyNote size={14} />
          {t('agent.canvas.newNote', 'New Note')}
        </button>
      </div>
    </div>
  );
}
export function CanvasTextEditor({
  type: renderType,
  title,
  content,
  onContentChange,
}: {
  type: EditableCanvasType;
  title: string;
  content: string;
  onContentChange: (text: string) => void;
}) {
  const { t } = useTranslation();
  const bgClass =
    renderType === 'code'
      ? 'bg-slate-900 text-slate-200'
      : 'bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200';
  return (
    <div className={`h-full overflow-auto ${renderType === 'code' ? 'bg-slate-900' : ''}`}>
      <textarea
        value={content}
        onChange={(e) => {
          onContentChange(e.target.value);
        }}
        className={`w-full h-full font-mono text-sm p-4 resize-none focus:outline-none ${bgClass}`}
        spellCheck={false}
        aria-label={t('agent.canvas.editorLabel', {
          title,
          defaultValue: 'Editor for {{title}}',
        })}
      />
    </div>
  );
}
