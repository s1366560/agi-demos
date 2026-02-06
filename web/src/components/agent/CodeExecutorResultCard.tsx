/**
 * CodeExecutorResultCard component
 *
 * Displays results from CodeExecutorTool execution including:
 * - Execution status (success/failure)
 * - stdout/stderr output
 * - Download buttons for generated files
 */

import React, { useState } from 'react';

import {
  CodeOutlined,
  FileOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { Card, Typography, Space, Tag, Alert, Collapse } from 'antd';

import { FileDownloadButton } from './FileDownloadButton';

const { Text } = Typography;

interface OutputFile {
  filename: string;
  url: string;
  size?: number;
  content_type?: string;
}

interface CodeExecutorResult {
  success: boolean;
  stdout?: string;
  stderr?: string;
  exit_code: number;
  execution_time_ms: number;
  output_files?: OutputFile[];
  error?: string;
}

interface CodeExecutorResultCardProps {
  result: CodeExecutorResult;
}

export function parseCodeExecutorResult(resultStr: string): CodeExecutorResult | null {
  try {
    // Try to parse as JSON first
    const parsed = JSON.parse(resultStr);
    if (typeof parsed === 'object' && 'success' in parsed) {
      return parsed as CodeExecutorResult;
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
      result.exit_code = parseInt(exitMatch[1], 10);
      result.success = result.exit_code === 0;
    }

    // Extract execution time
    const timeMatch = resultStr.match(/execution_time[_ms]*[:\s]+(\d+)/i);
    if (timeMatch) {
      result.execution_time_ms = parseInt(timeMatch[1], 10);
    }

    // Extract output files (URLs)
    const urlPattern = /https?:\/\/[^\s"'<>]+/g;
    const urls = resultStr.match(urlPattern);
    if (urls && urls.length > 0) {
      result.output_files = urls.map((url, index) => {
        // Try to extract filename from URL
        const urlPath = new URL(url).pathname;
        const filename = urlPath.split('/').pop() || `file_${index + 1}`;
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
  const [showLogs, setShowLogs] = useState(false);

  const hasFiles = result.output_files && result.output_files.length > 0;
  const hasStdout = result.stdout && result.stdout.trim().length > 0;
  const hasStderr = result.stderr && result.stderr.trim().length > 0;

  return (
    <Card
      size="small"
      className="code-executor-result-card"
      style={{
        backgroundColor: result.success ? '#f6ffed' : '#fff1f0',
        border: `1px solid ${result.success ? '#b7eb8f' : '#ffccc7'}`,
        marginTop: 8,
      }}
    >
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        {/* Status Header */}
        <Space wrap>
          <CodeOutlined />
          <Text strong>Code Execution</Text>
          <Tag
            icon={result.success ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
            color={result.success ? 'success' : 'error'}
          >
            {result.success ? 'Success' : 'Failed'}
          </Tag>
          <Tag icon={<ClockCircleOutlined />} color="default">
            {result.execution_time_ms}ms
          </Tag>
          {result.exit_code !== 0 && <Tag color="warning">Exit: {result.exit_code}</Tag>}
        </Space>

        {/* Error Message */}
        {result.error && (
          <Alert type="error" message={result.error} showIcon style={{ marginTop: 8 }} />
        )}

        {/* Output Files */}
        {hasFiles && (
          <div style={{ marginTop: 8 }}>
            <Space wrap>
              <FileOutlined />
              <Text type="secondary">Generated Files:</Text>
            </Space>
            <div style={{ marginTop: 8 }}>
              {result.output_files!.map((file, index) => (
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
            onChange={(keys) => setShowLogs(keys.includes('logs'))}
            items={[
              {
                key: 'logs',
                label: (
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {showLogs ? 'Hide' : 'Show'} Execution Logs
                  </Text>
                ),
                children: (
                  <Space direction="vertical" size="small" style={{ width: '100%' }}>
                    {hasStdout && (
                      <div>
                        <Text type="secondary" style={{ fontSize: 11 }}>
                          stdout:
                        </Text>
                        <pre
                          style={{
                            backgroundColor: '#f5f5f5',
                            padding: 8,
                            borderRadius: 4,
                            fontSize: 11,
                            maxHeight: 150,
                            overflow: 'auto',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                          }}
                        >
                          {result.stdout}
                        </pre>
                      </div>
                    )}
                    {hasStderr && (
                      <div>
                        <Text type="danger" style={{ fontSize: 11 }}>
                          stderr:
                        </Text>
                        <pre
                          style={{
                            backgroundColor: '#fff1f0',
                            padding: 8,
                            borderRadius: 4,
                            fontSize: 11,
                            maxHeight: 150,
                            overflow: 'auto',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                          }}
                        >
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
