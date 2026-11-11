const DEFAULT_TITLE_LENGTH = 48;

/** Keep the window/header title readable without changing the persisted
 * conversation title. Cuts at a whitespace or common sentence boundary when
 * one is close to the limit; otherwise it uses a hard character cut. */
export function compactConversationTitle(
  title: string,
  maxLength = DEFAULT_TITLE_LENGTH,
): string {
  const normalized = title.replace(/\s+/g, ' ').trim();
  if (!normalized || normalized.length <= maxLength) return normalized;
  const window = normalized.slice(0, maxLength);
  const boundary = Math.max(
    window.lastIndexOf(' '),
    window.lastIndexOf('，'),
    window.lastIndexOf('。'),
    window.lastIndexOf('、'),
    window.lastIndexOf('：'),
    window.lastIndexOf(':'),
  );
  const body =
    boundary >= Math.floor(maxLength * 0.55) ? window.slice(0, boundary) : window;
  return `${body.trimEnd()}…`;
}
