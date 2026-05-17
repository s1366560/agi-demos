/**
 * CodeExecutorResultCard component
 *
 * Displays results from CodeExecutorTool execution including:
 * - Execution status (success/failure)
 * - stdout/stderr output
 * - Download buttons for generated files
 */

import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Alert, Card, Collapse, Space, Tag, Typography } from 'antd';
import { CheckCircle2, Clock, Code, File, XCircle } from 'lucide-react';

import { FileDownloadButton } from './FileDownloadButton';

const { Text } = Typography;

interface OutputFile {
  filename: string;
  url: string;
  size?: number | undefined;
  content_type?: string | undefined;
}

interface CodeExecutorResult {
  success: boolean;
  stdout?: string | undefined;
  stderr?: string | undefined;
  exit_code: number;
  execution_time_ms: number;
  output_files?: OutputFile[] | undefined;
  error?: string | undefined;
}

interface CodeExecutorResultCardProps {
  result: CodeExecutorResult;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const isCodeExecutorResult = (value: unknown): value is CodeExecutorResult => {
  if (!isRecord(value)) return false;
  return (
    typeof value.success === 'boolean' &&
    typeof value.exit_code === 'number' &&
    typeof value.execution_time_ms === 'number'
  );
};

// eslint-disable-next-line react-refresh/only-export-components
export function parseCodeExecutorResult(resultStr: string): CodeExecutorResult | null {
  try {
    // Try to parse as JSON first
    const parsed: unknown = JSON.parse(resultStr);
    if (isCodeExecutorResult(parsed)) {
      return parsed;
    }
    return null;
  } catch {
    // Not JSON, might be a formatted string
    // Try to extract structured data from formatted output
    const result: Partial<CodeExecutorResult> = {
      success: false,
      exit_code: -1,
      execution_time_ms: 0,
    };

    // Check for success indicators
    if (resultStr.includes('success: true') || resultStr.includes('Success: true')) {
      result.success = true;
    }

    // Extract exit code
    const exitMatch = resultStr.match(/exit_code[:\s]+(\d+)/i);
    if (exitMatch) {
      result.exit_code = parseInt(exitMatch[1] ?? '0', 10);
      result.success = result.exit_code === 0;
    }

    // Extract execution time
    const timeMatch = resultStr.match(/execution_time[_ms]*[:\s]+(\d+)/i);
    if (timeMatch) {
      result.execution_time_ms = parseInt(timeMatch[1] ?? '0', 10);
    }

    // Extract output files (URLs)
    const urlPattern = /https?:\/\/[^\s"'<>]+/g;
    const urls = resultStr.match(urlPattern);
    if (urls && urls.length > 0) {
      result.output_files = urls.map((url, index) => {
        // Try to extract filename from URL
        const urlPath = new URL(url).pathname;
        const filename = urlPath.split('/').pop() || `file_${(index + 1).toString()}`;
        return { filename, url };
      });
    }

    // Check if we have meaningful data
    if (result.output_files && result.output_files.length > 0) {
      result.success = true;
      return result as CodeExecutorResult;
    }

    return null;
  }
}

export const CodeExecutorResultCard: React.FC<CodeExecutorResultCardProps> = ({ result }) => {
  const { t } = useTranslation();
  const [showLogs, setShowLogs] = useState(false);

  const outputFiles = result.output_files ?? [];
  const hasFiles = outputFiles.length > 0;
  const hasStdout = result.stdout && result.stdout.trim().length > 0;
  const hasStderr = result.stderr && result.stderr.trim().length > 0;

  return (
    <Card
      size="small"
      className={`code-executor-result-card ${
        result.success
          ? 'border-green-200 bg-green-50 dark:border-green-800/60 dark:bg-green-950/30'
          : 'border-red-200 bg-red-50 dark:border-red-800/60 dark:bg-red-950/30'
      }`}
      style={{
        marginTop: 8,
      }}
    >
      <Space orientation="vertical" size="small" style={{ width: '100%' }}>
        {/* Status Header */}
        <Space wrap>
          <Code size={16} />
          <Text strong>
            {t('components.codeExecutorResult.title', { defaultValue: 'Code Execution' })}
          </Text>
          <Tag
            icon={result.success ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
            color={result.success ? 'success' : 'error'}
          >
            {result.success
              ? t('components.codeExecutorResult.status.success', { defaultValue: 'Success' })
              : t('components.codeExecutorResult.status.failed', { defaultValue: 'Failed' })}
          </Tag>
          <Tag icon={<Clock size={16} />} color="default">
            {result.execution_time_ms}ms
          </Tag>
          {result.exit_code !== 0 && (
            <Tag color="warning">
              {t('components.codeExecutorResult.exitCode', {
                defaultValue: 'Exit: {{exitCode}}',
                exitCode: result.exit_code,
              })}
            </Tag>
          )}
        </Space>

        {/* Error Message */}
        {result.error && (
          <Alert type="error" title={result.error} showIcon style={{ marginTop: 8 }} />
        )}

        {/* Output Files */}
        {hasFiles && (
          <div style={{ marginTop: 8 }}>
            <Space wrap>
              <File size={16} />
              <Text type="secondary">
                {t('components.codeExecutorResult.generatedFiles', {
                  defaultValue: 'Generated Files:',
                })}
              </Text>
            </Space>
            <div style={{ marginTop: 8 }}>
              {outputFiles.map((file, index) => (
                <FileDownloadButton
                  key={index}
                  filename={file.filename}
                  url={file.url}
                  size={file.size}
                />
              ))}
            </div>
          </div>
        )}

        {/* Logs (collapsible) */}
        {(hasStdout || hasStderr) && (
          <Collapse
            ghost
            size="small"
            activeKey={showLogs ? ['logs'] : []}
            onChange={(keys) => {
              setShowLogs(keys.includes('logs'));
            }}
            items={[
              {
                key: 'logs',
                label: (
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {showLogs
                      ? t('components.codeExecutorResult.logs.hide', {
                          defaultValue: 'Hide Execution Logs',
                        })
                      : t('components.codeExecutorResult.logs.show', {
                          defaultValue: 'Show Execution Logs',
                        })}
                  </Text>
                ),
                children: (
                  <Space orientation="vertical" size="small" style={{ width: '100%' }}>
                    {hasStdout && (
                      <div>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          {t('components.codeExecutorResult.logs.stdout', {
                            defaultValue: 'stdout:',
                          })}
                        </Text>
                        <pre className="max-h-[150px] overflow-auto whitespace-pre-wrap break-words rounded bg-slate-100 p-2 text-[11px] text-slate-800 dark:bg-slate-900 dark:text-slate-200">
                          {result.stdout}
                        </pre>
                      </div>
                    )}
                    {hasStderr && (
                      <div>
                        <Text type="danger" style={{ fontSize: 11 }}>
                          {t('components.codeExecutorResult.logs.stderr', {
                            defaultValue: 'stderr:',
                          })}
                        </Text>
                        <pre className="max-h-[150px] overflow-auto whitespace-pre-wrap break-words rounded bg-red-50 p-2 text-[11px] text-red-900 dark:bg-red-950/40 dark:text-red-200">
                          {result.stderr}
                        </pre>
                      </div>
                    )}
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Space>
    </Card>
  );
};

export default CodeExecutorResultCard;
