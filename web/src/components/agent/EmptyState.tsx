/**
 * EmptyState - Modern welcome screen when no conversation is active
 *
 * Features:
 * - Focused welcome state
 * - Compact suggestion list that sends actual prompts
 * - Quick action suggestions that send actual prompts
 * - Keyboard shortcut hints
 */

import React from 'react';

import { useTranslation } from 'react-i18next';

import {
  Plus,
  Bot,
  BarChart3,
  FileText,
  Code,
  MessageSquare,
  Keyboard,
  ArrowRight,
  History,
} from 'lucide-react';

import { LazyButton } from '@/components/ui/lazyAntd';

import { ProjectContextCard } from './chat/ProjectContextCard';
import { RecentSkills } from './chat/RecentSkills';
import { TrendingEntities } from './chat/TrendingEntities';

interface EmptyStateProps {
  onNewConversation: () => void;
  onSendPrompt?: ((prompt: string) => void) | undefined;
  lastConversation?: { id: string; title: string; updated_at?: string | undefined } | undefined;
  onResumeConversation?: ((id: string) => void) | undefined;
  projectId?: string | undefined;
}

function formatRelativeTime(dateStr: string, locale: string): string {
  try {
    const now = Date.now();
    const then = new Date(dateStr).getTime();
    if (isNaN(then)) return '';
    const diffSeconds = Math.round((now - then) / 1000);

    const rtf = new Intl.RelativeTimeFormat(locale || undefined, { numeric: 'auto' });

    if (diffSeconds < 60) return rtf.format(-diffSeconds, 'second');
    const diffMinutes = Math.round(diffSeconds / 60);
    if (diffMinutes < 60) return rtf.format(-diffMinutes, 'minute');
    const diffHours = Math.round(diffMinutes / 60);
    if (diffHours < 24) return rtf.format(-diffHours, 'hour');
    const diffDays = Math.round(diffHours / 24);
    return rtf.format(-diffDays, 'day');
  } catch {
    return '';
  }
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  onNewConversation,
  onSendPrompt,
  lastConversation,
  onResumeConversation,
  projectId,
}) => {
  const { t, i18n } = useTranslation();

  const handleCardClick = (prompt: string) => {
    if (onSendPrompt) {
      onSendPrompt(prompt);
    } else {
      onNewConversation();
    }
  };

  const suggestionCards = [
    {
      icon: <BarChart3 size={20} />,
      title: t('agent.emptyState.cards.analyzeTrends', 'Analyze project trends'),
      description: t(
        'agent.emptyState.cards.analyzeTrendsDesc',
        'Identify key patterns and insights across your data'
      ),
      prompt: t(
        'agent.emptyState.cards.analyzeTrendsPrompt',
        'Analyze the trends and patterns in my project data. Identify key insights and anomalies.'
      ),
    },
    {
      icon: <FileText size={20} />,
      title: t('agent.emptyState.cards.synthesizeReports', 'Synthesize reports'),
      description: t(
        'agent.emptyState.cards.synthesizeReportsDesc',
        'Transform complex findings into executive summaries'
      ),
      prompt: t(
        'agent.emptyState.cards.synthesizeReportsPrompt',
        'Help me synthesize a report from my recent findings. Create a clear executive summary.'
      ),
    },
    {
      icon: <Code size={20} />,
      title: t('agent.emptyState.cards.generateCode', 'Generate code'),
      description: t(
        'agent.emptyState.cards.generateCodeDesc',
        'Write, review, and optimize code with AI assistance'
      ),
      prompt: t(
        'agent.emptyState.cards.generateCodePrompt',
        'Help me write code. What programming language and task do you need help with?'
      ),
    },
  ];

  return (
    <div className="relative flex h-full w-full overflow-y-auto px-4 py-5 sm:px-6 lg:px-8">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 sm:gap-5">
        <section className="rounded-lg border border-slate-200/70 bg-white/90 px-4 py-4 shadow-[0_1px_2px_rgba(15,23,42,0.03)] dark:border-slate-800/70 dark:bg-slate-900/70 sm:px-5">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="flex min-w-0 items-start gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary text-white shadow-sm">
                <Bot size={22} />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-medium uppercase tracking-normal text-primary">
                  {t('agent.emptyState.workbenchLabel', 'Agent workspace')}
                </p>
                <h2 className="mt-1 text-xl font-semibold leading-tight text-slate-950 dark:text-slate-100 sm:text-2xl">
                  {t('agent.emptyState.greeting', 'What are you working on?')}
                </h2>
                <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500 dark:text-slate-400">
                  {t(
                    'agent.emptyState.subtitle',
                    'Start a conversation or pick a suggestion below.'
                  )}
                </p>
              </div>
            </div>

            <LazyButton
              type="primary"
              size="large"
              icon={<Plus size={18} />}
              onClick={onNewConversation}
              className="h-10 shrink-0 rounded-lg px-5 text-sm font-medium shadow-sm"
            >
              {t('agent.emptyState.newConversation', 'Start New Conversation')}
            </LazyButton>
          </div>
        </section>

        {lastConversation && onResumeConversation && (
          <button
            type="button"
            onClick={() => {
              onResumeConversation(lastConversation.id);
            }}
            className="group flex w-full items-center gap-3 rounded-lg border border-primary/25 bg-white px-4 py-3 text-left shadow-[0_1px_2px_rgba(15,23,42,0.03)] transition-[border-color,background-color,box-shadow] duration-150 hover:border-primary/45 hover:shadow-md dark:border-primary/25 dark:bg-slate-900/70"
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary dark:bg-primary/20">
              <History size={18} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
                {t('agent.emptyState.continueTitle', 'Continue where you left off')}
              </p>
              <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                {lastConversation.title}
              </p>
              {lastConversation.updated_at && (
                <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">
                  {formatRelativeTime(lastConversation.updated_at, i18n.language)}
                </p>
              )}
            </div>
            <span className="hidden shrink-0 items-center gap-1 rounded-md bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary transition-colors group-hover:bg-primary group-hover:text-white sm:inline-flex">
              {t('agent.emptyState.continueAction', 'Resume')}
              <ArrowRight size={13} />
            </span>
          </button>
        )}

        {projectId && (
          <section className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_1.25fr]">
            <ProjectContextCard projectId={projectId} />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <TrendingEntities projectId={projectId} onEntityClick={onSendPrompt} />
              <RecentSkills projectId={projectId} onSkillClick={onSendPrompt} />
            </div>
          </section>
        )}

        <section className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {suggestionCards.map((card) => (
            <button
              key={card.title}
              type="button"
              onClick={() => {
                handleCardClick(card.prompt);
              }}
              className="group flex min-h-24 items-start gap-3 rounded-lg border border-slate-200 bg-white p-4 text-left shadow-[0_1px_2px_rgba(15,23,42,0.025)] transition-[border-color,background-color,box-shadow] duration-150 hover:border-primary/35 hover:bg-slate-50 dark:border-slate-800/70 dark:bg-slate-900/65 dark:hover:bg-slate-800/60"
            >
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary dark:bg-primary/15">
                {card.icon}
              </div>

              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {card.title}
                </h3>

                <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                  {card.description}
                </p>
              </div>
              <ArrowRight
                size={14}
                className="mt-1 shrink-0 text-slate-300 opacity-0 transition-opacity duration-150 group-hover:opacity-100 dark:text-slate-600"
              />
            </button>
          ))}
        </section>

        <div className="pb-2 text-center">
          <p className="flex flex-wrap items-center justify-center gap-3 text-xs text-slate-400 dark:text-slate-500">
            <span className="flex items-center gap-1.5">
              <MessageSquare size={12} />
              {t('agent.emptyState.naturalLanguage', 'Natural language conversations')}
            </span>
            <span className="h-1 w-1 rounded-full bg-slate-300 dark:bg-slate-600" />
            <span className="flex items-center gap-1.5">
              <kbd className="rounded border border-slate-200 bg-slate-100 px-1.5 py-0.5 font-sans text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400">
                /
              </kbd>
              {t('agent.emptyState.forCommands', 'for commands')}
            </span>
            <span className="h-1 w-1 rounded-full bg-slate-300 dark:bg-slate-600" />
            <span className="flex items-center gap-1.5">
              <Keyboard size={12} />
              <kbd className="rounded border border-slate-200 bg-slate-100 px-1.5 py-0.5 font-sans text-2xs text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400">
                {t('agent.emptyState.cmdKey', 'Cmd')}+1-5
              </kbd>
              {t('agent.emptyState.layoutModes', 'layout modes')}
            </span>
          </p>
        </div>
      </div>
    </div>
  );
};

export default EmptyState;
