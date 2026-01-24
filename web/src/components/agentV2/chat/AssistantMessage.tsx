/**
 * Assistant Message
 *
 * Displays a message from the AI assistant with markdown rendering.
 */

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CopyOutlined } from '@ant-design/icons';

interface AssistantMessageProps {
  content: string;
  isStreaming?: boolean;
  createdAt?: string;
}

export function AssistantMessage({ content, isStreaming = false, createdAt }: AssistantMessageProps) {
  const copyCode = (code: string) => {
    navigator.clipboard.writeText(code);
  };

  return (
    <div className="flex justify-start">
      <div className="max-w-4xl flex-1">
        {/* Message header */}
        <div className="flex items-center gap-2 mb-2">
          <div className="w-8 h-8 bg-gradient-to-br from-purple-500 to-pink-500 rounded-full flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 20 20">
              <path d="M10 2a6 6 0 00-6 6v3.586l-.707.707A1 1 0 004 14h12a1 1 0 00.707-1.707L16 11.586V8a6 6 0 00-6-6zM10 18a3 3 0 01-3-3h6a3 3 0 01-3 3z" />
            </svg>
          </div>
          <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
            Agent
          </span>
          {createdAt && (
            <span className="text-xs text-gray-500">
              {new Date(createdAt).toLocaleTimeString()}
            </span>
          )}
          {isStreaming && (
            <span className="flex items-center gap-1 text-xs text-gray-500">
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-pulse" />
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-pulse delay-75" />
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-pulse delay-150" />
            </span>
          )}
        </div>

        {/* Message content with Markdown */}
        <div className="bg-gray-100 dark:bg-gray-800 px-4 py-3 rounded-2xl rounded-tl-sm prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              // Code blocks with syntax highlighting and copy button
              pre({ children, ...props }: any) {
                const codeElement = children as React.ReactElement & { props?: { children?: string } };
                const codeString = codeElement?.props?.children || '';

                return (
                  <div className="relative group my-3">
                    <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => copyCode(String(codeString))}
                        className="p-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-xs flex items-center gap-1"
                        title="Copy code"
                      >
                        <CopyOutlined className="text-xs" />
                        Copy
                      </button>
                    </div>
                    <pre {...props} className="bg-gray-900 dark:bg-gray-950 p-4 rounded-lg overflow-x-auto">
                      {children}
                    </pre>
                  </div>
                );
              },
              // Inline code
              code({ children, node, ...props }: any) {
                const parentElement = (node as any)?.parent;
                const isInline = parentElement?.type !== 'codeBlock' && parentElement?.tagName !== 'pre';
                if (isInline) {
                  return (
                    <code {...props} className="px-1.5 py-0.5 bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 rounded text-sm font-mono">
                      {children}
                    </code>
                  );
                }
                return <code {...props}>{children}</code>;
              },
              // Links
              a({ children, href, ...props }: any) {
                return (
                  <a
                    {...props}
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 dark:text-blue-400 hover:underline"
                  >
                    {children}
                  </a>
                );
              },
              // Blockquotes
              blockquote({ children, ...props }: any) {
                return (
                  <blockquote
                    {...props}
                    className="border-l-4 border-gray-300 dark:border-gray-600 pl-4 italic text-gray-600 dark:text-gray-400 my-2"
                  >
                    {children}
                  </blockquote>
                );
              },
              // Tables
              table({ children, ...props }: any) {
                return (
                  <div className="overflow-x-auto my-4">
                    <table {...props} className="min-w-full divide-y divide-gray-200 dark:divide-gray-700 border border-gray-300 dark:border-gray-600">
                      {children}
                    </table>
                  </div>
                );
              },
              thead({ children, ...props }: any) {
                return (
                  <thead {...props} className="bg-gray-50 dark:bg-gray-800">
                    {children}
                  </thead>
                );
              },
              th({ children, ...props }: any) {
                return (
                  <th
                    {...props}
                    className="px-4 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider"
                  >
                    {children}
                  </th>
                );
              },
              td({ children, ...props }: any) {
                return (
                  <td {...props} className="px-4 py-2 text-sm text-gray-900 dark:text-gray-100">
                    {children}
                  </td>
                );
              },
              // Lists
              ul({ children, ...props }: any) {
                return (
                  <ul {...props} className="list-disc list-inside my-2 space-y-1">
                    {children}
                  </ul>
                );
              },
              ol({ children, ...props }: any) {
                return (
                  <ol {...props} className="list-decimal list-inside my-2 space-y-1">
                    {children}
                  </ol>
                );
              },
              li({ children, ...props }: any) {
                return (
                  <li {...props} className="text-gray-800 dark:text-gray-200">
                    {children}
                  </li>
                );
              },
              // Headings
              h1({ children, ...props }: any) {
                return (
                  <h1 {...props} className="text-xl font-bold text-gray-900 dark:text-gray-100 mt-4 mb-2">
                    {children}
                  </h1>
                );
              },
              h2({ children, ...props }: any) {
                return (
                  <h2 {...props} className="text-lg font-bold text-gray-900 dark:text-gray-100 mt-3 mb-2">
                    {children}
                  </h2>
                );
              },
              h3({ children, ...props }: any) {
                return (
                  <h3 {...props} className="text-base font-bold text-gray-900 dark:text-gray-100 mt-2 mb-1">
                    {children}
                  </h3>
                );
              },
              // Paragraphs
              p({ children, ...props }: any) {
                return (
                  <p {...props} className="text-gray-800 dark:text-gray-200 my-1">
                    {children}
                  </p>
                );
              },
              // Strong/Bold
              strong({ children, ...props }: any) {
                return (
                  <strong {...props} className="font-bold text-gray-900 dark:text-gray-100">
                    {children}
                  </strong>
                );
              },
              // Em/Italic
              em({ children, ...props }: any) {
                return (
                  <em {...props} className="italic text-gray-800 dark:text-gray-200">
                    {children}
                  </em>
                );
              },
              // HR
              hr({ ...props }: any) {
                return <hr {...props} className="my-4 border-gray-300 dark:border-gray-600" />;
              },
            }}
          >
            {content}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
