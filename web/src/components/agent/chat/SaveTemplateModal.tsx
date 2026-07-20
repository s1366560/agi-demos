/**
 * SaveTemplateModal - Save a message as a reusable prompt template
 */

import { useState, memo } from 'react';

import { useTranslation } from 'react-i18next';

import { AppModal } from '@/components/common';

interface SaveTemplateModalProps {
  content: string;
  visible: boolean;
  onClose: () => void;
  onSave: (title: string, category: string) => void;
}

export const SaveTemplateModal = memo<SaveTemplateModalProps>(
  ({ content, visible, onClose, onSave }) => {
    const { t } = useTranslation();
    const nameInputId = 'save-template-name';
    const categoryInputId = 'save-template-category';
    const previewId = 'save-template-preview';
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
      <AppModal
        open={visible}
        onClose={onClose}
        title={t('agent.templates.saveTitle', 'Save as Template')}
        size="sm"
        footer={
          <>
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
          </>
        }
      >
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
      </AppModal>
    );
  }
);
SaveTemplateModal.displayName = 'SaveTemplateModal';
