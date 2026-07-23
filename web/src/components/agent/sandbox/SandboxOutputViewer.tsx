/**
 * SandboxOutputViewer - Display tool execution output with syntax highlighting
 *
 * Shows the output from sandbox tool executions (read, write, edit, etc.)
 * with proper formatting and syntax highlighting.
 * Now supports artifact display for rich outputs (images, videos, etc.)
 */

import { useState, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { Typography, Tag, Empty, Collapse, Button, Tooltip, message } from 'antd';
import {
  Copy,
  Check,
  FileText,
  Code,
  Monitor,
  Search,
  Pencil,
  Folder,
  Image as PictureIcon,
} from 'lucide-react';

import { formatTimeOnly } from '@/utils/date';

import { ArtifactRenderer } from '../../artifact';

import type { Artifact } from '../../../types/agent';
import type { CollapseProps } from 'antd';

const { Text } = Typography;

export interface ToolExecution {
  id: string;
  toolName: string;
  input: Record<string, unknown>;
  output?: string | undefined;
  error?: string | undefined;
  durationMs?: number | undefined;
  timestamp: number;
  /** Artifacts produced by this tool execution */
  artifacts?: Artifact[] | undefined;
}

export interface SandboxOutputViewerProps {
  /** List of tool executions to display */
  executions: ToolExecution[];
  /** Maximum height (default: 100%) */
  maxHeight?: string | number | undefined;
  /** Called when user clicks on a file path */
  onFileClick?: ((filePath: string) => void) | undefined;
  /** Called when user wants to expand an artifact */
  onArtifactExpand?: ((artifact: Artifact) => void) | undefined;
}

// Tool icons mapping
const TOOL_ICONS: Record<string, React.ReactNode> = {
  read: <FileText size={14} />,
  write: <Pencil size={14} />,
  edit: <Code size={14} />,
  glob: <Folder size={14} />,
  grep: <Search size={14} />,
  bash: <Monitor size={14} />,
};

// Tool colors mapping
const TOOL_COLORS: Record<string, string> = {
  read: 'blue',
  write: 'green',
  edit: 'orange',
  glob: 'purple',
  grep: 'cyan',
  bash: 'default',
};

function stringInput(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function ToolExecutionCard({
  execution,
  onFileClick,
  onArtifactExpand,
}: {
  execution: ToolExecution;
  onFileClick?: ((filePath: string) => void) | undefined;
  onArtifactExpand?: ((artifact: Artifact) => void) | undefined;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    const content = execution.output || execution.error || '';
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      message.success(
        t('components.sandboxOutput.copySuccess', { defaultValue: 'Copied to clipboard' })
      );
      setTimeout(() => {
        setCopied(false);
      }, 2000);
    } catch {
      void message.error(t('components.sandboxOutput.copyFailed', { defaultValue: 'Copy failed' }));
    }
  };

  // Format input for display
  const formattedInput = useMemo(() => {
    const input = execution.input;
    if (execution.toolName === 'read' || execution.toolName === 'write') {
      return stringInput(input.file_path);
    }
    if (execution.toolName === 'edit') {
      const filePath = stringInput(input.file_path);
      const oldLength = stringInput(input.old_string).length;
      const newLength = stringInput(input.new_string).length;
      return t('components.sandboxOutput.editSummary', {
        defaultValue: '{{filePath}} ({{oldLength}} → {{newLength}} chars)',
        filePath,
        oldLength,
        newLength,
      });
    }
    if (execution.toolName === 'glob') {
      return stringInput(input.pattern);
    }
    if (execution.toolName === 'grep') {
      const pattern = stringInput(input.pattern);
      const path = stringInput(input.path);
      return path
        ? t('components.sandboxOutput.grepSummary', {
            defaultValue: '{{pattern}} in {{path}}',
            pattern,
            path,
          })
        : pattern;
    }
    if (execution.toolName === 'bash') {
      const cmd = stringInput(input.command);
      return cmd.length > 50 ? cmd.slice(0, 50) + '…' : cmd;
    }
    return JSON.stringify(input);
  }, [execution, t]);

  // Determine if output looks like code
  const isCodeOutput = useMemo(() => {
    const output = execution.output || '';
    return (
      execution.toolName === 'read' ||
      execution.toolName === 'bash' ||
      output.includes('\n') ||
      output.startsWith('{') ||
      output.startsWith('[')
    );
  }, [execution]);

  return (
    <div className="border border-slate-200 rounded-lg overflow-hidden bg-white">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-slate-50 border-b border-slate-200">
        <div className="flex items-center gap-2">
          <Tag
            icon={TOOL_ICONS[execution.toolName]}
            {...(TOOL_COLORS[execution.toolName] != null
              ? { color: TOOL_COLORS[execution.toolName] }
              : {})}
          >
            {execution.toolName}
          </Tag>
          {(() => {
            const filePath =
              stringInput(execution.input.file_path) || stringInput(execution.input.path);
            if (filePath && onFileClick) {
              return (
                <button
                  type="button"
                  className="text-sm text-slate-600 cursor-pointer hover:text-blue-600 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 rounded"
                  onClick={() => {
                    onFileClick(filePath);
                  }}
                >
                  {formattedInput}
                </button>
              );
            }
            return <span className="text-sm text-slate-600">{formattedInput}</span>;
          })()}
        </div>
        <div className="flex items-center gap-2">
          {execution.durationMs && (
            <Text className="text-xs text-slate-400">{execution.durationMs}ms</Text>
          )}
          <Tooltip
            title={
              copied
                ? t('components.sandboxOutput.copied', { defaultValue: 'Copied!' })
                : t('components.sandboxOutput.copyOutput', { defaultValue: 'Copy output' })
            }
          >
            <Button
              type="text"
              size="small"
              icon={copied ? <Check size={16} /> : <Copy size={16} />}
              onClick={() => {
                void handleCopy();
              }}
              className="text-slate-400 hover:text-slate-600"
              aria-label={
                copied
                  ? t('components.sandboxOutput.copied', { defaultValue: 'Copied!' })
                  : t('components.sandboxOutput.copyOutput', { defaultValue: 'Copy output' })
              }
            />
          </Tooltip>
        </div>
      </div>

      {/* Content */}
      <div className="max-h-64 overflow-auto">
        {execution.error ? (
          <div className="p-3 bg-red-50">
            <Text type="danger" className="text-sm font-mono whitespace-pre-wrap">
              {execution.error}
            </Text>
          </div>
        ) : execution.output ? (
          <div className={`p-3 ${isCodeOutput ? 'bg-slate-900' : 'bg-white'}`}>
            <pre
              className={`text-sm font-mono whitespace-pre-wrap m-0 ${
                isCodeOutput ? 'text-slate-200' : 'text-slate-700'
              }`}
            >
              {execution.output}
            </pre>
          </div>
        ) : (
          <div className="p-3 text-center">
            <Text type="secondary" className="text-sm">
              {t('components.sandboxOutput.noOutput', { defaultValue: 'No output' })}
            </Text>
          </div>
        )}
      </div>

      {/* Artifacts section */}
      {execution.artifacts && execution.artifacts.length > 0 && (
        <div className="border-t border-slate-200">
          <div className="px-3 py-2 bg-slate-50 flex items-center gap-2">
            <PictureIcon size={16} className="text-blue-500" />
            <Text className="text-xs text-slate-600">
              {t('components.sandboxOutput.artifactCount', {
                defaultValue:
                  execution.artifacts.length === 1 ? '{{count}} artifact' : '{{count}} artifacts',
                count: execution.artifacts.length,
              })}
            </Text>
          </div>
          <div
            className="p-3 grid gap-2"
            style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))' }}
          >
            {execution.artifacts.map((artifact) => (
              <ArtifactRenderer
                key={artifact.id}
                artifact={artifact}
                compact
                maxHeight={120}
                onExpand={onArtifactExpand}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function SandboxOutputViewer({
  executions,
  maxHeight = '100%',
  onFileClick,
  onArtifactExpand,
}: SandboxOutputViewerProps) {
  const { t } = useTranslation();

  if (executions.length === 0) {
    return (
      <div className="flex items-center justify-center h-full" style={{ maxHeight }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t('components.sandboxOutput.empty', {
            defaultValue: 'No tool executions yet',
          })}
        />
      </div>
    );
  }

  // Group executions for collapse view if many
  const useCollapse = executions.length > 3;

  if (useCollapse) {
    const items: CollapseProps['items'] = executions.map((exec, _index) => ({
      key: exec.id,
      label: (
        <div className="flex items-center gap-2">
          <Tag
            icon={TOOL_ICONS[exec.toolName]}
            {...(TOOL_COLORS[exec.toolName] != null ? { color: TOOL_COLORS[exec.toolName] } : {})}
            className="m-0"
          >
            {exec.toolName}
          </Tag>
          <Text className="text-sm text-slate-600">{formatTimeOnly(exec.timestamp)}</Text>
          {exec.error && (
            <Tag color="error">
              {t('components.sandboxOutput.error', { defaultValue: 'Error' })}
            </Tag>
          )}
          {exec.artifacts && exec.artifacts.length > 0 && (
            <Tag icon={<PictureIcon size={14} />} color="blue">
              {exec.artifacts.length}
            </Tag>
          )}
        </div>
      ),
      children: (
        <ToolExecutionCard
          execution={exec}
          onFileClick={onFileClick}
          onArtifactExpand={onArtifactExpand}
        />
      ),
    }));

    return (
      <div className="h-full overflow-auto p-2" style={{ maxHeight }}>
        <Collapse
          items={items}
          defaultActiveKey={[executions[executions.length - 1]?.id ?? '']}
          size="small"
        />
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-2 space-y-2" style={{ maxHeight }}>
      {executions.map((exec) => (
        <ToolExecutionCard
          key={exec.id}
          execution={exec}
          onFileClick={onFileClick}
          onArtifactExpand={onArtifactExpand}
        />
      ))}
    </div>
  );
}

export default SandboxOutputViewer;
