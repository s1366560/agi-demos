/**
 * EmptyState - Welcome screen when no conversation is active
 */

import React from 'react';
import { Button } from 'antd';
import { Plus, Sparkles, BarChart3, FileText, Search } from 'lucide-react';

interface EmptyStateProps {
  onNewConversation: () => void;
}

const suggestionCards = [
  {
    icon: <BarChart3 size={20} className="text-blue-500" />,
    title: 'Analyze project trends',
    description: 'Identify key patterns across multiple data streams',
    color: 'bg-blue-50 dark:bg-blue-900/20',
  },
  {
    icon: <FileText size={20} className="text-purple-500" />,
    title: 'Synthesize reports',
    description: 'Aggregate complex findings into an executive summary',
    color: 'bg-purple-50 dark:bg-purple-900/20',
  },
  {
    icon: <Search size={20} className="text-emerald-500" />,
    title: 'Audit memory logs',
    description: 'Review system activity and trace data genealogy',
    color: 'bg-emerald-50 dark:bg-emerald-900/20',
  },
  {
    icon: <Sparkles size={20} className="text-amber-500" />,
    title: 'Cross-project comparison',
    description: 'Compare performance metrics between active projects',
    color: 'bg-amber-50 dark:bg-amber-900/20',
  },
];

export const EmptyState: React.FC<EmptyStateProps> = ({ onNewConversation }) => {
  return (
    <div className="h-full w-full flex flex-col items-center justify-center p-8 overflow-y-auto">
      {/* Main Content */}
      <div className="text-center mb-12">
        {/* Logo/Icon */}
        <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-primary to-primary-600 flex items-center justify-center shadow-xl shadow-primary/20">
          <Sparkles size={40} className="text-white" />
        </div>

        {/* Title */}
        <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-3">
          How can I help you today?
        </h1>

        {/* Subtitle */}
        <p className="text-slate-500 dark:text-slate-400 max-w-md mx-auto mb-8">
          Access your intelligent memory workspace. Start a conversation or select a suggested task below.
        </p>

        {/* New Chat Button */}
        <Button
          type="primary"
          size="large"
          icon={<Plus size={18} />}
          onClick={onNewConversation}
          className="h-12 px-6 bg-primary hover:bg-primary-600 shadow-lg shadow-primary/20 rounded-xl"
        >
          Start New Conversation
        </Button>
      </div>

      {/* Suggestion Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-3xl w-full">
        {suggestionCards.map((card, index) => (
          <button
            key={index}
            onClick={onNewConversation}
            className="
              p-4 rounded-xl border border-slate-200 dark:border-slate-800
              bg-white dark:bg-slate-800/50
              hover:border-primary/30 hover:shadow-md
              transition-all duration-200
              text-left group
            "
          >
            <div className={`
              w-10 h-10 rounded-lg ${card.color} 
              flex items-center justify-center mb-3
              group-hover:scale-110 transition-transform
            `}>
              {card.icon}
            </div>
            <h3 className="font-semibold text-slate-900 dark:text-slate-100 mb-1">
              {card.title}
            </h3>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {card.description}
            </p>
          </button>
        ))}
      </div>

      {/* Footer */}
      <p className="mt-12 text-xs text-slate-400">
        Press <kbd className="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-800 rounded">/</kbd> to access commands
      </p>
    </div>
  );
};
