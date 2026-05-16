/**
 * CodeViewer - Display code/data files with syntax highlighting
 */

import React, { useState, useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { Typography, Spin, Alert, Button, Tooltip, message } from 'antd';
import { Copy, Check } from 'lucide-react';

const { Text } = Typography;

export interface CodeViewerProps {
  /** URL to fetch content from */
  url: string;
  /** Filename for language detection */
  filename: string;
  /** MIME type for format hint */
  mimeType?: string | undefined;
  /** Maximum height */
  maxHeight?: number | string | undefined;
  /** Compact mode */
  compact?: boolean | undefined;
  /** Called when content loads */
  onLoad?: (() => void) | undefined;
  /** Called on error */
  onError?: ((error: string) => void) | undefined;
}

// Detect language from filename
function detectLanguage(filename: string, _mimeType?: string): string {
  const ext = filename.split('.').pop()?.toLowerCase();

  const extMap: Record<string, string> = {
    js: 'javascript',
    mjs: 'javascript',
    ts: 'typescript',
    tsx: 'typescript',
    jsx: 'javascript',
    py: 'python',
    rb: 'ruby',
    java: 'java',
    go: 'go',
    rs: 'rust',
    c: 'c',
    cpp: 'cpp',
    h: 'c',
    hpp: 'cpp',
    cs: 'csharp',
    php: 'php',
    sh: 'bash',
    bash: 'bash',
    zsh: 'bash',
    json: 'json',
    yaml: 'yaml',
    yml: 'yaml',
    xml: 'xml',
    html: 'html',
    htm: 'html',
    css: 'css',
    scss: 'scss',
    less: 'less',
    md: 'markdown',
    sql: 'sql',
    csv: 'plaintext',
    txt: 'plaintext',
  };

  return ext ? extMap[ext] || 'plaintext' : 'plaintext';
}

// Format JSON with pretty printing
function formatContent(content: string, mimeType?: string, filename?: string): string {
  // Try to format JSON
  if (mimeType?.includes('json') || filename?.endsWith('.json')) {
    try {
      const parsed: unknown = JSON.parse(content);
      return JSON.stringify(parsed, null, 2);
    } catch {
      // Not valid JSON, return as-is
    }
  }

  return content;
}

export const CodeViewer: React.FC<CodeViewerProps> = ({
  url,
  filename,
  mimeType,
  maxHeight = 400,
  compact = false,
  onLoad,
  onError,
}) => {
  const { t } = useTranslation();
  const [content, setContent] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const language = detectLanguage(filename, mimeType);

  useEffect(() => {
    let cancelled = false;

    const fetchContent = async () => {
      try {
        setLoading(true);
        setError(null);

        const response = await fetch(url);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status.toString()}: ${response.statusText}`);
        }

        const text = await response.text();
        if (!cancelled) {
          setContent(formatContent(text, mimeType, filename));
          setLoading(false);
          onLoad?.();
        }
      } catch (err) {
        if (!cancelled) {
          const errMsg =
            err instanceof Error
              ? err.message
              : t('components.codeViewer.loadFailed', {
                  defaultValue: 'Failed to load content',
                });
          setError(errMsg);
          setLoading(false);
          onError?.(errMsg);
        }
      }
    };

    void fetchContent();

    return () => {
      cancelled = true;
    };
  }, [url, mimeType, filename, onLoad, onError, t]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      message.success(
        t('components.codeViewer.copySuccess', { defaultValue: 'Copied to clipboard' })
      );
      setTimeout(() => {
        setCopied(false);
      }, 2000);
    } catch {
      void message.error(t('components.codeViewer.copyFailed', { defaultValue: 'Copy failed' }));
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Spin />
      </div>
    );
  }

  if (error) {
    return (
      <Alert
        type="error"
        title={t('components.codeViewer.loadFailed', { defaultValue: 'Failed to load content' })}
        description={error}
        showIcon
      />
    );
  }

  // Line count for display
  const lineCount = content.split('\n').length;

  return (
    <div className="code-viewer relative">
      {!compact && (
        <div className="flex items-center justify-between px-3 py-1 bg-gray-100 border-b border-gray-200 text-xs">
          <Text type="secondary">
            {t('components.codeViewer.meta', {
              defaultValue: '{{filename}} • {{language}} • {{lineCount}} lines',
              filename,
              language,
              lineCount,
            })}
          </Text>
          <Tooltip
            title={
              copied
                ? t('components.codeViewer.copied', { defaultValue: 'Copied!' })
                : t('components.codeViewer.copyCode', { defaultValue: 'Copy code' })
            }
          >
            <Button
              type="text"
              size="small"
              icon={copied ? <Check size={14} /> : <Copy size={14} />}
              onClick={() => {
                void handleCopy();
              }}
            />
          </Tooltip>
        </div>
      )}
      <pre
        className="m-0 p-3 overflow-auto bg-gray-900 text-gray-100 text-sm font-mono"
        style={{
          maxHeight: typeof maxHeight === 'number' ? maxHeight : undefined,
        }}
      >
        <code className={`language-${language}`}>{content}</code>
      </pre>
    </div>
  );
};

export default CodeViewer;
