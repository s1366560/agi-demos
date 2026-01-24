/**
 * Cost Summary
 *
 * Displays token usage and cost information.
 */

import { useState } from 'react';
import { DownOutlined, RightOutlined } from '@ant-design/icons';
import { useTotalTokens, useTotalCost, useTokenBreakdown } from '../../../stores/agentV2';

interface CostSummaryProps {
  variant?: 'inline' | 'detailed';
}

export function CostSummary({ variant = 'inline' }: CostSummaryProps) {
  const totalTokens = useTotalTokens();
  const totalCost = useTotalCost();
  const tokenBreakdown = useTokenBreakdown();
  const [isExpanded, setIsExpanded] = useState(false);

  // Only show if there's data
  if (totalTokens === 0 && totalCost === 0) return null;

  return (
    <div className={`text-xs text-gray-500 dark:text-gray-400 ${
      variant === 'detailed' ? 'p-3 bg-gray-50 dark:bg-gray-900/50 rounded-lg' : ''
    }`}>
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1 hover:text-gray-700 dark:hover:text-gray-300 transition-colors"
      >
        {isExpanded ? <DownOutlined /> : <RightOutlined />}
        <span>{totalTokens.toLocaleString()} tokens</span>
        <span>·</span>
        <span>${totalCost.toFixed(4)}</span>
      </button>

      {isExpanded && (
        <div className="mt-2 space-y-1 ml-4">
          <div className="flex justify-between">
            <span>Input tokens:</span>
            <span>{tokenBreakdown.input.toLocaleString()}</span>
          </div>
          <div className="flex justify-between">
            <span>Output tokens:</span>
            <span>{tokenBreakdown.output.toLocaleString()}</span>
          </div>
          {tokenBreakdown.reasoning && (
            <div className="flex justify-between">
              <span>Reasoning tokens:</span>
              <span>{tokenBreakdown.reasoning.toLocaleString()}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
