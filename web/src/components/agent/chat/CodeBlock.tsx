import { memo, type ReactNode } from 'react';
import { useCanvasStore } from '@/stores/canvasStore';
import { useLayoutModeStore } from '@/stores/layoutMode';
import { CodeBlock as PackageCodeBlock } from '@business/agent/ui/web/chat/CodeBlock';
import { useSyntaxHighlighter } from '@business/agent/ui/web/canvas/useSyntaxHighlighter';
import { MermaidBlock } from './MermaidBlock';

function openInCanvas(text: string, language?: string) {
  const id = `code-${String(Date.now())}`;
  const title = language ? `snippet.${language}` : 'snippet.txt';

  useCanvasStore.getState().openTab({
    id,
    title,
    type: 'code',
    content: text,
    language,
  });

  const currentMode = useLayoutModeStore.getState().mode;
  if (currentMode !== 'canvas') {
    useLayoutModeStore.getState().setMode('canvas');
  }
}
const renderDiagram = (chart: string) => <MermaidBlock chart={chart} />;
export const CodeBlock = memo(function CodeBlock(props: { children?: ReactNode | undefined }) {
  const highlighter = useSyntaxHighlighter();
  return (
    <PackageCodeBlock
      {...props}
      highlighter={highlighter}
      onOpenInCanvas={openInCanvas}
      renderDiagram={renderDiagram}
      copyEnabled
    />
  );
});
