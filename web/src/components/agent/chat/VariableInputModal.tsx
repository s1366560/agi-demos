/**
 * VariableInputModal - Fill in template variables before sending
 *
 * Detects {{variable}} patterns in template content and presents
 * input fields for each unique variable.
 */

import { useState, memo, useMemo, useCallback } from 'react';

import { useTranslation } from 'react-i18next';

interface TemplateVariable {
  name: string;
  description: string;
  default_value: string;
  required: boolean;
}

interface VariableInputModalProps {
  template: {
    title: string;
    content: string;
    variables?: TemplateVariable[] | undefined;
  };
  visible: boolean;
  onClose: () => void;
  onSubmit: (interpolatedContent: string) => void;
}

export const VariableInputModal = memo<VariableInputModalProps>(
  ({ template, visible, onClose, onSubmit }) => {
    const { t } = useTranslation();

    const detectedVars = useMemo(() => {
      const matches = template.content.match(/\{\{(\w+)\}\}/g) || [];
      const unique = [...new Set(matches.map((m) => m.replace(/[{}]/g, '')))];
      return unique.map((name) => {
        const defined = template.variables?.find((v) => v.name === name);
        return {
          name,
          description: defined?.description || '',
          default_value: defined?.default_value || '',
          required: defined?.required ?? false,
        };
      });
    }, [template]);

    const [values, setValues] = useState<Record<string, string>>(() => {
      const initial: Record<string, string> = {};
      detectedVars.forEach((v) => {
        initial[v.name] = v.default_value;
      });
      return initial;
    });

    const handleSubmit = useCallback(() => {
      let result = template.content;
      for (const [key, val] of Object.entries(values)) {
        result = result.split(`{{${key}}}`).join(val || `{{${key}}}`);
      }
      onSubmit(result);
      onClose();
    }, [template.content, values, onSubmit, onClose]);

    if (!visible) return null;

    // If no variables detected, send content as-is
    if (detectedVars.length === 0) {
      onSubmit(template.content);
      onClose();
      return null;
    }

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
        <div className="bg-white dark:bg-slate-800 rounded-xl p-6 w-[28rem] shadow-2xl max-h-[80vh] overflow-auto">
          <h3 className="text-lg font-semibold mb-1 text-slate-800 dark:text-slate-100">
            {template.title}
          </h3>
          <p className="text-xs text-slate-500 mb-4">
            {t('agent.templates.fillVariables', 'Fill in the template variables')}
          </p>
          <div className="space-y-3 mb-4">
            {detectedVars.map((v) => (
              <div key={v.name}>
                <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                  {v.name}
                  {v.required && <span className="text-red-500 ml-0.5">*</span>}
                </label>
                {v.description && <p className="text-xs text-slate-400 mb-1">{v.description}</p>}
                <input
                  value={values[v.name] || ''}
                  onChange={(e) => { setValues((prev) => ({ ...prev, [v.name]: e.target.value })); }}
                  placeholder={v.default_value || v.name}
                  className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg bg-transparent text-sm text-slate-800 dark:text-slate-200"
                />
              </div>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
            >
              {t('common.cancel', 'Cancel')}
            </button>
            <button
              onClick={handleSubmit}
              className="px-4 py-2 text-sm bg-primary text-white rounded-lg"
            >
              {t('agent.templates.useTemplate', 'Use Template')}
            </button>
          </div>
        </div>
      </div>
    );
  }
);
VariableInputModal.displayName = 'VariableInputModal';
