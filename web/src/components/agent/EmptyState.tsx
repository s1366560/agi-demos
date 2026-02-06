/**
 * EmptyState - Modern welcome screen when no conversation is active
 *
 * Features:
 * - Animated gradient background
 * - Modern card design with hover effects
 * - Quick action suggestions
 * - Smooth animations
 */

import React from 'react';

import {
  Plus,
  Sparkles,
  BarChart3,
  FileText,
  Search,
  Code,
  MessageSquare,
  Zap,
} from 'lucide-react';

import { LazyButton } from '@/components/ui/lazyAntd';

interface EmptyStateProps {
  onNewConversation: () => void;
}

const suggestionCards = [
  {
    icon: <BarChart3 size={20} />,
    title: 'Analyze project trends',
    description: 'Identify key patterns and insights across your data streams',
    color: 'from-blue-500/10 to-blue-600/5',
    iconColor: 'text-blue-500',
    borderColor: 'border-blue-200/50 dark:border-blue-800/30',
    hoverBorder: 'hover:border-blue-300 dark:hover:border-blue-700',
  },
  {
    icon: <FileText size={20} />,
    title: 'Synthesize reports',
    description: 'Transform complex findings into executive summaries',
    color: 'from-purple-500/10 to-purple-600/5',
    iconColor: 'text-purple-500',
    borderColor: 'border-purple-200/50 dark:border-purple-800/30',
    hoverBorder: 'hover:border-purple-300 dark:hover:border-purple-700',
  },
  {
    icon: <Code size={20} />,
    title: 'Generate code',
    description: 'Write, review, and optimize code with AI assistance',
    color: 'from-emerald-500/10 to-emerald-600/5',
    iconColor: 'text-emerald-500',
    borderColor: 'border-emerald-200/50 dark:border-emerald-800/30',
    hoverBorder: 'hover:border-emerald-300 dark:hover:border-emerald-700',
  },
  {
    icon: <Zap size={20} />,
    title: 'Quick automation',
    description: 'Build workflows and automate repetitive tasks',
    color: 'from-amber-500/10 to-amber-600/5',
    iconColor: 'text-amber-500',
    borderColor: 'border-amber-200/50 dark:border-amber-800/30',
    hoverBorder: 'hover:border-amber-300 dark:hover:border-amber-700',
  },
];

export const EmptyState: React.FC<EmptyStateProps> = ({ onNewConversation }) => {
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
          How can I help you today?
        </h1>

        {/* Subtitle */}
        <p className="text-slate-500 dark:text-slate-400 max-w-md mx-auto mb-8 text-base leading-relaxed">
          Your intelligent AI assistant is ready to help with analysis, coding, writing, and more.
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
          Start New Conversation
        </LazyButton>
      </div>

      {/* Suggestion Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl w-full relative z-10">
        {suggestionCards.map((card, index) => (
          <button
            key={index}
            onClick={onNewConversation}
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
              {/* Icon */}
              <div
                className={`
                w-11 h-11 rounded-xl mb-4
                bg-gradient-to-br ${card.color}
                border ${card.borderColor}
                flex items-center justify-center
                group-hover:scale-110 transition-transform duration-300
                ${card.iconColor}
              `}
              >
                {card.icon}
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
        <p className="text-xs text-slate-400 dark:text-slate-500 flex items-center justify-center gap-3">
          <span className="flex items-center gap-1.5">
            <MessageSquare size={12} />
            Natural language conversations
          </span>
          <span className="w-1 h-1 rounded-full bg-slate-300 dark:bg-slate-600" />
          <span className="flex items-center gap-1.5">
            <kbd className="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-slate-500 dark:text-slate-400 font-sans">
              /
            </kbd>
            for commands
          </span>
        </p>
      </div>
    </div>
  );
};

export default EmptyState;
