/**
 * ReportViewer component (T123)
 *
 * Displays formatted reports (markdown, tables, code) in a viewer
 * with download functionality.
 */

import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';

import { message } from 'antd';
import { Code, Copy, Download, FileText, Table } from 'lucide-react';

import { LazyCard, LazyButton, Typography } from '@/components/ui/lazyAntd';

import { safeMarkdownComponents } from './chat/markdownPlugins';

const { Text, Paragraph } = Typography;

interface ReportViewerProps {
  /** Report content */
  content: string;
  /** Report format type */
  format: 'markdown' | 'table' | 'code' | 'json' | 'yaml';
  /** Report title */
  title?: string | undefined;
  /** Filename for download */
  filename?: string | undefined;
  /** Show download button */
  showDownload?: boolean | undefined;
}

/**
 * Component for viewing and downloading formatted reports
 */
export const ReportViewer: React.FC<ReportViewerProps> = ({
  content,
  format,
  title,
  filename = 'report',
  showDownload = true,
}) => {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  const displayTitle =
    title ?? t('components.reportViewer.defaultTitle', { defaultValue: 'Report' });

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
      void message.success(
        t('components.reportViewer.copySuccess', { defaultValue: 'Copied to clipboard' })
      );
      setTimeout(() => {
        setCopied(false);
      }, 2000);
    } catch {
      void message.error(t('components.reportViewer.copyFailed', { defaultValue: 'Copy failed' }));
    }
  };

  // Get icon based on format
  const getIcon = () => {
    const icons: Record<string, React.ReactNode> = {
      markdown: <FileText size={16} />,
      table: <Table size={16} />,
      code: <Code size={16} />,
      json: <Code size={16} />,
      yaml: <Code size={16} />,
    };
    return icons[format] || <FileText size={16} />;
  };

  // Parse content for table format
  const renderContent = () => {
    switch (format) {
      case 'markdown':
      case 'table':
        return (
          <div className="markdown-report">
            <ReactMarkdown components={safeMarkdownComponents}>{content}</ReactMarkdown>
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
          <Text strong>{displayTitle}</Text>
          <Text type="secondary" style={{ fontWeight: 'normal', fontSize: 12 }}>
            ({format.toUpperCase()})
          </Text>
        </div>
      }
      extra={
        showDownload && (
          <div style={{ display: 'flex', gap: 8 }}>
            <LazyButton
              icon={<Copy size={16} />}
              size="small"
              onClick={() => {
                void handleCopy();
              }}
            >
              {copied
                ? t('components.reportViewer.copied', { defaultValue: 'Copied!' })
                : t('common.copy', { defaultValue: 'Copy' })}
            </LazyButton>
            <LazyButton
              type="primary"
              icon={<Download size={16} />}
              size="small"
              onClick={handleDownload}
            >
              {t('common.download', { defaultValue: 'Download' })}
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
