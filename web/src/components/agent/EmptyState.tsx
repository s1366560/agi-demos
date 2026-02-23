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
  Sparkles,
  BarChart3,
  FileText,
  Code,
  MessageSquare,
  Zap,
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
  onSendPrompt?: (prompt: string) => void;
  lastConversation?: { id: string; title: string; updated_at?: string };
  onResumeConversation?: (id: string) => void;
  projectId?: string;
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
        'Identify key patterns and insights across your data streams'
      ),
      prompt: t(
        'agent.emptyState.cards.analyzeTrendsPrompt',
        'Analyze the trends and patterns in my project data. Identify key insights and anomalies.'
      ),
      color: 'from-blue-500/10 to-blue-600/5',
      iconColor: 'text-blue-500',
      borderColor: 'border-blue-200/50 dark:border-blue-800/30',
      hoverBorder: 'hover:border-blue-300 dark:hover:border-blue-700',
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
      color: 'from-purple-500/10 to-purple-600/5',
      iconColor: 'text-purple-500',
      borderColor: 'border-purple-200/50 dark:border-purple-800/30',
      hoverBorder: 'hover:border-purple-300 dark:hover:border-purple-700',
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
      color: 'from-emerald-500/10 to-emerald-600/5',
      iconColor: 'text-emerald-500',
      borderColor: 'border-emerald-200/50 dark:border-emerald-800/30',
      hoverBorder: 'hover:border-emerald-300 dark:hover:border-emerald-700',
    },
    {
      icon: <Zap size={20} />,
      title: t('agent.emptyState.cards.quickAutomation', 'Quick automation'),
      description: t(
        'agent.emptyState.cards.quickAutomationDesc',
        'Build workflows and automate repetitive tasks'
      ),
      prompt: t(
        'agent.emptyState.cards.quickAutomationPrompt',
        'Help me automate a repetitive task. Describe the workflow you want to streamline.'
      ),
      color: 'from-amber-500/10 to-amber-600/5',
      iconColor: 'text-amber-500',
      borderColor: 'border-amber-200/50 dark:border-amber-800/30',
      hoverBorder: 'hover:border-amber-300 dark:hover:border-amber-700',
    },
  ];

  return (
    <div className="h-full w-full flex flex-col items-center justify-center p-6 overflow-y-auto relative">
      {/* Animated gradient background */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/5 rounded-full blur-3xl animate-pulse-slow" />
        <div
          className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-purple-500/5 rounded-full blur-3xl animate-pulse-slow"
          style={{ animationDelay: '1s' }}
        />
      </div>

      {/* Main Content */}
      <div className="text-center mb-10 relative z-10">
        {/* Logo/Icon with glow effect */}
        <div className="relative inline-block mb-6">
          <div className="absolute inset-0 bg-primary/20 rounded-3xl blur-xl animate-pulse-slow" />
          <div className="relative w-20 h-20 rounded-2xl bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center shadow-xl shadow-primary/25">
            <Sparkles size={40} className="text-white" />
          </div>
        </div>

        {/* Title */}
        <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-3">
          {t('agent.emptyState.greeting', 'How can I help you today?')}
        </h1>

        {/* Subtitle */}
        <p className="text-slate-500 dark:text-slate-400 max-w-md mx-auto mb-8 text-base leading-relaxed">
          {t(
            'agent.emptyState.subtitle',
            'Your intelligent AI assistant is ready to help with analysis, coding, writing, and more.'
          )}
        </p>

        {/* New Chat Button */}
        <LazyButton
          type="primary"
          size="large"
          icon={<Plus size={20} />}
          onClick={onNewConversation}
          className="
            h-12 px-8 rounded-xl
            bg-gradient-to-r from-primary to-primary-600
            hover:from-primary-600 hover:to-primary-700
            shadow-lg shadow-primary/25 hover:shadow-xl hover:shadow-primary/30
            text-base font-medium
            transition-all duration-300
            hover:-translate-y-0.5
          "
        >
          {t('agent.emptyState.newConversation', 'Start New Conversation')}
        </LazyButton>
      </div>

      {/* Resume Card */}
      {lastConversation && onResumeConversation && (
        <div className="max-w-2xl w-full relative z-10 mb-4">
          <button
            onClick={() => onResumeConversation(lastConversation.id)}
            className="
              group w-full flex items-center gap-4 p-4 rounded-xl
              bg-white dark:bg-slate-800/50
              border-l-4 border-l-primary border border-slate-200/50 dark:border-slate-700/30
              hover:shadow-lg hover:shadow-primary/10
              transition-all duration-300 ease-out
              text-left
              hover:-translate-y-0.5
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

      {/* Project Context */}
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
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl w-full relative z-10">
        {suggestionCards.map((card, index) => (
          <button
            key={index}
            onClick={() => handleCardClick(card.prompt)}
            className={`
              group relative p-5 rounded-2xl
              bg-white dark:bg-slate-800/50
              border ${card.borderColor} ${card.hoverBorder}
              hover:shadow-lg hover:shadow-slate-200/50 dark:hover:shadow-black/20
              transition-all duration-300 ease-out
              text-left
              hover:-translate-y-0.5
              overflow-hidden
            `}
          >
            {/* Gradient background on hover */}
            <div
              className={`absolute inset-0 bg-gradient-to-br ${card.color} opacity-0 group-hover:opacity-100 transition-opacity duration-300`}
            />

            <div className="relative z-10">
              {/* Icon + Arrow */}
              <div className="flex items-start justify-between mb-4">
                <div
                  className={`
                  w-11 h-11 rounded-xl
                  bg-gradient-to-br ${card.color}
                  border ${card.borderColor}
                  flex items-center justify-center
                  group-hover:scale-110 transition-transform duration-300
                  ${card.iconColor}
                `}
                >
                  {card.icon}
                </div>
                <ArrowRight
                  size={16}
                  className="text-slate-300 dark:text-slate-600 opacity-0 group-hover:opacity-100 group-hover:translate-x-1 transition-all duration-300"
                />
              </div>

              {/* Title */}
              <h3 className="font-semibold text-slate-900 dark:text-slate-100 mb-1.5 text-base">
                {card.title}
              </h3>

              {/* Description */}
              <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">
                {card.description}
              </p>
            </div>
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
