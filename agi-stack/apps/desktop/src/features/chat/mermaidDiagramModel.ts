export type DesktopAppearance = 'dark' | 'light';
export type MermaidTheme = 'dark' | 'default';

/** Mermaid rendering is selected only by the structured Markdown language info string. */
export function shouldRenderMermaidDiagram(
  language: string | null | undefined,
): boolean {
  return language === 'mermaid';
}

export function mermaidThemeForAppearance(appearance: DesktopAppearance): MermaidTheme {
  return appearance === 'dark' ? 'dark' : 'default';
}
