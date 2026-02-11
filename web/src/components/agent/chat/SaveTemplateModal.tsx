/**
 * SaveTemplateModal - Save a message as a reusable prompt template
 */

import { useState, memo } from 'react';

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
    const [title, setTitle] = useState('');
    const [category, setCategory] = useState('general');

    if (!visible) return null;

    const handleSave = () => {
      if (!title.trim()) return;
      onSave(title, category);
      setTitle('');
      setCategory('general');
      onClose();
    };

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
        <div className="bg-white dark:bg-slate-800 rounded-xl p-6 w-96 shadow-2xl">
          <h3 className="text-lg font-semibold mb-4">
            {t('agent.templates.saveTitle', 'Save as Template')}
          </h3>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t('agent.templates.titlePlaceholder', 'Template name')}
            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg mb-3 bg-transparent text-sm text-slate-800 dark:text-slate-200"
            autoFocus
          />
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg mb-4 bg-transparent text-sm text-slate-800 dark:text-slate-200"
          >
            <option value="general">General</option>
            <option value="analysis">Analysis</option>
            <option value="code">Coding</option>
            <option value="writing">Writing</option>
          </select>
          <pre className="text-xs bg-slate-100 dark:bg-slate-700 p-2 rounded mb-4 max-h-32 overflow-auto whitespace-pre-wrap text-slate-600 dark:text-slate-300">
            {content.slice(0, 200)}
            {content.length > 200 ? '...' : ''}
          </pre>
          <div className="flex justify-end gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
            >
              {t('common.cancel', 'Cancel')}
            </button>
            <button
              onClick={handleSave}
              disabled={!title.trim()}
              className="px-4 py-2 text-sm bg-primary text-white rounded-lg disabled:opacity-50"
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
