/**
 * VariableInputModal - Fill in template variables before sending
 *
 * Detects {{variable}} patterns in template content and presents
 * input fields for each unique variable.
 */

import { useState, memo, useMemo, useCallback, useEffect, useRef } from 'react';

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
    }, [template.content, template.variables]);

    const templateKey = useMemo(
      () => `${template.content}\n${JSON.stringify(template.variables ?? [])}`,
      [template.content, template.variables]
    );

    const initialValues = useMemo(() => {
      const initial: Record<string, string> = {};
      detectedVars.forEach((v) => {
        initial[v.name] = v.default_value;
      });
      return initial;
    }, [detectedVars]);

    const [valueState, setValueState] = useState<{
      templateKey: string;
      values: Record<string, string>;
    }>(() => ({
      templateKey,
      values: initialValues,
    }));
    const values = valueState.templateKey === templateKey ? valueState.values : initialValues;
    const autoSubmittedKeyRef = useRef<string | null>(null);

    useEffect(() => {
      if (!visible) {
        autoSubmittedKeyRef.current = null;
        return;
      }
      if (detectedVars.length > 0 || autoSubmittedKeyRef.current === templateKey) {
        return;
      }
      autoSubmittedKeyRef.current = templateKey;
      onSubmit(template.content);
      onClose();
    }, [visible, detectedVars.length, onSubmit, onClose, template.content, templateKey]);

    const resetValues = useCallback(() => {
      setValueState({ templateKey, values: initialValues });
    }, [initialValues, templateKey]);

    const handleClose = useCallback(() => {
      resetValues();
      onClose();
    }, [onClose, resetValues]);

    const handleSubmit = useCallback(() => {
      let result = template.content;
      for (const [key, val] of Object.entries(values)) {
        result = result.split(`{{${key}}}`).join(val || `{{${key}}}`);
      }
      onSubmit(result);
      resetValues();
      onClose();
    }, [template.content, values, onSubmit, resetValues, onClose]);

    if (!visible) return null;

    if (detectedVars.length === 0) {
      return null;
    }

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50">
        <div className="max-h-[80vh] w-[28rem] overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-6 shadow-lg dark:border-slate-700 dark:bg-slate-900">
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
                  onChange={(e) => {
                    setValueState((prev) => {
                      const baseValues =
                        prev.templateKey === templateKey ? prev.values : initialValues;
                      return {
                        templateKey,
                        values: { ...baseValues, [v.name]: e.target.value },
                      };
                    });
                  }}
                  placeholder={v.default_value || v.name}
                  className="w-full rounded-lg border border-slate-300 bg-slate-100 px-3 py-2 text-sm text-slate-800 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-200"
                />
              </div>
            ))}
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={handleClose}
              className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              {t('common.cancel', 'Cancel')}
            </button>
            <button
              type="button"
              onClick={handleSubmit}
              className="rounded-lg bg-primary px-4 py-2 text-sm text-slate-50"
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
