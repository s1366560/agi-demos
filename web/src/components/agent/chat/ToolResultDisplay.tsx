import { useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { AlertCircle, ChevronDown, ChevronUp, TerminalSquare } from 'lucide-react';

import { foldTextWithMetadata } from '../../../utils/toolResultUtils';

import { MarkdownContent } from './MarkdownContent';

interface ToolResultDisplayProps {
  /** Result text to display */
  result: string;
  /** Whether this is an error result */
  isError: boolean;
}

export function ToolResultDisplay({ result, isError }: ToolResultDisplayProps) {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(false);

  // Memoize the folded result calculation
  const { foldedText, isFolded, totalLines } = useMemo(() => {
    const { text, folded } = foldTextWithMetadata(result, 5);
    const lines = result.split('\n').length;
    return { foldedText: text, isFolded: folded, totalLines: lines };
  }, [result]);

  const displayText = isExpanded ? result : foldedText;

  if (isError) {
    return (
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-2xs font-semibold uppercase tracking-label text-red-600 flex items-center gap-1">
            <AlertCircle size={12} />
            {t('components.messageStream.error', { defaultValue: 'Error' })}
          </span>
          {isFolded && (
            <button
              type="button"
              onClick={() => {
                setIsExpanded(!isExpanded);
              }}
              className="text-2xs text-red-500 hover:text-red-600 font-medium flex items-center gap-1"
            >
              {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {isExpanded
                ? t('components.messageStream.showLess', { defaultValue: 'Show Less' })
                : t('components.messageStream.showFullLines', {
                    defaultValue: 'Show Full ({{count}} lines)',
                    count: totalLines,
                  })}
            </button>
          )}
        </div>
        <div className="px-3 py-2 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/20 rounded-md text-xs font-mono text-red-700 dark:text-red-300 overflow-x-auto max-h-48 overflow-y-auto">
          <pre className="whitespace-pre-wrap break-words">{displayText}</pre>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-2xs font-semibold uppercase tracking-label text-emerald-600 flex items-center gap-1">
          <TerminalSquare size={12} />
          {t('components.messageStream.output', { defaultValue: 'Output' })}
        </span>
        {isFolded && (
          <button
            type="button"
            onClick={() => {
              setIsExpanded(!isExpanded);
            }}
            className="text-2xs text-emerald-600 hover:text-emerald-700 font-medium flex items-center gap-1"
          >
            {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {isExpanded
              ? t('components.messageStream.showLess', { defaultValue: 'Show Less' })
              : t('components.messageStream.showFullLines', {
                  defaultValue: 'Show Full ({{count}} lines)',
                  count: totalLines,
                })}
          </button>
        )}
      </div>
      <div
        className={`px-3 py-2 bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/20 rounded-md text-xs text-slate-700 dark:text-slate-300 overflow-x-auto ${isExpanded ? 'max-h-96' : 'max-h-48'} overflow-y-auto`}
      >
        <MarkdownContent
          content={displayText}
          className="prose-p:my-0 prose-headings:my-1 prose-ul:my-0 prose-ol:my-0"
          prose={true}
        />
      </div>
    </div>
  );
}
