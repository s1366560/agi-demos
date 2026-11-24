import type { ComponentType, CSSProperties, ReactNode } from 'react';

interface SyntaxHighlighterProps {
  style?: Record<string, unknown> | undefined;
  language?: string | undefined;
  PreTag?: string | undefined;
  customStyle?: CSSProperties | undefined;
  children?: ReactNode | undefined;
}

export interface SyntaxHighlighterBundle {
  SyntaxHighlighter: ComponentType<SyntaxHighlighterProps>;
  theme: Record<string, unknown>;
}
