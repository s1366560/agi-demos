/**
 * EmptyState - Modern welcome screen when no conversation is active
 *
 * Features:
 * - Animated gradient background
 * - Modern card design with hover effects
 * - Quick action suggestions that send actual prompts
 * - Keyboard shortcut hints
 * - Smooth animations
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

function formatRelativeTime(dateStr: string): string {
  try {
    const now = Date.now();
    const then = new Date(dateStr).getTime();
    if (isNaN(then)) return '';
    const diffSeconds = Math.round((now - then) / 1000);

    const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

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
  const { t } = useTranslation();

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
    <div className="h-full w-full flex flex-col items-center justify-center p-6 overflow-y-auto relative">
      {/* Main Content */}
      <div className="text-center mb-10 relative z-10">
        {/* Logo/Icon with glow effect */}
        <div className="relative inline-block mb-6">
          <div className="relative w-16 h-16 rounded-xl bg-primary flex items-center justify-center shadow-md">
            <Bot size={32} className="text-white" />
          </div>
        </div>

        {/* Title */}
        <h2 className="text-2xl font-semibold text-slate-900 dark:text-slate-100 mb-2">
          {t('agent.emptyState.greeting', 'What are you working on?')}
        </h2>

        {/* Subtitle */}
        <p className="text-slate-400 dark:text-slate-500 max-w-md mx-auto mb-8 text-sm leading-relaxed">
          {t('agent.emptyState.subtitle', 'Start a conversation or pick a suggestion below.')}
        </p>

        {/* New Chat Button */}
        <LazyButton
          type="primary"
          size="large"
          icon={<Plus size={20} />}
          onClick={onNewConversation}
          className="
            h-12 px-8 rounded-xl
            bg-primary hover:bg-primary-600
            shadow-sm hover:shadow-md
            text-base font-medium
            transition-colors duration-200
          "
        >
          {t('agent.emptyState.newConversation', 'Start New Conversation')}
        </LazyButton>
      </div>

      {/* Resume Card */}
      {lastConversation && onResumeConversation && (
        <div className="max-w-2xl w-full relative z-10 mb-4">
          <button
            type="button"
            onClick={() => {
              onResumeConversation(lastConversation.id);
            }}
            className="
              group w-full flex items-center gap-4 p-4 rounded-xl
              bg-white dark:bg-slate-800/50
              border-l-4 border-l-primary border border-slate-200/50 dark:border-slate-700/30
              hover:shadow-lg hover:shadow-primary/10
              transition-shadow duration-200 ease-out
              text-left
            "
          >
            <div
              className="
              flex-shrink-0 w-10 h-10 rounded-lg
              bg-primary/10 dark:bg-primary/20
              flex items-center justify-center
              text-primary
              group-hover:scale-110 transition-transform duration-300
            "
            >
              <History size={20} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400">
                {t('agent.emptyState.continueTitle', 'Continue where you left off')}
              </p>
              <p className="text-base font-semibold text-slate-900 dark:text-slate-100 truncate">
                {lastConversation.title}
              </p>
              {lastConversation.updated_at && (
                <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
                  {formatRelativeTime(lastConversation.updated_at)}
                </p>
              )}
            </div>
            <div
              className="
              flex-shrink-0 px-4 py-1.5 rounded-lg
              bg-primary/10 dark:bg-primary/20
              text-primary text-sm font-medium
              group-hover:bg-primary group-hover:text-white
              transition-colors duration-300
            "
            >
              {t('agent.emptyState.continueAction', 'Resume')}
            </div>
          </button>
        </div>
      )}

      {/* Project Context — shown above suggestions when available */}
      {projectId && (
        <div className="space-y-4 mb-6 max-w-2xl w-full relative z-10">
          <ProjectContextCard projectId={projectId} />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <TrendingEntities projectId={projectId} onEntityClick={onSendPrompt} />
            <RecentSkills projectId={projectId} onSkillClick={onSendPrompt} />
          </div>
        </div>
      )}

      {/* Suggestion Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-2xl w-full relative z-10">
        {suggestionCards.map((card) => (
          <button
            key={card.title}
            type="button"
            onClick={() => {
              handleCardClick(card.prompt);
            }}
            className="
              group relative p-4 rounded-xl
              bg-white dark:bg-slate-800/50
              border border-slate-200 dark:border-slate-700/50
              hover:border-slate-300 dark:hover:border-slate-600
              hover:shadow-md
              transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200 ease-out
              text-left
            "
          >
            <div className="flex items-start justify-between mb-3">
              <div
                className="
                  w-10 h-10 rounded-lg
                  bg-primary/8 dark:bg-primary/15
                  flex items-center justify-center
                  text-primary
                "
              >
                {card.icon}
              </div>
              <ArrowRight
                size={14}
                className="text-slate-300 dark:text-slate-600 opacity-0 group-hover:opacity-100 group-hover:translate-x-0.5 transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-200"
              />
            </div>

            <h3 className="font-medium text-slate-900 dark:text-slate-100 mb-1 text-sm">
              {card.title}
            </h3>

            <p className="text-xs text-slate-400 dark:text-slate-500 leading-relaxed">
              {card.description}
            </p>
          </button>
        ))}
      </div>

      {/* Footer tips */}
      <div className="mt-10 text-center relative z-10">
        <p className="text-xs text-slate-400 dark:text-slate-500 flex items-center justify-center gap-3 flex-wrap">
          <span className="flex items-center gap-1.5">
            <MessageSquare size={12} />
            {t('agent.emptyState.naturalLanguage', 'Natural language conversations')}
          </span>
          <span className="w-1 h-1 rounded-full bg-slate-300 dark:bg-slate-600" />
          <span className="flex items-center gap-1.5">
            <kbd className="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-slate-500 dark:text-slate-400 font-sans">
              /
            </kbd>
            {t('agent.emptyState.forCommands', 'for commands')}
          </span>
          <span className="w-1 h-1 rounded-full bg-slate-300 dark:bg-slate-600" />
          <span className="flex items-center gap-1.5">
            <Keyboard size={12} />
            <kbd className="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-slate-500 dark:text-slate-400 font-sans text-[10px]">
              {t('agent.emptyState.cmdKey', 'Cmd')}+1-5
            </kbd>
            {t('agent.emptyState.layoutModes', 'layout modes')}
          </span>
        </p>
      </div>
    </div>
  );
};

export default EmptyState;
