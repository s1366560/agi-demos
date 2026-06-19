/**
 * MarkdownContent - Unified Markdown rendering component
 *
 * Provides consistent Markdown rendering across the application with:
 * - GitHub Flavored Markdown (GFM) support (tables, strikethrough, task lists)
 * - Proper styling for links and images
 * - Syntax highlighting support (via prose classes)
 * - Code block actions (Copy, Open in Canvas)
 * - Lazy loading for heavy plugins (mermaid, math)
 * - Memoization for performance
 *
 * This component can be reused in:
 * - AssistantMessage
 * - ToolExecutionCardDisplay (for tool results)
 * - FinalResponseDisplay
 *
 * @example
 * // Full prose styling with code actions (for message content)
 * <MarkdownContent content="# Header\n\n```js\nconst x = 1;\n```" prose codeActions />
 *
 * @example
 * // Minimal styling (for inline or tool results)
 * <MarkdownContent content="**Result:** Done" className="text-xs" />
 */

import { isValidElement, memo, useMemo } from 'react';
import type { ReactElement, ReactNode } from 'react';

import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';

import { looksLikeCanonicalStory, parseCanonicalStory } from '../canonicalStory/canonicalStory';
import { CanonicalStoryCard } from '../canonicalStory/CanonicalStoryCard';
import { MARKDOWN_PROSE_CLASSES } from '../styles';

import { CodeBlock } from './CodeBlock';
import { useMarkdownPlugins } from './markdownPlugins';
import { safeMarkdownComponents } from './safeMarkdownComponents';

/**
 * Inspect the `<code>` child react-markdown places inside `<pre>` and, when
 * its language is `yaml` (or `canonical-story`) and the content looks like a
 * canonical story document, return its raw text. Otherwise return null so the
 * normal CodeBlock path handles syntax highlighting.
 */
function extractCanonicalStoryYaml(children: ReactNode): string | null {
  let codeEl: ReactElement<{ className?: string; children?: ReactNode }> | null = null;
  if (isValidElement<{ className?: string; children?: ReactNode }>(children)) {
    codeEl = children;
  } else if (Array.isArray(children)) {
    const childNodes = children as ReactNode[];
    const found = childNodes.find(
      (child): child is ReactElement<{ className?: string; children?: ReactNode }> =>
        isValidElement<{ className?: string; children?: ReactNode }>(child)
    );
    if (found) codeEl = found;
  }
  if (!codeEl) return null;
  const className = codeEl.props.className ?? '';
  if (!/language-(yaml|canonical-story)/.test(className)) return null;
  const text = collectText(codeEl.props.children);
  if (!text || !looksLikeCanonicalStory(text)) return null;
  return text;
}

function collectText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(collectText).join('');
  if (isValidElement(node)) {
    const props = node.props as { children?: ReactNode };
    return collectText(props.children);
  }
  return '';
}

export interface MarkdownContentProps {
  /** Markdown content to render */
  content: string;
  /** Additional CSS classes for the container */
  className?: string | undefined;
  /** Whether to enable full prose styling */
  prose?: boolean | undefined;
  /** Whether to show code block actions (copy, open in canvas) */
  codeActions?: boolean | undefined;
}

/**
 * MarkdownContent component
 *
 * Optimizations:
 * - React.memo prevents re-renders when props haven't changed
 * - Lazy loading for heavy Markdown plugins
 * - useMemo for plugin initialization
 */
export const MarkdownContent = memo<MarkdownContentProps>(
  ({ content, className = '', prose = true, codeActions = false }) => {
    const combinedClassName = prose ? `${MARKDOWN_PROSE_CLASSES} ${className}`.trim() : className;

    // Stable components reference
    const components: Components = useMemo(() => {
      const baseStoryAware: Components = {
        ...safeMarkdownComponents,
        pre: ({ children }) => {
          const yamlText = extractCanonicalStoryYaml(children);
          if (yamlText !== null) {
            return (
              <div className="my-2">
                <CanonicalStoryCard result={parseCanonicalStory(yamlText)} />
              </div>
            );
          }
          if (codeActions) {
            return <CodeBlock>{children}</CodeBlock>;
          }
          return <pre>{children}</pre>;
        },
      };
      return baseStoryAware;
    }, [codeActions]);

    const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(content);

    return (
      <div className={combinedClassName}>
        <ReactMarkdown
          remarkPlugins={remarkPlugins}
          rehypePlugins={rehypePlugins}
          components={components}
        >
          {content}
        </ReactMarkdown>
      </div>
    );
  },
  // Custom comparison function for better memoization
  (prevProps, nextProps) => {
    return (
      prevProps.content === nextProps.content &&
      prevProps.className === nextProps.className &&
      prevProps.prose === nextProps.prose &&
      prevProps.codeActions === nextProps.codeActions
    );
  }
);

MarkdownContent.displayName = 'MarkdownContent';

export default MarkdownContent;
