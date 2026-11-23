import type { MarketText } from './pluginMarketText';
import type { CatalogItem, Localized } from './pluginMarketTypes';

const drawings = {
  'message-square': 'M21 11a8 8 0 0 1-8 8H7l-5 3 1.5-6A8 8 0 0 1 2 11a9 9 0 0 1 19 0ZM7 9h9M7 13h6',
  workflow: 'M3 3h7v6H3zM14 15h7v6h-7zM6.5 9v5a4 4 0 0 0 4 4H14M14 6h6m-3-3 3 3-3 3',
  receipt: 'M5 3l3 2 4-2 4 2 3-2v18l-3-2-4 2-4-2-3 2zM9 9h6m-6 4h6',
  terminal:
    'M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm3 4 4 4-4 4m6 0h4',
  'book-open': 'M12 6c-3-2-6-2-10-1v14c4-1 7-1 10 1 3-2 6-2 10-1V5c-4-1-7-1-10 1Zm0 0v14',
  'panels-top-left':
    'M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm-1 5h18M9 8v13',
  box: 'm12 2 9 5v10l-9 5-9-5V7zM3 7l9 5 9-5m-9 5v10',
  search: 'M17 17l5 5m-3-12a8 8 0 1 1-16 0 8 8 0 1 1 16 0',
  arrow: 'M5 12h14m-6-6 6 6-6 6',
  back: 'M19 12H5m6-6-6 6 6 6',
  refresh: 'M20 7a9 9 0 1 0 1 8m-1-13v6h-6',
  upload: 'M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5',
  more: 'M4 12h1m6 0h1m6 0h1',
  source: 'M3 6c0-5 18-5 18 0s-18 5-18 0Zm0 0v6c0 5 18 5 18 0V6M3 12v6c0 5 18 5 18 0v-6',
  lock: 'M5 10h14v11H5zM8 10V7a4 4 0 0 1 8 0v3',
  check: 'm4 12 5 5L20 6',
};
type GlyphName = keyof typeof drawings;
export function Mark({ name, size = 18 }: { name: GlyphName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={drawings[name]} />
    </svg>
  );
}
const icons = [
  'message-square',
  'workflow',
  'receipt',
  'terminal',
  'book-open',
  'panels-top-left',
] as const;
export function PackageIcon({ icon }: { icon: string | null }) {
  const glyph = icons.find((key) => key === icon) ?? 'box';
  return (
    <span className={'pm-icon pm-icon-' + glyph}>
      <Mark name={glyph} size={26} />
    </span>
  );
}
export function localize(value: Localized | null | undefined, locale: string | undefined) {
  return (locale ?? navigator.language).startsWith('zh')
    ? value?.zh || value?.en
    : value?.en || value?.zh;
}
export function marketName(item: CatalogItem, locale?: string) {
  return localize(item.display_name, locale) || item.package_name || item.plugin_id;
}
export function platforms(targets: string[], t: MarketText) {
  const map: Record<string, string> = {
    web: t.web,
    'desktop-renderer': t.desktop,
    python: t.cloud,
    'desktop-sidecar': t.device,
  };
  return [...new Set(targets.map((target) => map[target] ?? target))];
}
export function MarketStatus({ item, text }: { item: CatalogItem; text: MarketText }) {
  const installed = item.installation;
  if (!installed?.installed_version) return null;
  const state = installed.failure
    ? 'failed'
    : item.update_available
      ? 'updateBadge'
      : installed.running_version
        ? 'ready'
        : 'disabled';
  return <span className={'pm-status pm-status-' + state}>{text[state]}</span>;
}
