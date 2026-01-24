/**
 * Human Interaction Dialogs
 *
 * Combined component for clarification, decision, and permission dialogs.
 */

import { useState } from 'react';
import { Modal } from 'antd';
import {
  QuestionCircleOutlined,
  InfoCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';
import {
  usePendingClarification,
  usePendingDecision,
  usePendingPermission,
  useAgentV2Store,
} from '../../../stores/agentV2';

/**
 * Clarification Dialog
 */
function ClarificationDialog() {
  const pending = usePendingClarification();
  const { respondToClarification } = useAgentV2Store();
  const [customAnswer, setCustomAnswer] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!pending) return null;

  const handleOptionClick = async (optionId: string) => {
    setIsSubmitting(true);
    try {
      await respondToClarification(pending.request_id, optionId);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCustomSubmit = async () => {
    if (!customAnswer.trim()) return;
    setIsSubmitting(true);
    try {
      await respondToClarification(pending.request_id, customAnswer.trim());
    } finally {
      setIsSubmitting(false);
      setCustomAnswer('');
    }
  };

  return (
    <Modal
      open={true}
      title={
        <span className="flex items-center gap-2">
          <QuestionCircleOutlined className="text-blue-500" />
          <span>Clarification Needed</span>
        </span>
      }
      onCancel={() => {}}
      footer={null}
      closable={false}
      maskClosable={false}
    >
      <div className="space-y-4">
        <p className="text-gray-700 dark:text-gray-300">{pending.question}</p>

        {/* Options */}
        <div className="space-y-2">
          {pending.options.map((option) => (
            <button
              key={option.id}
              onClick={() => !isSubmitting && handleOptionClick(option.id)}
              disabled={isSubmitting}
              className={`w-full p-4 text-left rounded-lg border transition-all ${
                option.recommended
                  ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20 hover:border-blue-600'
                  : 'border-gray-300 dark:border-gray-700 hover:border-gray-400 dark:hover:border-gray-600'
              } disabled:opacity-50`}
            >
              <div>
                <p className="font-medium text-gray-900 dark:text-gray-100">
                  {option.label}
                  {option.recommended && (
                    <span className="ml-2 text-xs bg-blue-500 text-white px-2 py-0.5 rounded">
                      Recommended
                    </span>
                  )}
                </p>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  {option.description}
                </p>
              </div>
            </button>
          ))}
        </div>

        {/* Custom Answer */}
        {pending.allow_custom && (
          <div className="border-t border-gray-200 dark:border-gray-800 pt-4">
            <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Or provide your own answer:
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                value={customAnswer}
                onChange={(e) => setCustomAnswer(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCustomSubmit()}
                placeholder="Type your answer..."
                className="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-700 rounded-lg focus:ring-2 focus:ring-blue-500 outline-none bg-white dark:bg-gray-800"
                disabled={isSubmitting}
              />
              <button
                onClick={handleCustomSubmit}
                disabled={!customAnswer.trim() || isSubmitting}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50"
              >
                Submit
              </button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}

/**
 * Decision Dialog
 */
function DecisionDialog() {
  const pending = usePendingDecision();
  const { respondToDecision } = useAgentV2Store();
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!pending) return null;

  const handleOptionClick = async (optionId: string) => {
    setIsSubmitting(true);
    try {
      await respondToDecision(pending.request_id, optionId);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      open={true}
      title={
        <span className="flex items-center gap-2">
          <InfoCircleOutlined className="text-purple-500" />
          <span>Decision Required</span>
        </span>
      }
      onCancel={() => {}}
      footer={null}
      closable={false}
      maskClosable={false}
    >
      <div className="space-y-4">
        <p className="text-gray-700 dark:text-gray-300">{pending.question}</p>

        {/* Options */}
        <div className="space-y-3">
          {pending.options.map((option) => (
            <button
              key={option.id}
              onClick={() => !isSubmitting && handleOptionClick(option.id)}
              disabled={isSubmitting}
              className={`w-full p-4 text-left rounded-lg border transition-all ${
                option.recommended
                  ? 'border-purple-500 bg-purple-50 dark:bg-purple-900/20 hover:border-purple-600'
                  : 'border-gray-300 dark:border-gray-700 hover:border-gray-400 dark:hover:border-gray-600'
              } disabled:opacity-50`}
            >
              <div>
                <p className="font-medium text-gray-900 dark:text-gray-100">
                  {option.label}
                  {option.recommended && (
                    <span className="ml-2 text-xs bg-purple-500 text-white px-2 py-0.5 rounded">
                      Recommended
                    </span>
                  )}
                </p>
                <p className="text-sm text-gray-600 dark:text-gray-400">
                  {option.description}
                </p>

                {/* Additional Info */}
                <div className="flex flex-wrap gap-4 mt-3 text-xs text-gray-500 dark:text-gray-400">
                  {option.estimated_time && (
                    <span>⏱️ {option.estimated_time}</span>
                  )}
                  {option.estimated_cost && (
                    <span>💰 ${option.estimated_cost.toFixed(4)}</span>
                  )}
                  {option.risks && option.risks.length > 0 && (
                    <span className="text-red-500">
                      ⚠️ Risks: {option.risks.join(', ')}
                    </span>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </Modal>
  );
}

/**
 * Permission Dialog
 */
function PermissionDialog() {
  const pending = usePendingPermission();
  const { respondToPermission } = useAgentV2Store();
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!pending) return null;

  const handleAllow = async () => {
    setIsSubmitting(true);
    try {
      await respondToPermission(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeny = async () => {
    setIsSubmitting(true);
    try {
      await respondToPermission(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      open={true}
      title={
        <span className="flex items-center gap-2">
          <ExclamationCircleOutlined className="text-amber-500" />
          <span>Permission Request</span>
        </span>
      }
      onCancel={() => {}}
      footer={null}
      closable={false}
      maskClosable={false}
    >
      <div className="space-y-4">
        <p className="text-gray-700 dark:text-gray-300">
          The agent is requesting permission to perform:
        </p>

        <div className="bg-gray-100 dark:bg-gray-900 p-4 rounded-lg">
          <p className="font-medium text-gray-900 dark:text-gray-100">
            {pending.permission}
          </p>
          {pending.patterns && pending.patterns.length > 0 && (
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-2">
              Patterns: {pending.patterns.join(', ')}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-3">
          <button
            onClick={handleDeny}
            disabled={isSubmitting}
            className="px-4 py-2 border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-50"
          >
            Deny
          </button>
          <button
            onClick={handleAllow}
            disabled={isSubmitting}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50"
          >
            Allow
          </button>
        </div>
      </div>
    </Modal>
  );
}

/**
 * Doom Loop Dialog
 */
function DoomLoopDialog() {
  // Doom loop dialog uses a similar pattern to decision dialog
  // For now, we'll implement a basic version
  const [pending, setPending] = useState<{
    tool: string;
    count: number;
    threshold: number;
  } | null>(null);

  if (!pending) return null;

  const handleContinue = async () => {
    setPending(null);
  };

  const handleStop = async () => {
    setPending(null);
  };

  return (
    <Modal
      open={true}
      title={
        <span className="flex items-center gap-2">
          <ExclamationCircleOutlined className="text-red-500" />
          <span>Loop Detected</span>
        </span>
      }
      onCancel={() => setPending(null)}
      footer={null}
    >
      <div className="space-y-4">
        <p className="text-gray-700 dark:text-gray-300">
          The agent appears to be stuck in a loop:
        </p>

        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 rounded-lg">
          <p className="font-medium text-red-900 dark:text-red-100">
            Tool: {pending.tool}
          </p>
          <p className="text-sm text-red-700 dark:text-red-300 mt-2">
            Loop count: {pending.count} / {pending.threshold}
          </p>
        </div>

        <div className="flex justify-end gap-3">
          <button
            onClick={handleStop}
            className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg"
          >
            Stop Execution
          </button>
          <button
            onClick={handleContinue}
            className="px-4 py-2 border border-gray-300 dark:border-gray-700 text-gray-700 dark:text-gray-300 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800"
          >
            Continue Anyway
          </button>
        </div>
      </div>
    </Modal>
  );
}

/**
 * Combined Human Interactions Component
 */
export function HumanInteractions() {
  return (
    <>
      <ClarificationDialog />
      <DecisionDialog />
      <PermissionDialog />
      <DoomLoopDialog />
    </>
  );
}
