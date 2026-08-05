import { useCallback, useEffect, useRef, useState } from 'react';

import {
  runInputService,
  type ActiveAgentRun,
  type AgentRunInput,
  type RunInputContextItem,
  type RunInputDelivery,
  type RunInputReference,
  type RunInputReceipt,
} from '@/services/runInputService';

const newProtocolId = (prefix: string): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
};

export interface RunInputAuthorityController {
  activeRun: ActiveAgentRun | null;
  loading: boolean;
  submitting: boolean;
  error: string | null;
  lastReceipt: RunInputReceipt | null;
  inputs: AgentRunInput[];
  promotingInputId: string | null;
  refresh: () => Promise<void>;
  submit: (
    message: string,
    delivery: RunInputDelivery,
    context?: RunInputSubmissionContext
  ) => Promise<boolean>;
  promote: (inputId: string) => Promise<boolean>;
}

export interface RunInputSubmissionContext {
  references?: RunInputReference[];
  contextItems?: RunInputContextItem[];
}

export function useRunInputAuthority(
  conversationId: string | null | undefined,
  streaming: boolean
): RunInputAuthorityController {
  const requestRevision = useRef(0);
  const pendingSubmissionIdentity = useRef<{
    signature: string;
    messageId: string;
    idempotencyKey: string;
  } | null>(null);
  const [activeRun, setActiveRun] = useState<ActiveAgentRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastReceipt, setLastReceipt] = useState<RunInputReceipt | null>(null);
  const [inputs, setInputs] = useState<AgentRunInput[]>([]);
  const [promotingInputId, setPromotingInputId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!conversationId) {
      setActiveRun(null);
      setLoading(false);
      return;
    }
    const revision = ++requestRevision.current;
    setLoading(true);
    setError(null);
    try {
      const run = streaming
        ? await runInputService.getActiveRun(conversationId)
        : await runInputService.getLatestRun(conversationId);
      if (requestRevision.current === revision) {
        setActiveRun(run);
        if (run) {
          const inputList = await runInputService.list(run.run_id);
          if (requestRevision.current === revision) {
            setInputs(inputList.inputs);
          }
        } else {
          setInputs([]);
        }
      }
    } catch (caught) {
      if (requestRevision.current === revision) {
        setActiveRun(null);
        setError(caught instanceof Error ? caught.message : String(caught));
      }
    } finally {
      if (requestRevision.current === revision) {
        setLoading(false);
      }
    }
  }, [conversationId, streaming]);

  useEffect(() => {
    setActiveRun(null);
    setLastReceipt(null);
    setInputs([]);
    pendingSubmissionIdentity.current = null;
  }, [conversationId]);

  useEffect(() => {
    void refresh();
    return () => {
      requestRevision.current += 1;
    };
  }, [refresh]);

  const submit = useCallback(
    async (
      message: string,
      delivery: RunInputDelivery,
      context?: RunInputSubmissionContext
    ): Promise<boolean> => {
      const trimmed = message.trim();
      if (
        !trimmed ||
        !activeRun ||
        activeRun.status !== 'running' ||
        !activeRun.allowed_actions.includes(delivery)
      ) {
        setError('run_input_unavailable');
        return false;
      }
      setSubmitting(true);
      setError(null);
      const references = context?.references ?? [];
      const contextItems = context?.contextItems ?? [];
      const signature = JSON.stringify({
        runId: activeRun.run_id,
        runRevision: activeRun.run_revision,
        message: trimmed,
        delivery,
        references,
        contextItems,
      });
      if (pendingSubmissionIdentity.current?.signature !== signature) {
        pendingSubmissionIdentity.current = {
          signature,
          messageId: newProtocolId('message'),
          idempotencyKey: newProtocolId('run-input'),
        };
      }
      const commandIdentity = pendingSubmissionIdentity.current;
      try {
        const receipt = await runInputService.create(activeRun.run_id, {
          expected_run_revision: activeRun.run_revision,
          message: trimmed,
          message_id: commandIdentity.messageId,
          idempotency_key: commandIdentity.idempotencyKey,
          delivery,
          references,
          context_items: contextItems,
        });
        if (!receipt.accepted) {
          setError('run_input_rejected');
          return false;
        }
        setLastReceipt(receipt);
        pendingSubmissionIdentity.current = null;
        setInputs((current) => {
          const next = current.filter((item) => item.id !== receipt.input.id);
          return [...next, receipt.input].sort((left, right) => left.sequence - right.sequence);
        });
        setActiveRun((current) =>
          current && current.run_id === receipt.run_id
            ? { ...current, run_revision: receipt.run_revision }
            : current
        );
        return true;
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [activeRun]
  );

  const promote = useCallback(
    async (inputId: string): Promise<boolean> => {
      const input = inputs.find((candidate) => candidate.id === inputId);
      if (!activeRun || input?.status !== 'ready') {
        setError('run_input_promotion_unavailable');
        return false;
      }
      setPromotingInputId(inputId);
      setError(null);
      try {
        const receipt = await runInputService.promote(activeRun.run_id, inputId, {
          expected_source_run_revision: activeRun.run_revision,
          idempotency_key: newProtocolId('run-input-promote'),
        });
        if (!receipt.accepted) {
          setError('run_input_promotion_rejected');
          return false;
        }
        await refresh();
        return true;
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : String(caught));
        return false;
      } finally {
        setPromotingInputId(null);
      }
    },
    [activeRun, inputs, refresh]
  );

  return {
    activeRun,
    loading,
    submitting,
    error,
    lastReceipt,
    inputs,
    promotingInputId,
    refresh,
    submit,
    promote,
  };
}
