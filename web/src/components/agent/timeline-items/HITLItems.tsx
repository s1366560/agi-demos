/**
 * HITLItems - Human-in-the-loop timeline event rendering
 *
 * Contains ClarificationAskedItem, DecisionAskedItem, and EnvVarRequestedItem.
 */

import { memo, useState, useId } from 'react';

import { useTranslation } from 'react-i18next';

import { useAgentV3Store } from '../../../stores/agentV3';

import { OptionButton, TimeBadge } from './shared';

import type {
  ClarificationAskedTimelineEvent,
  ClarificationOption,
  DecisionAskedTimelineEvent,
  DecisionOption,
  EnvVarField,
  EnvVarRequestedTimelineEvent,
} from '../../../types/agent';

// ---------------------------------------------------------------------------
// ClarificationAskedItem
// ---------------------------------------------------------------------------

interface ClarificationAskedItemProps {
  event: ClarificationAskedTimelineEvent;
}

export const ClarificationAskedItem = memo(
  function ClarificationAskedItem({ event }: ClarificationAskedItemProps) {
    const { t } = useTranslation();
    const hasOptions = event.options.length > 0;
    const [selectedOption, setSelectedOption] = useState<string | null>(null);
    const [customAnswer, setCustomAnswer] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);
    const { respondToClarification } = useAgentV3Store();
    const isAnswered = event.answered ?? false;
    const customAnswerId = useId();

    const handleSubmit = async () => {
      const answer = hasOptions ? selectedOption || customAnswer : customAnswer;
      if (!answer) return;

      setIsSubmitting(true);
      try {
        await respondToClarification(event.requestId, answer);
      } finally {
        setIsSubmitting(false);
      }
    };

    const isSubmitDisabled = (() => {
      if (isSubmitting) return true;
      if (!hasOptions) return !customAnswer.trim();
      return !selectedOption && !customAnswer;
    })();

    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-start gap-3 my-3">
          <div className="w-10 h-10 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-slate-500 dark:text-slate-400 text-lg">
              help_outline
            </span>
          </div>
          <div className="flex-1 min-w-0 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400 uppercase tracking-wider">
                {t('agent.hitl.title.clarification')}
              </span>
              {isAnswered && (
                <span className="text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 px-1.5 py-0.5 rounded">
                  {t('agent.hitl.status.completed')}
                </span>
              )}
            </div>
            <p className="text-sm text-slate-700 dark:text-slate-300 mb-3">{event.question}</p>

            {!isAnswered ? (
              <>
                {hasOptions ? (
                  <div className="space-y-2 mb-3">
                    {event.options.map((option: ClarificationOption, idx: number) => (
                      <OptionButton
                        key={option.id || `option-${String(idx)}`}
                        option={option}
                        isSelected={selectedOption === option.id}
                        isRecommended={option.recommended}
                        onClick={() => {
                          setSelectedOption(option.id);
                          setCustomAnswer('');
                        }}
                        disabled={isSubmitting}
                      />
                    ))}
                  </div>
                ) : event.allowCustom ? (
                  <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
                    {t('agent.hitl.none.no_preset_answer')}
                  </p>
                ) : (
                  <p className="text-xs text-slate-400 dark:text-slate-500 mb-2">
                    {t('agent.hitl.none.no_options')}
                  </p>
                )}

                {(event.allowCustom || !hasOptions) && (hasOptions || event.allowCustom) && (
                  <div className="mb-3">
                    <label htmlFor={customAnswerId} className="sr-only">
                      {t('agent.hitl.option.custom_answer')}
                    </label>
                    <input
                      id={customAnswerId}
                      type="text"
                      placeholder={t('agent.hitl.placeholder.enter_answer')}
                      value={customAnswer}
                      onChange={(e) => {
                        setCustomAnswer(e.target.value);
                        setSelectedOption(null);
                      }}
                      disabled={isSubmitting}
                      className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                  </div>
                )}

                <button
                  type="button"
                  onClick={() => {
                    void handleSubmit();
                  }}
                  disabled={isSubmitDisabled}
                  className="px-4 py-2 text-sm font-medium text-white bg-primary hover:bg-primary/90 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-primary/50 focus:ring-offset-2"
                >
                  {isSubmitting ? t('common.loading') : t('agent.hitl.button.confirm')}
                </button>
              </>
            ) : (
              <div className="text-sm text-slate-600 dark:text-slate-400 bg-white/50 dark:bg-slate-800/50 rounded-lg p-2">
                <span className="font-medium">{t('agent.hitl.status.submitted')}: </span>{' '}
                {event.answer}
              </div>
            )}
          </div>
        </div>
        <div className="pl-12">
          <TimeBadge timestamp={event.timestamp} />
        </div>
      </div>
    );
  },
  (prev, next) => {
    return prev.event.id === next.event.id && prev.event.answered === next.event.answered;
  }
);

// ---------------------------------------------------------------------------
// DecisionAskedItem
// ---------------------------------------------------------------------------

interface DecisionAskedItemProps {
  event: DecisionAskedTimelineEvent;
}

export const DecisionAskedItem = memo(
  function DecisionAskedItem({ event }: DecisionAskedItemProps) {
    const { t } = useTranslation();
    const [selectedOption, setSelectedOption] = useState<string | null>(
      event.defaultOption || null
    );
    const [customDecision, setCustomDecision] = useState('');
    const [selectedMultiple, setSelectedMultiple] = useState<string[]>([]);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const { respondToDecision } = useAgentV3Store();
    const isAnswered = event.answered ?? false;
    const hasOptions = event.options.length > 0;
    const isMultiSelect = event.selectionMode === 'multiple';
    const customDecisionId = useId();

    const toggleMultiSelect = (optionId: string) => {
      setSelectedMultiple((prev) =>
        prev.includes(optionId) ? prev.filter((id) => id !== optionId) : [...prev, optionId]
      );
    };

    const handleSubmit = async () => {
      let decision: string | string[];
      if (!hasOptions && customDecision) {
        decision = customDecision;
      } else if (isMultiSelect) {
        decision = selectedMultiple;
      } else if (customDecision) {
        decision = customDecision;
      } else if (selectedOption) {
        decision = selectedOption;
      } else {
        return;
      }

      setIsSubmitting(true);
      try {
        await respondToDecision(event.requestId, decision);
      } finally {
        setIsSubmitting(false);
      }
    };

    const isSubmitDisabled = (() => {
      if (isSubmitting) return true;
      if (!hasOptions) return !customDecision;
      if (isMultiSelect) return selectedMultiple.length === 0;
      if (customDecision) return false;
      return !selectedOption;
    })();

    const titleLabel = isMultiSelect
      ? t('agent.hitl.multiselect.limit', { max: event.maxSelections || 10 })
      : t('agent.hitl.title.decision');

    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-start gap-3 my-3">
          <div className="w-10 h-10 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-blue-600 dark:text-blue-400 text-lg">
              rule
            </span>
          </div>
          <div className="flex-1 min-w-0 bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium text-blue-700 dark:text-blue-400 uppercase tracking-wider">
                {titleLabel}
              </span>
              {isAnswered && (
                <span className="text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 px-1.5 py-0.5 rounded">
                  {t('agent.hitl.status.completed')}
                </span>
              )}
            </div>
            <p className="text-sm text-slate-700 dark:text-slate-300 mb-3">{event.question}</p>

            {!isAnswered ? (
              <>
                {hasOptions ? (
                  <>
                    <div className="space-y-2 mb-3">
                      {event.options.map((option: DecisionOption, idx: number) => (
                        <OptionButton
                          key={option.id || `option-${String(idx)}`}
                          option={option}
                          isSelected={
                            isMultiSelect
                              ? selectedMultiple.includes(option.id)
                              : selectedOption === option.id
                          }
                          isRecommended={option.recommended}
                          onClick={() => {
                            if (isMultiSelect) {
                              toggleMultiSelect(option.id);
                            } else {
                              setSelectedOption(option.id);
                              setCustomDecision('');
                            }
                          }}
                          disabled={isSubmitting}
                        />
                      ))}
                    </div>

                    {event.allowCustom && !isMultiSelect && (
                      <div className="mb-3">
                        <label htmlFor={customDecisionId} className="sr-only">
                          {t('agent.hitl.option.custom_decision')}
                        </label>
                        <input
                          id={customDecisionId}
                          type="text"
                          placeholder={t('agent.hitl.placeholder.enter_decision')}
                          value={customDecision}
                          onChange={(e) => {
                            setCustomDecision(e.target.value);
                            setSelectedOption(null);
                          }}
                          disabled={isSubmitting}
                          className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/50"
                        />
                      </div>
                    )}
                  </>
                ) : event.allowCustom ? (
                  <div className="mb-3">
                    <p className="text-xs text-slate-500 dark:text-slate-400 mb-2">
                      {t('agent.hitl.none.no_preset_decision')}
                    </p>
                    <label htmlFor={`${customDecisionId}-fallback`} className="sr-only">
                      {t('agent.hitl.option.custom_decision')}
                    </label>
                    <input
                      id={`${customDecisionId}-fallback`}
                      type="text"
                      placeholder={t('agent.hitl.placeholder.enter_decision')}
                      value={customDecision}
                      onChange={(e) => {
                        setCustomDecision(e.target.value);
                      }}
                      disabled={isSubmitting}
                      className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/50"
                    />
                  </div>
                ) : (
                  <div className="mb-3 text-xs text-slate-400 dark:text-slate-500 italic">
                    {t('agent.hitl.none.no_options')}
                  </div>
                )}

                <button
                  type="button"
                  onClick={() => {
                    void handleSubmit();
                  }}
                  disabled={isSubmitDisabled}
                  className="px-4 py-2 text-sm font-medium text-white bg-primary hover:bg-primary/90 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-primary/50 focus:ring-offset-2"
                >
                  {isSubmitting
                    ? t('common.loading')
                    : isMultiSelect
                      ? `${t('agent.hitl.button.confirm_choice')} (${String(selectedMultiple.length)})`
                      : t('agent.hitl.button.confirm')}
                </button>
              </>
            ) : (
              <div className="text-sm text-slate-600 dark:text-slate-400 bg-white/50 dark:bg-slate-800/50 rounded-lg p-2">
                <span className="font-medium">{t('agent.hitl.status.completed')}: </span>{' '}
                {event.decision}
              </div>
            )}
          </div>
        </div>
        <div className="pl-12">
          <TimeBadge timestamp={event.timestamp} />
        </div>
      </div>
    );
  },
  (prev, next) => {
    return prev.event.id === next.event.id && prev.event.answered === next.event.answered;
  }
);

// ---------------------------------------------------------------------------
// EnvVarRequestedItem
// ---------------------------------------------------------------------------

interface EnvVarRequestedItemProps {
  event: EnvVarRequestedTimelineEvent;
}

export const EnvVarRequestedItem = memo(
  function EnvVarRequestedItem({ event }: EnvVarRequestedItemProps) {
    const { t } = useTranslation();
    const [values, setValues] = useState<Record<string, string>>({});
    const [isSubmitting, setIsSubmitting] = useState(false);
    const { respondToEnvVar } = useAgentV3Store();
    const isAnswered = event.answered || false;
    const fieldIds = useId();

    const handleChange = (name: string, value: string) => {
      setValues((prev) => ({ ...prev, [name]: value }));
    };

    const handleSubmit = async () => {
      const missingRequired = event.fields.filter(
        (f: EnvVarField) => f.required && !values[f.name]
      );
      if (missingRequired.length > 0) {
        return;
      }

      setIsSubmitting(true);
      try {
        await respondToEnvVar(event.requestId, values);
      } finally {
        setIsSubmitting(false);
      }
    };

    const requiredFilled = event.fields
      .filter((f: EnvVarField) => f.required)
      .every((f: EnvVarField) => values[f.name]);

    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-start gap-3 my-3">
          <div className="w-10 h-10 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-slate-500 dark:text-slate-400 text-lg">
              key
            </span>
          </div>
          <div className="flex-1 min-w-0 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700/50 rounded-xl p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-medium text-slate-600 dark:text-slate-400 uppercase tracking-wider">
                {t('agent.hitl.title.env_var')}
              </span>
              <span className="text-xs text-slate-500 dark:text-slate-400">{event.toolName}</span>
              {isAnswered && (
                <span className="text-xs bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 px-1.5 py-0.5 rounded">
                  {t('agent.hitl.status.configured')}
                </span>
              )}
            </div>
            {event.message && (
              <p className="text-sm text-slate-700 dark:text-slate-300 mb-3">{event.message}</p>
            )}

            {!isAnswered ? (
              <>
                <div className="space-y-3 mb-3">
                  {event.fields.map((field: EnvVarField) => {
                    const fieldId = `${fieldIds}-${field.name}`;
                    return (
                      <div key={field.name}>
                        <label htmlFor={fieldId} className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
                          {field.label}
                          {field.required && (
                            <span className="text-red-500 ml-1" aria-label={t('common.forms.required')}>
                              *
                            </span>
                          )}
                        </label>
                        {field.description && (
                          <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">
                            {field.description}
                          </p>
                        )}
                        {field.input_type === 'textarea' ? (
                          <textarea
                            id={fieldId}
                            name={field.name}
                            placeholder={field.placeholder || t('agent.hitl.validation.enter_field', { field: field.label })}
                            value={values[field.name] || field.default_value || ''}
                            onChange={(e) => {
                              handleChange(field.name, e.target.value);
                            }}
                            disabled={isSubmitting}
                            rows={3}
                            className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/50"
                          />
                        ) : (
                          <input
                            id={fieldId}
                            name={field.name}
                            type={field.input_type === 'password' ? 'password' : 'text'}
                            placeholder={field.placeholder || t('agent.hitl.validation.enter_field', { field: field.label })}
                            value={values[field.name] || field.default_value || ''}
                            onChange={(e) => {
                              handleChange(field.name, e.target.value);
                            }}
                            disabled={isSubmitting}
                            className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-primary/50"
                          />
                        )}
                      </div>
                    );
                  })}
                </div>

                <button
                  type="button"
                  onClick={() => {
                    void handleSubmit();
                  }}
                  disabled={isSubmitting || !requiredFilled}
                  className="px-4 py-2 text-sm font-medium text-white bg-primary hover:bg-primary/90 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-primary/50 focus:ring-offset-2"
                >
                  {isSubmitting ? t('common.loading') : t('agent.hitl.button.submit')}
                </button>
              </>
            ) : (
              <div className="text-sm text-slate-600 dark:text-slate-400 bg-white/50 dark:bg-slate-800/50 rounded-lg p-2">
                <span className="font-medium">{t('agent.hitl.status.configured')}: </span>{' '}
                {event.providedVariables?.join(', ')}
              </div>
            )}
          </div>
        </div>
        <div className="pl-12">
          <TimeBadge timestamp={event.timestamp} />
        </div>
      </div>
    );
  },
  (prev, next) => {
    return prev.event.id === next.event.id && prev.event.answered === next.event.answered;
  }
);
