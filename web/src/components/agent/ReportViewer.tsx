/**
 * ReportViewer component (T123)
 *
 * Displays formatted reports (markdown, tables, code) in a viewer
 * with download functionality.
 */

import React, { useState } from 'react';

import ReactMarkdown from 'react-markdown';

import {
  DownloadOutlined,
  CopyOutlined,
  FileTextOutlined,
  TableOutlined,
  CodeOutlined,
} from '@ant-design/icons';

import { LazyCard, LazyButton, Typography } from '@/components/ui/lazyAntd';

const { Text, Paragraph } = Typography;

interface ReportViewerProps {
  /** Report content */
  content: string;
  /** Report format type */
  format: 'markdown' | 'table' | 'code' | 'json' | 'yaml';
  /** Report title */
  title?: string;
  /** Filename for download */
  filename?: string;
  /** Show download button */
  showDownload?: boolean;
}

/**
 * Component for viewing and downloading formatted reports
 */
export const ReportViewer: React.FC<ReportViewerProps> = ({
  content,
  format,
  title = 'Report',
  filename = 'report',
  showDownload = true,
}) => {
  const [copied, setCopied] = useState(false);

  // Get file extension based on format
  const getExtension = (): string => {
    const extensions: Record<string, string> = {
      markdown: '.md',
      table: '.md',
      code: '.txt',
      json: '.json',
      yaml: '.yaml',
    };
    return extensions[format] || '.txt';
  };

  // Get content type for download
  const getContentType = (): string => {
    const types: Record<string, string> = {
      markdown: 'text/markdown',
      table: 'text/markdown',
      code: 'text/plain',
      json: 'application/json',
      yaml: 'text/yaml',
    };
    return types[format] || 'text/plain';
  };

  // Handle download
  const handleDownload = () => {
    const blob = new Blob([content], { type: getContentType() });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${filename}${getExtension()}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // Handle copy to clipboard
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  };

  // Get icon based on format
  const getIcon = () => {
    const icons: Record<string, React.ReactNode> = {
      markdown: <FileTextOutlined />,
      table: <TableOutlined />,
      code: <CodeOutlined />,
      json: <CodeOutlined />,
      yaml: <CodeOutlined />,
    };
    return icons[format] || <FileTextOutlined />;
  };

  // Parse content for table format
  const renderContent = () => {
    switch (format) {
      case 'markdown':
      case 'table':
        return (
          <div className="markdown-report">
            <ReactMarkdown>{content}</ReactMarkdown>
          </div>
        );

      case 'json':
      case 'yaml':
      case 'code':
        return (
          <pre className="code-report">
            <code>{content}</code>
          </pre>
        );

      default:
        return <Paragraph>{content}</Paragraph>;
    }
  };

  return (
    <LazyCard
      title={
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {getIcon()}
          <Text strong>{title}</Text>
          <Text type="secondary" style={{ fontWeight: 'normal', fontSize: 12 }}>
            ({format.toUpperCase()})
          </Text>
        </div>
      }
      extra={
        showDownload && (
          <div style={{ display: 'flex', gap: 8 }}>
            <LazyButton
              icon={<CopyOutlined />}
              size="small"
              onClick={handleCopy}
            >
              {copied ? 'Copied!' : 'Copy'}
            </LazyButton>
            <LazyButton
              type="primary"
              icon={<DownloadOutlined />}
              size="small"
              onClick={handleDownload}
            >
              Download
            </LazyButton>
          </div>
        )
      }
      className="report-viewer"
    >
      {renderContent()}
    </LazyCard>
  );
};

export default ReportViewer;
