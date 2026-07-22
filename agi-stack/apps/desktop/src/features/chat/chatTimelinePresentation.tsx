import type { ReactNode } from 'react';
import {
  ActivityLogIcon,
  ArchiveIcon,
  ChatBubbleIcon,
  CodeIcon,
  DotsHorizontalIcon,
} from '@radix-ui/react-icons';

import { useI18n } from '../../i18n';
import type {
  AgentTimelineItem,
  HitlType,
  ToolDisplayData,
  ToolFileMetadata,
} from '../../types';
import { agentLifecyclePresentation } from './agentLifecyclePresentationModel';

export type TimelineKind = 'user' | 'agent' | 'runtime' | 'tool' | 'artifact';

export type TimelineStatus = {
  kind: 'ok' | 'error' | 'waiting';
  label: string;
  localized: boolean;
};

export function timelineHitlType(item: AgentTimelineItem): HitlType | null {
  if (item.type === 'clarification_asked') return 'clarification';
  if (item.type === 'decision_asked') return 'decision';
  if (item.type === 'env_var_requested') return 'env_var';
  if (item.type === 'permission_asked' || item.type === 'permission_requested') {
    return 'permission';
  }
  if (item.type === 'a2ui_action_asked') return 'a2ui_action';
  return null;
}

export function timelineHitlRequestId(item: AgentTimelineItem): string {
  if (item.requestId) return item.requestId;
  const direct = item.request_id;
  if (typeof direct === 'string') return direct;
  return stringPayloadField(item, 'request_id') ?? '';
}

export function timelineHitlQuestion(
  item: AgentTimelineItem,
  t: (key: string) => string,
): string {
  if (item.question) return item.question;
  return (
    stringPayloadField(item, 'question') ??
    stringPayloadField(item, 'message') ??
    item.reason ??
    stringPayloadField(item, 'reason') ??
    item.description ??
    stringPayloadField(item, 'description') ??
    t('chat.agentWaitingForInput')
  );
}

export function timelineHitlOptions(
  item: AgentTimelineItem,
): Array<{ value: string; label: string; description?: string }> {
  const payload = isRecord(item.payload) ? item.payload : {};
  const source = Array.isArray(item.options)
    ? item.options
    : Array.isArray(payload.options)
      ? payload.options
      : [];
  return source.flatMap((option) => {
    if (typeof option === 'string') return [{ value: option, label: option }];
    if (!isRecord(option)) return [];
    const value = firstString(option, ['id', 'value', 'option_id', 'label']);
    if (!value) return [];
    return [
      {
        value,
        label: firstString(option, ['label', 'title', 'name']) ?? value,
        description: firstString(option, ['description', 'detail']) ?? undefined,
      },
    ];
  });
}

export function timelineHitlFields(
  item: AgentTimelineItem,
): Array<{ name: string; label: string; required: boolean }> {
  const payload = isRecord(item.payload) ? item.payload : {};
  const source = Array.isArray(item.fields)
    ? item.fields
    : Array.isArray(payload.fields)
      ? payload.fields
      : [];
  return source.flatMap((field) => {
    if (typeof field === 'string') return [{ name: field, label: field, required: true }];
    if (!isRecord(field)) return [];
    const name = firstString(field, ['name', 'key', 'variable']);
    if (!name) return [];
    return [
      {
        name,
        label: firstString(field, ['label', 'description']) ?? name,
        required: field.required !== false,
      },
    ];
  });
}

export function booleanPayloadField(item: AgentTimelineItem, key: string): boolean | null {
  if (!isRecord(item.payload)) return null;
  const value = item.payload[key];
  return typeof value === 'boolean' ? value : null;
}

export function timelineKind(item: AgentTimelineItem): TimelineKind {
  if (item.role === 'user' || item.type === 'user_message') return 'user';
  if (item.role === 'assistant' || item.type === 'assistant_message') return 'agent';
  if (item.type === 'act' || item.type === 'observe') return 'tool';
  if (item.type.startsWith('artifact_') || item.type === 'artifacts_batch') return 'artifact';
  return 'runtime';
}

export function timelineToolDisplay(item: AgentTimelineItem): ToolDisplayData | null {
  if (isRecord(item.display)) return item.display as ToolDisplayData;
  const output = isRecord(item.toolOutput) ? item.toolOutput : null;
  const display = output?.display;
  return isRecord(display) ? (display as ToolDisplayData) : null;
}

export function timelineFileMetadata(item: AgentTimelineItem): ToolFileMetadata | null {
  if (isRecord(item.fileMetadata)) return item.fileMetadata as ToolFileMetadata;
  const output = isRecord(item.toolOutput) ? item.toolOutput : null;
  const metadata = output?.fileMetadata ?? output?.file_metadata;
  return isRecord(metadata) ? (metadata as ToolFileMetadata) : null;
}

export function timelineTitle(item: AgentTimelineItem, t: (key: string) => string): string {
  if (item.role === 'user' || item.type === 'user_message') return t('chat.you');
  if (item.role === 'assistant' || item.type === 'assistant_message') return t('chat.agent');
  const display = timelineToolDisplay(item);
  if (display?.title) return display.title;
  if (item.type === 'thought') return t('chat.thought');
  if (item.type === 'act') return t('chat.toolCall');
  if (item.type === 'observe') return t('chat.toolResult');
  if (item.type === 'work_plan') return t('chat.workPlan');
  if (item.type === 'task_start') return t('chat.taskStarted');
  if (item.type === 'task_complete') return t('chat.taskCompleted');
  if (item.type.startsWith('task_')) return t('chat.task');
  if (item.type === 'artifact_created') return t('chat.artifactCreated');
  if (item.type === 'artifact_ready') return t('chat.artifactReady');
  if (item.type === 'artifact_error') return t('chat.artifactFailed');
  if (item.type === 'artifacts_batch') return t('chat.artifactsBatch');
  if (item.type.startsWith('artifact_')) return t('chat.artifact');
  if (timelineHitlType(item)) return t('chat.humanInput');
  const lifecycle = agentLifecyclePresentation(item);
  if (lifecycle?.family === 'subagent') return t('chat.subagent');
  if (lifecycle?.family === 'agent') return t('chat.agentEvent');
  if (lifecycle?.family === 'agentMessage') return t('chat.agentMessage');
  if (lifecycle?.family === 'parallel') return t('chat.parallel');
  if (lifecycle?.family === 'chain' || lifecycle?.family === 'chainStep') {
    return t('chat.chain');
  }
  if (lifecycle?.family === 'background') return t('chat.background');
  if (lifecycle?.family === 'retry') return t('chat.retrying');
  if (lifecycle?.family === 'routing') return t('chat.routingDecision');
  if (lifecycle?.family === 'selection') return t('chat.toolSelection');
  if (lifecycle?.family === 'policy') return t('chat.toolPolicy');
  if (lifecycle?.family === 'toolset') return t('chat.toolsetChange');
  if (lifecycle?.family === 'doomLoop') {
    return item.type === 'doom_loop_detected'
      ? t('chat.doomLoopDetected')
      : t('chat.doomLoopIntervened');
  }
  if (lifecycle?.family === 'conversation') {
    return item.type === 'agent_goal_completed'
      ? t('chat.agentGoalCompleted')
      : t('chat.agentConversationFinished');
  }
  if (lifecycle?.family === 'planReflection') return t('chat.plan');
  if (lifecycle?.family === 'sessionLifecycle') {
    return item.type === 'session_forked' ? t('chat.sessionForked') : t('chat.sessionMerged');
  }
  if (lifecycle?.family === 'participant') {
    return item.type === 'conversation_participant_joined'
      ? t('chat.participantJoined')
      : t('chat.participantLeft');
  }
  if (lifecycle?.family === 'agentTask') {
    if (item.type === 'agent_task_assigned') return t('chat.agentTaskAssigned');
    if (item.type === 'agent_task_refused') return t('chat.agentTaskRefused');
    return t('chat.agentProgressDeclared');
  }
  if (lifecycle?.family === 'agentGovernance') {
    if (item.type === 'agent_human_input_requested') {
      return t('chat.agentHumanInputRequested');
    }
    if (item.type === 'agent_escalated') return t('chat.agentEscalated');
    return t('chat.agentConflictMarked');
  }
  if (lifecycle?.family === 'agentAudit') {
    return item.type === 'agent_supervisor_verdict'
      ? t('chat.agentSupervisorVerdict')
      : t('chat.agentDecisionLogged');
  }
  if (lifecycle?.family === 'workspaceOrchestration') {
    if (item.type === 'workspace_goal_materialized') {
      return t('chat.workspaceGoalMaterialized');
    }
    if (item.type === 'workspace_decomposition_complete') {
      return t('chat.workspaceDecompositionComplete');
    }
    if (item.type === 'workspace_worker_dispatched') {
      return t('chat.workspaceWorkerDispatched');
    }
    if (item.type === 'workspace_worker_report_submitted') {
      return t('chat.workspaceWorkerReportSubmitted');
    }
    if (item.type === 'workspace_adjudication_complete') {
      return t('chat.workspaceAdjudicationComplete');
    }
    return t('chat.workspaceGoalCompleted');
  }
  if (lifecycle?.family === 'agentDefinition') {
    if (item.type === 'agent_definition_created') return t('chat.agentDefinitionCreated');
    if (item.type === 'agent_definition_updated') return t('chat.agentDefinitionUpdated');
    return t('chat.agentDefinitionDeleted');
  }
  if (lifecycle?.family === 'skill') {
    if (item.type === 'skill_matched') return t('chat.skillMatched');
    if (item.type === 'skill_tool_start' || item.type === 'skill_tool_result') {
      return t('chat.skillTool');
    }
    if (item.type === 'skill_fallback') return t('chat.skillFallback');
    return t('chat.skillExecution');
  }
  if (lifecycle?.family === 'model') {
    return item.type === 'model_override_rejected'
      ? t('chat.modelOverride')
      : t('chat.modelSwitch');
  }
  if (lifecycle?.family === 'context') {
    return item.type === 'context_compressed' || item.type === 'context_compacted'
      ? t('chat.contextCompressed')
      : t('chat.contextStatus');
  }
  if (lifecycle?.family === 'mcpApp') {
    return item.type === 'mcp_app_registered'
      ? t('chat.mcpAppRegistered')
      : t('chat.mcpAppResult');
  }
  if (lifecycle?.family === 'memory') {
    return item.type === 'memory_recalled'
      ? t('chat.memoryRecalled')
      : t('chat.memoryCaptured');
  }
  if (lifecycle?.family === 'sandbox') return t('chat.sandboxEvent');
  if (lifecycle?.family === 'desktop') return t('chat.desktopEvent');
  if (lifecycle?.family === 'terminal') return t('chat.terminalEvent');
  if (lifecycle?.family === 'httpService') return t('chat.httpServiceEvent');
  if (lifecycle?.family === 'graphRun') return t('chat.graphRun');
  if (lifecycle?.family === 'graphNode') return t('chat.graphNode');
  if (lifecycle?.family === 'graphHandoff') return t('chat.graphHandoff');
  if (item.type.startsWith('subagent_')) return t('chat.subagent');
  if (item.type.startsWith('chain_')) return t('chat.chain');
  if (item.type.startsWith('agent_')) return t('chat.agentEvent');
  return t('chat.event');
}

export function timelineIcon(kind: TimelineKind, item: AgentTimelineItem): ReactNode {
  if (item.isError || item.error) return <DotsHorizontalIcon />;
  if (kind === 'tool') return <CodeIcon />;
  if (kind === 'artifact') return <ArchiveIcon />;
  if (item.type === 'thought') return <ChatBubbleIcon />;
  if (item.type === 'work_plan') return <ActivityLogIcon />;
  return <DotsHorizontalIcon />;
}

export function isImportantTimelineItem(item: AgentTimelineItem): boolean {
  const kind = timelineKind(item);
  if (kind === 'user' || kind === 'agent') return true;
  if (timelineHitlType(item)) return true;
  if (item.type === 'work_plan') return true;
  if (item.type === 'doom_loop_detected') return true;
  if (item.type === 'agent_goal_completed' || item.type === 'agent_conversation_finished') {
    return true;
  }
  if (item.type.startsWith('agent_definition_')) return true;
  return false;
}

export function isTimelineItemInitiallyExpanded(item: AgentTimelineItem): boolean {
  if (!isImportantTimelineItem(item)) return false;
  return (
    item.type !== 'doom_loop_detected' &&
    item.type !== 'agent_goal_completed' &&
    item.type !== 'agent_conversation_finished' &&
    !item.type.startsWith('agent_definition_')
  );
}

export function timelineHasDetails(item: AgentTimelineItem, kind: TimelineKind): boolean {
  if (kind === 'user' || kind === 'agent') return false;
  if (timelineToolDisplay(item) || timelineFileMetadata(item)) return true;
  if (timelineHitlType(item) || item.question || item.error || item.content) return true;
  if (item.toolInput !== undefined || item.toolOutput !== undefined) return true;
  if (item.payload !== undefined) return true;
  if (item.filename || item.artifactId) return true;
  return false;
}

export function timelineSummary(
  item: AgentTimelineItem,
  kind: TimelineKind,
  t: (key: string, values?: Record<string, string | number>) => string,
): string {
  const lifecycle = agentLifecyclePresentation(item);
  if (lifecycle) {
    const progress = lifecycle.progress
      ? lifecycle.progress.current === undefined
        ? t(`chat.${lifecycle.progress.unit}Count`, { count: lifecycle.progress.total })
        : t(`chat.${lifecycle.progress.unit}Progress`, {
            current: lifecycle.progress.current,
            total: lifecycle.progress.total,
          })
      : '';
    return compactTimelineValue(
      [lifecycle.subject, progress, lifecycle.detail].filter(Boolean).join(' · '),
    ) || item.type;
  }
  if (item.error) return item.error;
  if (timelineHitlType(item)) return timelineHitlQuestion(item, t);
  if (kind === 'artifact') return item.filename || item.artifactId || item.type;
  if (kind === 'tool') {
    const display = timelineToolDisplay(item);
    if (display?.summary) return display.summary;
    const fileSummary = timelineFileMetadataSummary(timelineFileMetadata(item), t);
    if (fileSummary) {
      return item.toolName ? `${item.toolName} ${fileSummary}` : fileSummary;
    }
    const source = item.toolOutput ?? item.toolInput ?? item.payload ?? item.content;
    const summary = compactTimelineValue(source);
    return item.toolName ? `${item.toolName}${summary ? ` ${summary}` : ''}` : summary || item.type;
  }
  if (item.content) return compactTimelineValue(item.content);
  if (item.payload !== undefined) return compactTimelineValue(item.payload);
  return item.type;
}

export function timelineStatus(item: AgentTimelineItem): TimelineStatus | null {
  const lifecycle = agentLifecyclePresentation(item);
  if (lifecycle) {
    if (lifecycle.isError) {
      return { kind: 'error', label: 'chat.status.error', localized: true };
    }
    if (lifecycle.state === 'complete') {
      return { kind: 'ok', label: 'chat.status.result', localized: true };
    }
    if (lifecycle.state === 'attention') {
      return { kind: 'waiting', label: 'chat.status.needsAttention', localized: true };
    }
    if (lifecycle.state === 'sent') {
      return { kind: 'ok', label: 'chat.status.sent', localized: true };
    }
    if (lifecycle.state === 'received') {
      return { kind: 'ok', label: 'chat.status.received', localized: true };
    }
    if (lifecycle.state === 'blocked') {
      return { kind: 'waiting', label: 'chat.status.blocked', localized: true };
    }
    if (lifecycle.state === 'scheduled') {
      return { kind: 'waiting', label: 'chat.status.scheduled', localized: true };
    }
    if (lifecycle.state === 'ready') {
      return { kind: 'ok', label: 'chat.status.ready', localized: true };
    }
    if (lifecycle.state === 'stopped') {
      return { kind: 'waiting', label: 'chat.status.stopped', localized: true };
    }
    return {
      kind: 'waiting',
      label: lifecycle.state === 'waiting' ? 'chat.status.waiting' : 'chat.status.running',
      localized: true,
    };
  }
  if (item.isError || item.error) {
    return { kind: 'error', label: 'chat.status.error', localized: true };
  }
  const displayStatus = timelineToolDisplay(item)?.status;
  if (displayStatus) {
    return {
      kind: item.type === 'act' ? 'waiting' : 'ok',
      label: displayStatus,
      localized: false,
    };
  }
  if (timelineHitlType(item)) {
    return item.answered
      ? { kind: 'ok', label: 'chat.status.answered', localized: true }
      : { kind: 'waiting', label: 'chat.status.waiting', localized: true };
  }
  if (item.type === 'act') {
    return { kind: 'waiting', label: 'chat.status.call', localized: true };
  }
  if (item.type === 'observe') {
    return { kind: 'ok', label: 'chat.status.result', localized: true };
  }
  if (item.type === 'artifact_ready') {
    return { kind: 'ok', label: 'chat.status.ready', localized: true };
  }
  return null;
}

export function timelineDetailLineCount(item: AgentTimelineItem, kind: TimelineKind): number {
  const display = timelineToolDisplay(item);
  const fileMetadata = timelineFileMetadata(item);
  const values: string[] = [];
  if (item.content) values.push(item.content);
  if (display?.summary) values.push(display.summary);
  if (fileMetadata) values.push(formatTimelineValue(fileMetadata));
  if (item.toolInput !== undefined) values.push(formatTimelineValue(item.toolInput));
  if (item.toolOutput !== undefined) values.push(formatTimelineValue(item.toolOutput));
  if (item.payload !== undefined) values.push(formatTimelineValue(item.payload));
  if (item.question) values.push(item.question);
  if (item.error) values.push(item.error);
  if (kind === 'artifact') values.push(item.filename || item.artifactId || '');
  // Count non-empty lines across the values directly: the previous
  // join('\n').split('\n') copied every payload into one big string and then
  // allocated a substring per line — significant on a cold load of ~150
  // tool-heavy items whose outputs run to tens of KB.
  let count = 0;
  for (const value of values) count += countNonEmptyLines(value);
  return count;
}

const WHITESPACE_CHAR = /\s/;

/** Number of lines containing at least one non-whitespace character. */
function countNonEmptyLines(text: string): number {
  let count = 0;
  let hasContent = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch === '\n') {
      if (hasContent) count += 1;
      hasContent = false;
    } else if (!WHITESPACE_CHAR.test(ch)) {
      hasContent = true;
    }
  }
  if (hasContent) count += 1;
  return count;
}

// Shared formatter: constructing an Intl.DateTimeFormat per call (what
// toLocaleTimeString with options does internally) costs far more than
// formatting — and this runs for every visible timeline row on every
// streaming chunk. Same locale/options => identical output.
const TIMELINE_TIME_FORMAT = new Intl.DateTimeFormat([], {
  hour: '2-digit',
  minute: '2-digit',
});

export function formatTimelineTime(item: AgentTimelineItem): string {
  const value =
    typeof item.timestamp === 'number'
      ? item.timestamp
      : typeof item.eventTimeUs === 'number'
        ? Math.floor(item.eventTimeUs / 1000)
        : null;
  if (!value) return '';
  return TIMELINE_TIME_FORMAT.format(new Date(value));
}

export function timelinePayloadPreview(item: AgentTimelineItem): string {
  if (item.payload === undefined || item.payload === null) return item.type;
  return formatTimelineValue(item.payload);
}

export function formatTimelineValue(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function ToolFileMetadataView({ metadata }: { metadata: ToolFileMetadata }) {
  const { t } = useI18n();
  const paths = Array.isArray(metadata.paths) ? metadata.paths : [];
  const matches = Array.isArray(metadata.matches) ? metadata.matches : [];
  return (
    <div className="tool-file-metadata">
      <div className="tool-file-metadata-head">
        <span>{metadata.operation || t('chat.file')}</span>
        {typeof metadata.matchCount === 'number' ? (
          <em>{t('chat.matchCount', { count: metadata.matchCount })}</em>
        ) : null}
        {metadata.truncated ? <em>{t('chat.truncated')}</em> : null}
      </div>
      {metadata.diffStat ? (
        <div className="tool-file-diffstat">
          <span>{t('chat.fileCount', { count: metadata.diffStat.filesChanged ?? 0 })}</span>
          <span>+{metadata.diffStat.additions ?? 0}</span>
          <span>-{metadata.diffStat.deletions ?? 0}</span>
        </div>
      ) : null}
      {paths.length ? (
        <div className="tool-file-list">
          {paths.slice(0, 8).map((path, index) => (
            <div className="tool-file-row" key={`${path.path ?? path.relativePath ?? index}`}>
              <CodeIcon />
              <span>{path.relativePath || path.path || t('chat.file')}</span>
              <em>{filePathMetaLabel(path, t)}</em>
            </div>
          ))}
        </div>
      ) : null}
      {matches.length ? (
        <div className="tool-file-matches">
          {matches.slice(0, 6).map((match, index) => (
            <div
              className="tool-match-row"
              key={`${match.path ?? 'match'}:${match.lineNumber ?? index}`}
            >
              <span>
                {match.path}
                {typeof match.lineNumber === 'number' ? `:${match.lineNumber}` : ''}
              </span>
              {match.preview ? <em>{match.preview}</em> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function stringPayloadField(item: AgentTimelineItem, key: string): string | null {
  if (!isRecord(item.payload)) return null;
  const value = item.payload[key];
  return typeof value === 'string' && value ? value : null;
}

function firstString(record: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value) return value;
  }
  return null;
}

function timelineFileMetadataSummary(
  metadata: ToolFileMetadata | null,
  t: (key: string, values?: Record<string, string | number>) => string,
): string {
  if (!metadata) return '';
  const paths = Array.isArray(metadata.paths) ? metadata.paths : [];
  const pathLabel =
    paths.length === 1
      ? paths[0].relativePath || paths[0].path
      : paths.length > 1
        ? t('chat.fileCount', { count: paths.length })
        : '';
  const matchLabel =
    typeof metadata.matchCount === 'number'
      ? t('chat.matchCount', { count: metadata.matchCount })
      : '';
  const truncated = metadata.truncated ? t('chat.truncated') : '';
  return [metadata.operation, pathLabel, matchLabel, truncated].filter(Boolean).join(' · ');
}

function filePathMetaLabel(
  path: NonNullable<ToolFileMetadata['paths']>[number],
  t: (key: string, values?: Record<string, string | number>) => string,
): string {
  const parts: string[] = [];
  if (typeof path.lineStart === 'number' && typeof path.lineEnd === 'number') {
    parts.push(
      path.lineStart === path.lineEnd ? `L${path.lineStart}` : `L${path.lineStart}-${path.lineEnd}`,
    );
  } else if (typeof path.lineCount === 'number') {
    parts.push(t('chat.lineCount', { count: path.lineCount }));
  }
  if (typeof path.bytesWritten === 'number') {
    parts.push(t('chat.bytesWritten', { count: path.bytesWritten }));
  }
  if (typeof path.bytesRead === 'number') {
    parts.push(t('chat.bytesRead', { count: path.bytesRead }));
  }
  if (path.created) parts.push(t('chat.created'));
  if (path.changed) parts.push(t('chat.changed'));
  if (path.deleted) parts.push(t('chat.deleted'));
  return parts.join(' · ');
}

function compactTimelineValue(value: unknown, maxLength = 180): string {
  if (value === undefined || value === null) return '';
  const rendered = typeof value === 'string' ? value : formatTimelineValue(value);
  const compacted = rendered.replace(/\s+/g, ' ').trim();
  if (compacted.length <= maxLength) return compacted;
  return `${compacted.slice(0, maxLength - 1)}…`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
