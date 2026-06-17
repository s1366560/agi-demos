/**
 * SaveTemplateModal - Save a message as a reusable prompt template
 */

import { useState, memo, useEffect, useId } from 'react';

import { useTranslation } from 'react-i18next';

interface SaveTemplateModalProps {
  content: string;
  visible: boolean;
  onClose: () => void;
  onSave: (title: string, category: string) => void;
}

export const SaveTemplateModal = memo<SaveTemplateModalProps>(
  ({ content, visible, onClose, onSave }) => {
    const { t } = useTranslation();
    const titleId = useId();
    const nameInputId = useId();
    const categoryInputId = useId();
    const previewId = useId();
    const [title, setTitle] = useState('');
    const [category, setCategory] = useState('general');

    useEffect(() => {
      if (!visible) return undefined;
      const handleKeyDown = (event: KeyboardEvent) => {
        if (event.key === 'Escape') {
          onClose();
        }
      };
      window.addEventListener('keydown', handleKeyDown);
      return () => {
        window.removeEventListener('keydown', handleKeyDown);
      };
    }, [visible, onClose]);

    if (!visible) return null;

    const handleSave = () => {
      if (!title.trim()) return;
      onSave(title, category);
      setTitle('');
      setCategory('general');
      onClose();
    };

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50">
        <div
          className="w-96 rounded-lg border border-slate-200 bg-slate-50 p-6 shadow-lg dark:border-slate-700 dark:bg-slate-900"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={previewId}
        >
          <h3 id={titleId} className="text-lg font-semibold mb-4">
            {t('agent.templates.saveTitle', 'Save as Template')}
          </h3>
          <label htmlFor={nameInputId} className="sr-only">
            {t('agent.templates.titlePlaceholder', 'Template name')}
          </label>
          <input
            id={nameInputId}
            value={title}
            onChange={(e) => {
              setTitle(e.target.value);
            }}
            placeholder={t('agent.templates.titlePlaceholder', 'Template name')}
            className="mb-3 w-full rounded-lg border border-slate-300 bg-slate-100 px-3 py-2 text-sm text-slate-800 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-200"
            autoFocus
          />
          <label htmlFor={categoryInputId} className="sr-only">
            {t('agent.templates.category', 'Category')}
          </label>
          <select
            id={categoryInputId}
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
            }}
            className="mb-4 w-full rounded-lg border border-slate-300 bg-slate-100 px-3 py-2 text-sm text-slate-800 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-200"
          >
            <option value="general">{t('agent.templates.general', 'General')}</option>
            <option value="analysis">{t('agent.templates.analysis', 'Analysis')}</option>
            <option value="code">{t('agent.templates.coding', 'Coding')}</option>
            <option value="writing">{t('agent.templates.writing', 'Writing')}</option>
          </select>
          <pre
            id={previewId}
            className="text-xs bg-slate-100 dark:bg-slate-700 p-2 rounded mb-4 max-h-32 overflow-auto whitespace-pre-wrap text-slate-600 dark:text-slate-300"
          >
            {content.slice(0, 200)}
            {content.length > 200 ? '...' : ''}
          </pre>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {t('common.cancel', 'Cancel')}
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!title.trim()}
              className="rounded-lg bg-primary px-4 py-2 text-sm text-slate-50 disabled:opacity-50"
            >
              {t('common.save', 'Save')}
            </button>
          </div>
        </div>
      </div>
    );
  }
);
SaveTemplateModal.displayName = 'SaveTemplateModal';
