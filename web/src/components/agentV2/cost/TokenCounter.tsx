/**
 * Token Counter
 *
 * Compact display of current token usage.
 */

import { useTotalTokens } from "../../../stores/agentV2";

interface TokenCounterProps {
  showLabel?: boolean;
}

export function TokenCounter({ showLabel = false }: TokenCounterProps) {
  const totalTokens = useTotalTokens();

  if (totalTokens === 0) return null;

  return (
    <div className="flex items-center gap-2">
      {showLabel && (
        <span className="text-xs text-gray-500 dark:text-gray-400">
          Tokens:
        </span>
      )}
      <span className="text-sm font-mono text-gray-700 dark:text-gray-300">
        {totalTokens.toLocaleString()}
      </span>
    </div>
  );
}
