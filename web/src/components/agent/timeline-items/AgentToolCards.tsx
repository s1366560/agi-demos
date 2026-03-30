import { memo, useState } from 'react';

import { Rocket, CircleStop, Send, Users, Bot, Network, Terminal, History, AlertCircle, Check } from 'lucide-react';

import { AgentSection } from '../chat/MessageStream';

import { TimeBadge } from './shared';

import type { ActEvent, ObserveEvent } from '../../../types/agent';

const AGENT_TOOL_NAMES = new Set([
  'agent_spawn',
  'agent_stop',
  'agent_send',
  'agent_list',
  'agent_sessions',
  'agent_history',
]);

// eslint-disable-next-line react-refresh/only-export-components
export function isAgentTool(toolName: string): boolean {
  return AGENT_TOOL_NAMES.has(toolName);
}

interface StatusBadgeProps {
  status: 'running' | 'success' | 'error';
  label?: string | undefined;
  duration?: number | undefined;
}

function StatusBadge({ status, label, duration }: StatusBadgeProps) {
  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${String(ms)}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${(ms / 60000).toFixed(1)}m`;
  };

  if (status === 'running') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400 text-2xs font-bold uppercase tracking-wider">
        <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse motion-reduce:animate-none" />
        {label ?? 'Running'}
      </span>
    );
  }
  if (status === 'error') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-50 dark:bg-red-500/10 text-red-600 dark:text-red-400 text-2xs font-bold uppercase tracking-wider">
        <AlertCircle size={12} />
        {label ?? 'Error'}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 text-2xs font-bold uppercase tracking-wider">
      <Check size={12} />
      {label ?? 'Done'}
      {duration !== undefined && (
        <span className="ml-0.5 opacity-70">({formatDuration(duration)})</span>
      )}
    </span>
  );
}

function parseResult(raw: unknown): Record<string, unknown> | unknown[] | null {
  if (typeof raw === 'string') {
    try {
      return JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return null;
    }
  }
  if (typeof raw === 'object' && raw !== null) {
    return raw as Record<string, unknown>;
  }
  return null;
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + '...' : s;
}

interface AgentSpawnCardProps {
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  status: 'running' | 'success' | 'error';
  error?: string | undefined;
  duration?: number | undefined;
}

function AgentSpawnCard({ params, result, status, error, duration }: AgentSpawnCardProps) {
  const agentName =
    (result?.['agent_name'] as string | undefined) ??
    (params['agent_id'] as string | undefined) ??
    'Agent';
  const sessionId = result?.['session_id'] as string | undefined;
  const mode =
    (result?.['mode'] as string | undefined) ?? (params['mode'] as string | undefined) ?? 'run';
  const message = params['message'] as string | undefined;

  return (
    <div className="rounded-lg border border-emerald-200 dark:border-emerald-800/50 bg-emerald-50/50 dark:bg-emerald-950/20 overflow-hidden">
      <div className="flex items-center gap-2.5 px-3 py-2 bg-emerald-100/60 dark:bg-emerald-900/30">
        <Rocket size={16} className="text-emerald-600 dark:text-emerald-400" />
        <span className="text-xs font-semibold text-emerald-800 dark:text-emerald-200">
          Spawn Agent
        </span>
        <span className="text-2xs text-emerald-600/70 dark:text-emerald-400/60 bg-emerald-200/60 dark:bg-emerald-800/40 px-1.5 py-0.5 rounded">
          {mode}
        </span>
        <div className="ml-auto">
          <StatusBadge status={status} duration={duration} />
        </div>
      </div>
      <div className="px-3 py-2 space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="text-2xs uppercase tracking-wider text-slate-400 dark:text-slate-500 w-12 shrink-0">
            Agent
          </span>
          <span className="text-xs font-medium text-slate-700 dark:text-slate-200">
            {agentName}
          </span>
        </div>
        {sessionId && (
          <div className="flex items-center gap-2">
            <span className="text-2xs uppercase tracking-wider text-slate-400 dark:text-slate-500 w-12 shrink-0">
              Session
            </span>
            <code className="text-2xs text-slate-500 dark:text-slate-400 font-mono bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
              {sessionId.slice(0, 12)}...
            </code>
          </div>
        )}
        {message && (
          <div className="flex items-start gap-2 mt-1">
            <span className="text-2xs uppercase tracking-wider text-slate-400 dark:text-slate-500 w-12 shrink-0 pt-0.5">
              Task
            </span>
            <span className="text-xs-plus text-slate-600 dark:text-slate-300 leading-relaxed">
              {truncate(message, 200)}
            </span>
          </div>
        )}
        {error && (
          <div className="text-xs-plus text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 rounded px-2 py-1 mt-1">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

interface AgentStopCardProps {
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  status: 'running' | 'success' | 'error';
  error?: string | undefined;
  duration?: number | undefined;
}

function AgentStopCard({ params, result, status, error, duration }: AgentStopCardProps) {
  const sessionId = params['session_id'] as string | undefined;
  const cascade = params['cascade'] as boolean | undefined;
  const stopped = result?.['stopped_sessions'] as string[] | undefined;
  const count = (result?.['count'] as number | undefined) ?? stopped?.length ?? 0;

  return (
    <div className="rounded-lg border border-red-200 dark:border-red-800/50 bg-red-50/50 dark:bg-red-950/20 overflow-hidden">
      <div className="flex items-center gap-2.5 px-3 py-2 bg-red-100/60 dark:bg-red-900/30">
        <CircleStop size={16} className="text-red-600 dark:text-red-400" />
        <span className="text-xs font-semibold text-red-800 dark:text-red-200">Stop Agent</span>
        {cascade && (
          <span className="text-2xs text-red-600/70 dark:text-red-400/60 bg-red-200/60 dark:bg-red-800/40 px-1.5 py-0.5 rounded">
            cascade
          </span>
        )}
        <div className="ml-auto">
          <StatusBadge status={status} duration={duration} />
        </div>
      </div>
      <div className="px-3 py-2 space-y-1.5">
        {sessionId && (
          <div className="flex items-center gap-2">
            <span className="text-2xs uppercase tracking-wider text-slate-400 dark:text-slate-500 w-14 shrink-0">
              Session
            </span>
            <code className="text-2xs text-slate-500 dark:text-slate-400 font-mono bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
              {sessionId.slice(0, 12)}...
            </code>
          </div>
        )}
        {status === 'success' && (
          <div className="flex items-center gap-2">
            <span className="text-2xs uppercase tracking-wider text-slate-400 dark:text-slate-500 w-14 shrink-0">
              Stopped
            </span>
            <span className="text-xs text-slate-600 dark:text-slate-300">
              {count} session{count !== 1 ? 's' : ''}
            </span>
          </div>
        )}
        {error && (
          <div className="text-xs-plus text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 rounded px-2 py-1 mt-1">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

interface AgentSendCardProps {
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  status: 'running' | 'success' | 'error';
  error?: string | undefined;
  duration?: number | undefined;
}

function AgentSendCard({ params, result, status, error, duration }: AgentSendCardProps) {
  const agentId = params['agent_id'] as string | undefined;
  const message = params['message'] as string | undefined;
  const targetSession =
    (result?.['session_id'] as string | undefined) ?? (params['session_id'] as string | undefined);

  return (
    <div className="rounded-lg border border-blue-200 dark:border-blue-800/50 bg-blue-50/50 dark:bg-blue-950/20 overflow-hidden">
      <div className="flex items-center gap-2.5 px-3 py-2 bg-blue-100/60 dark:bg-blue-900/30">
        <Send size={16} className="text-blue-600 dark:text-blue-400" />
        <span className="text-xs font-semibold text-blue-800 dark:text-blue-200">Send Message</span>
        <div className="ml-auto">
          <StatusBadge status={status} duration={duration} />
        </div>
      </div>
      <div className="px-3 py-2 space-y-1.5">
        {agentId && (
          <div className="flex items-center gap-2">
            <span className="text-2xs uppercase tracking-wider text-slate-400 dark:text-slate-500 w-8 shrink-0">
              To
            </span>
            <span className="text-xs font-medium text-slate-700 dark:text-slate-200">
              {truncate(agentId, 24)}
            </span>
          </div>
        )}
        {targetSession && (
          <div className="flex items-center gap-2">
            <span className="text-2xs uppercase tracking-wider text-slate-400 dark:text-slate-500 w-8 shrink-0">
              Sess
            </span>
            <code className="text-2xs text-slate-500 dark:text-slate-400 font-mono bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
              {targetSession.slice(0, 12)}...
            </code>
          </div>
        )}
        {message && (
          <div className="flex items-start gap-2 mt-1">
            <span className="text-2xs uppercase tracking-wider text-slate-400 dark:text-slate-500 w-8 shrink-0 pt-0.5">
              Msg
            </span>
            <span className="text-xs-plus text-slate-600 dark:text-slate-300 leading-relaxed">
              {truncate(message, 200)}
            </span>
          </div>
        )}
        {error && (
          <div className="text-xs-plus text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 rounded px-2 py-1 mt-1">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}

interface AgentListCardProps {
  result: unknown[] | Record<string, unknown> | null;
  status: 'running' | 'success' | 'error';
  error?: string | undefined;
  duration?: number | undefined;
}

function AgentListCard({ result, status, error, duration }: AgentListCardProps) {
  const agents = Array.isArray(result) ? result : [];

  return (
    <div className="rounded-lg border border-violet-200 dark:border-violet-800/50 bg-violet-50/50 dark:bg-violet-950/20 overflow-hidden">
      <div className="flex items-center gap-2.5 px-3 py-2 bg-violet-100/60 dark:bg-violet-900/30">
        <Users size={16} className="text-violet-600 dark:text-violet-400" />
        <span className="text-xs font-semibold text-violet-800 dark:text-violet-200">
          Available Agents
        </span>
        {agents.length > 0 && (
          <span className="text-2xs text-violet-600/70 dark:text-violet-400/60 bg-violet-200/60 dark:bg-violet-800/40 px-1.5 py-0.5 rounded">
            {agents.length}
          </span>
        )}
        <div className="ml-auto">
          <StatusBadge status={status} duration={duration} />
        </div>
      </div>
      {agents.length > 0 && (
        <div className="px-3 py-2 space-y-1.5">
          {agents.map((agent, i) => {
            const a = agent as Record<string, unknown>;
            const name =
              (a['display_name'] as string | undefined) ??
              (a['name'] as string | undefined) ??
              'Unknown';
            const canSpawn = a['can_spawn'] as boolean | undefined;
            const id = (a['id'] as string | undefined) ?? String(i);
            return (
              <div
                key={id}
                className="flex items-center gap-2 py-1 px-2 rounded bg-white/60 dark:bg-slate-800/40"
              >
                <Bot size={14} className="text-violet-500 dark:text-violet-400" />
                <span className="text-xs font-medium text-slate-700 dark:text-slate-200 flex-1">
                  {name}
                </span>
                {canSpawn && (
                  <span className="text-[9px] text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/40 px-1.5 py-0.5 rounded">
                    spawnable
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
      {error && (
        <div className="px-3 pb-2">
          <div className="text-xs-plus text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 rounded px-2 py-1">
            {error}
          </div>
        </div>
      )}
    </div>
  );
}

interface AgentSessionsCardProps {
  result: unknown[] | Record<string, unknown> | null;
  status: 'running' | 'success' | 'error';
  error?: string | undefined;
  duration?: number | undefined;
}

function AgentSessionsCard({ result, status, error, duration }: AgentSessionsCardProps) {
  const sessions = Array.isArray(result) ? result : [];

  return (
    <div className="rounded-lg border border-amber-200 dark:border-amber-800/50 bg-amber-50/50 dark:bg-amber-950/20 overflow-hidden">
      <div className="flex items-center gap-2.5 px-3 py-2 bg-amber-100/60 dark:bg-amber-900/30">
        <Network size={16} className="text-amber-600 dark:text-amber-400" />
        <span className="text-xs font-semibold text-amber-800 dark:text-amber-200">
          Active Sessions
        </span>
        {sessions.length > 0 && (
          <span className="text-2xs text-amber-600/70 dark:text-amber-400/60 bg-amber-200/60 dark:bg-amber-800/40 px-1.5 py-0.5 rounded">
            {sessions.length}
          </span>
        )}
        <div className="ml-auto">
          <StatusBadge status={status} duration={duration} />
        </div>
      </div>
      {sessions.length > 0 && (
        <div className="px-3 py-2 space-y-1.5">
          {sessions.map((session, i) => {
            const s = session as Record<string, unknown>;
            const childId = (s['child_session_id'] as string | undefined) ?? String(i);
            const agentId = s['child_agent_id'] as string | undefined;
            const st = (s['status'] as string | undefined) ?? 'unknown';
            const mode = s['mode'] as string | undefined;
            const taskSummary = s['task_summary'] as string | undefined;
            return (
              <div
                key={childId}
                className="flex items-start gap-2 py-1.5 px-2 rounded bg-white/60 dark:bg-slate-800/40"
              >
                <Terminal size={14} className="text-amber-500 dark:text-amber-400 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <code className="text-2xs text-slate-500 dark:text-slate-400 font-mono">
                      {childId.slice(0, 12)}...
                    </code>
                    {agentId && (
                      <span className="text-2xs text-slate-600 dark:text-slate-300">
                        {truncate(agentId, 16)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span
                      className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded ${
                        st === 'running'
                          ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400'
                          : st === 'completed'
                            ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400'
                            : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400'
                      }`}
                    >
                      {st}
                    </span>
                    {mode && (
                      <span className="text-[9px] text-slate-400 dark:text-slate-500">{mode}</span>
                    )}
                  </div>
                  {taskSummary && (
                    <div className="text-2xs text-slate-500 dark:text-slate-400 mt-0.5 truncate">
                      {truncate(taskSummary, 100)}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {error && (
        <div className="px-3 pb-2">
          <div className="text-xs-plus text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 rounded px-2 py-1">
            {error}
          </div>
        </div>
      )}
    </div>
  );
}

interface AgentHistoryCardProps {
  params: Record<string, unknown>;
  result: unknown[] | Record<string, unknown> | null;
  status: 'running' | 'success' | 'error';
  error?: string | undefined;
  duration?: number | undefined;
}

function AgentHistoryCard({ params, result, status, error, duration }: AgentHistoryCardProps) {
  const [expanded, setExpanded] = useState(false);
  const messages = Array.isArray(result) ? result : [];
  const sessionId = params['session_id'] as string | undefined;
  const visibleMessages = expanded ? messages : messages.slice(0, 3);

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700/50 bg-slate-50/50 dark:bg-slate-950/20 overflow-hidden">
      <div className="flex items-center gap-2.5 px-3 py-2 bg-slate-100/60 dark:bg-slate-800/30">
        <History size={16} className="text-slate-600 dark:text-slate-400" />
        <span className="text-xs font-semibold text-slate-800 dark:text-slate-200">
          Session History
        </span>
        {sessionId && (
          <code className="text-2xs text-slate-500 dark:text-slate-400 font-mono bg-slate-200/60 dark:bg-slate-700/40 px-1.5 py-0.5 rounded">
            {sessionId.slice(0, 12)}...
          </code>
        )}
        {messages.length > 0 && (
          <span className="text-2xs text-slate-500 dark:text-slate-400">
            {messages.length} msg{messages.length !== 1 ? 's' : ''}
          </span>
        )}
        <div className="ml-auto">
          <StatusBadge status={status} duration={duration} />
        </div>
      </div>
      {visibleMessages.length > 0 && (
        <div className="px-3 py-2 space-y-1">
          {visibleMessages.map((msg, i) => {
            const m = msg as Record<string, unknown>;
            const role = (m['message_type'] as string | undefined) ?? 'message';
            const content = (m['content'] as string | undefined) ?? '';
            const from = m['from_agent_id'] as string | undefined;
            return (
              <div
                key={(m['id'] as string | undefined) ?? String(i)}
                className="flex items-start gap-2 py-1 px-2 rounded bg-white/60 dark:bg-slate-800/40"
              >
                <span
                  className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded shrink-0 mt-0.5 ${
                    role === 'task' || role === 'request'
                      ? 'bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400'
                      : role === 'response' || role === 'result'
                        ? 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-600 dark:text-emerald-400'
                        : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400'
                  }`}
                >
                  {role}
                </span>
                {from && (
                  <span className="text-2xs text-slate-400 dark:text-slate-500 shrink-0">
                    {truncate(from, 12)}
                  </span>
                )}
                <span className="text-xs-plus text-slate-600 dark:text-slate-300 leading-relaxed min-w-0 break-words">
                  {truncate(content, 300)}
                </span>
              </div>
            );
          })}
          {messages.length > 3 && (
            <button
              type="button"
              onClick={() => {
                setExpanded((v) => !v);
              }}
              className="text-2xs text-blue-600 dark:text-blue-400 hover:underline cursor-pointer px-2 py-0.5"
            >
              {expanded ? 'Show less' : `Show ${String(messages.length - 3)} more...`}
            </button>
          )}
        </div>
      )}
      {error && (
        <div className="px-3 pb-2">
          <div className="text-xs-plus text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 rounded px-2 py-1">
            {error}
          </div>
        </div>
      )}
    </div>
  );
}

interface AgentToolStepCardProps {
  toolName: string;
  input?: Record<string, unknown>;
  output?: string | Record<string, unknown>;
  status: 'running' | 'success' | 'error';
  isError?: boolean;
  duration?: number;
}

export const AgentToolStepCard = memo(function AgentToolStepCard({
  toolName,
  input,
  output,
  status,
  isError,
  duration,
}: AgentToolStepCardProps) {
  const errorMsg = isError && typeof output === 'string' ? output : undefined;
  const parsed = output ? parseResult(output) : null;
  const params = input ?? {};

  let card: React.ReactNode;

  switch (toolName) {
    case 'agent_spawn':
      card = (
        <AgentSpawnCard
          params={params}
          result={parsed && !Array.isArray(parsed) ? parsed : null}
          status={status}
          error={errorMsg}
          duration={duration}
        />
      );
      break;
    case 'agent_stop':
      card = (
        <AgentStopCard
          params={params}
          result={parsed && !Array.isArray(parsed) ? parsed : null}
          status={status}
          error={errorMsg}
          duration={duration}
        />
      );
      break;
    case 'agent_send':
      card = (
        <AgentSendCard
          params={params}
          result={parsed && !Array.isArray(parsed) ? parsed : null}
          status={status}
          error={errorMsg}
          duration={duration}
        />
      );
      break;
    case 'agent_list':
      card = <AgentListCard result={parsed} status={status} error={errorMsg} duration={duration} />;
      break;
    case 'agent_sessions':
      card = (
        <AgentSessionsCard result={parsed} status={status} error={errorMsg} duration={duration} />
      );
      break;
    case 'agent_history':
      card = (
        <AgentHistoryCard
          params={params}
          result={parsed}
          status={status}
          error={errorMsg}
          duration={duration}
        />
      );
      break;
    default:
      return null;
  }

  return card;
});

interface AgentToolCardProps {
  event: ActEvent;
  observeEvent?: ObserveEvent | undefined;
}

export const AgentToolCard = memo(function AgentToolCard({
  event,
  observeEvent,
}: AgentToolCardProps) {
  const status: 'running' | 'success' | 'error' = observeEvent
    ? observeEvent.isError
      ? 'error'
      : 'success'
    : 'running';
  const duration = observeEvent ? observeEvent.timestamp - event.timestamp : undefined;
  const errorMsg = observeEvent?.isError ? (observeEvent.toolOutput ?? undefined) : undefined;
  const parsed = observeEvent?.toolOutput ? parseResult(observeEvent.toolOutput) : null;
  const params = event.toolInput;
  const toolName = event.toolName;

  let card: React.ReactNode;

  switch (toolName) {
    case 'agent_spawn':
      card = (
        <AgentSpawnCard
          params={params}
          result={parsed && !Array.isArray(parsed) ? parsed : null}
          status={status}
          error={errorMsg}
          duration={duration}
        />
      );
      break;
    case 'agent_stop':
      card = (
        <AgentStopCard
          params={params}
          result={parsed && !Array.isArray(parsed) ? parsed : null}
          status={status}
          error={errorMsg}
          duration={duration}
        />
      );
      break;
    case 'agent_send':
      card = (
        <AgentSendCard
          params={params}
          result={parsed && !Array.isArray(parsed) ? parsed : null}
          status={status}
          error={errorMsg}
          duration={duration}
        />
      );
      break;
    case 'agent_list':
      card = <AgentListCard result={parsed} status={status} error={errorMsg} duration={duration} />;
      break;
    case 'agent_sessions':
      card = (
        <AgentSessionsCard result={parsed} status={status} error={errorMsg} duration={duration} />
      );
      break;
    case 'agent_history':
      card = (
        <AgentHistoryCard
          params={params}
          result={parsed}
          status={status}
          error={errorMsg}
          duration={duration}
        />
      );
      break;
    default:
      return null;
  }

  return (
    <div className="flex flex-col gap-1">
      <AgentSection
        icon="smart_toy"
        iconBg="bg-indigo-100 dark:bg-indigo-800/30"
        opacity={status !== 'running'}
      >
        {card}
      </AgentSection>
      <div className="pl-12">
        <TimeBadge timestamp={event.timestamp} />
      </div>
    </div>
  );
});
