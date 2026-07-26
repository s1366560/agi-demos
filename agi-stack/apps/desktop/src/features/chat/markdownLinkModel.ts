export type MarkdownLinkPresentation =
  | {
      kind: 'external';
      href: string;
    }
  | {
      kind: 'blocked';
    };

export function markdownLinkPresentation(
  href: string | undefined,
): MarkdownLinkPresentation {
  if (!href || href.trim() !== href) return { kind: 'blocked' };

  let target: URL;
  try {
    target = new URL(href);
  } catch {
    return { kind: 'blocked' };
  }

  if (
    (target.protocol !== 'https:' && target.protocol !== 'http:') ||
    target.username ||
    target.password
  ) {
    return { kind: 'blocked' };
  }

  return { kind: 'external', href };
}
