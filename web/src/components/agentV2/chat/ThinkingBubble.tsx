/**
 * Thinking Bubble
 *
 * Displays the agent's thinking process with expandable sections.
 */

import { useState } from "react";
import { DownOutlined, RightOutlined, BulbOutlined } from "@ant-design/icons";

interface ThinkingBubbleProps {
  thoughts: Array<{
    id: string;
    content: string;
    level: "work" | "task";
    timestamp: string;
  }>;
  currentLevel?: "work" | "task" | null;
}

export function ThinkingBubble({
  thoughts,
  currentLevel: _currentLevel,
}: ThinkingBubbleProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  if (thoughts.length === 0) return null;

  const levelColors = {
    work: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
    task: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
  };

  const levelLabels = {
    work: "Work-level thinking",
    task: "Task-level thinking",
  };

  return (
    <div className="mb-4">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200 transition-colors"
      >
        {isExpanded ? (
          <DownOutlined className="text-xs" />
        ) : (
          <RightOutlined className="text-xs" />
        )}
        <BulbOutlined className="text-xs" />
        <span>Thinking process ({thoughts.length} steps)</span>
      </button>

      {isExpanded && (
        <div className="mt-2 space-y-2 ml-6">
          {thoughts.map((thought) => (
            <div
              key={thought.id}
              className="flex items-start gap-2 p-3 bg-gray-50 dark:bg-gray-900/50 rounded-lg border border-gray-200 dark:border-gray-800"
            >
              <span
                className={`px-2 py-0.5 text-xs font-medium rounded-full ${
                  levelColors[thought.level]
                }`}
              >
                {levelLabels[thought.level]}
              </span>
              <p className="flex-1 text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
                {thought.content}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
