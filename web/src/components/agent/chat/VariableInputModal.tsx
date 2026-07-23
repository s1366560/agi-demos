/**
 * VariableInputModal - Fill in template variables before sending
 *
 * Detects {{variable}} patterns in template content and presents
 * input fields for each unique variable.
 */

import { useState, memo, useMemo, useCallback, useEffect, useId, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import { AppModal } from '@/components/common';

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
    const titleId = useId();

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
    // Names of required variables that failed validation on the last submit attempt.
    const [errors, setErrors] = useState<ReadonlySet<string>>(new Set());
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
      setErrors(new Set());
    }, [initialValues, templateKey]);

    const handleClose = useCallback(() => {
      resetValues();
      onClose();
    }, [onClose, resetValues]);

    const handleSubmit = useCallback(() => {
      // Block submission while required variables are empty so raw
      // {{placeholder}} tokens never leak into the outgoing prompt.
      const missing = detectedVars
        .filter((v) => v.required && !(values[v.name] ?? '').trim())
        .map((v) => v.name);
      if (missing.length > 0) {
        setErrors(new Set(missing));
        return;
      }
      let result = template.content;
      for (const [key, val] of Object.entries(values)) {
        result = result.split(`{{${key}}}`).join(val || `{{${key}}}`);
      }
      onSubmit(result);
      resetValues();
      onClose();
    }, [detectedVars, template.content, values, onSubmit, resetValues, onClose]);

    if (!visible) return null;

    if (detectedVars.length === 0) {
      return null;
    }

    return (
      <AppModal
        open={visible}
        onClose={handleClose}
        title={template.title}
        description={t('agent.templates.fillVariables', 'Fill in the template variables')}
        size="md"
        footer={
          <>
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
          </>
        }
      >
        <div className="space-y-3 mb-4">
          {detectedVars.map((v, index) => {
            const inputId = `${titleId}-${v.name}`;
            const descriptionInputId = v.description ? `${inputId}-description` : undefined;
            const hasError = errors.has(v.name);
            const errorId = hasError ? `${inputId}-error` : undefined;
            return (
              <div key={v.name}>
                <label
                  htmlFor={inputId}
                  className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
                >
                  {v.name}
                  {v.required && (
                    <span className="text-red-500 ml-0.5" aria-hidden="true">
                      *
                    </span>
                  )}
                </label>
                {v.description && (
                  <p id={descriptionInputId} className="text-xs text-slate-400 mb-1">
                    {v.description}
                  </p>
                )}
                <input
                  id={inputId}
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
                    if (hasError) {
                      setErrors((prev) => {
                        const next = new Set(prev);
                        next.delete(v.name);
                        return next;
                      });
                    }
                  }}
                  placeholder={v.default_value || v.name}
                  className={`w-full rounded-lg border bg-slate-100 px-3 py-2 text-sm text-slate-800 outline-none transition-colors focus:border-primary focus:ring-2 focus:ring-primary/20 dark:bg-slate-950 dark:text-slate-200 ${
                    hasError
                      ? 'border-red-400 dark:border-red-500/70'
                      : 'border-slate-300 dark:border-slate-600'
                  }`}
                  aria-describedby={[descriptionInputId, errorId].filter(Boolean).join(' ') || undefined}
                  aria-required={v.required}
                  aria-invalid={hasError}
                  autoFocus={index === 0}
                />
                {hasError && (
                  <p id={errorId} className="mt-1 text-xs text-red-500" role="alert">
                    {t('agent.templates.variableRequired', {
                      name: v.name,
                      defaultValue: '{{name}} is required',
                    })}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </AppModal>
    );
  }
);
VariableInputModal.displayName = 'VariableInputModal';
