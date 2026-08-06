import type { FC, ReactNode } from 'react';

import { Loader2 } from 'lucide-react';

export interface SpinnerProps {
  /** Icon size in px. AntD mapping: small -> 16, default -> 24, large -> 32. */
  size?: number;
  /** Optional muted hint rendered below the indicator. */
  tip?: string | undefined;
  /**
   * Extra classes on the wrapping span. The icon inherits the wrapper's text
   * color (default `text-primary`), so pass e.g. `text-white` inside buttons.
   */
  className?: string;
}

export const Spinner: FC<SpinnerProps> = ({ size = 24, tip, className }) => {
  const indicator = (
    <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" size={size} />
  );

  if (tip === undefined) {
    return <span className={className ?? 'text-primary'}>{indicator}</span>;
  }

  return (
    <span className={`inline-flex flex-col items-center gap-2 ${className ?? 'text-primary'}`}>
      {indicator}
      <span className="text-xs text-slate-600 dark:text-slate-400">{tip}</span>
    </span>
  );
};

export interface LoadingOverlayProps {
  spinning: boolean;
  tip?: string;
  className?: string;
  children: ReactNode;
}

/**
 * AntD `Spin` wrapper replacement: dims and blocks the wrapped content while
 * `spinning` is true, with an overlay spinner centered on top.
 */
export const LoadingOverlay: FC<LoadingOverlayProps> = ({ spinning, tip, className, children }) => (
  <div className={`relative ${className ?? ''}`.trim()}>
    <div aria-busy={spinning} className={spinning ? 'pointer-events-none opacity-60' : undefined}>
      {children}
    </div>
    {spinning && (
      <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-white/60 dark:bg-slate-950/60">
        <Spinner tip={tip} />
      </div>
    )}
  </div>
);
