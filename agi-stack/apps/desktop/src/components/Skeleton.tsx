import type { CSSProperties, ReactNode } from 'react';

import './Skeleton.css';

export type SkeletonVariant = 'text' | 'rect' | 'circle';

export function Skeleton({
  variant = 'text',
  width,
  height,
  className,
}: {
  variant?: SkeletonVariant;
  width?: number | string;
  height?: number | string;
  className?: string;
}) {
  const style: CSSProperties = {};
  if (width !== undefined) style.width = width;
  if (height !== undefined) style.height = height;
  return (
    <span
      aria-hidden="true"
      className={`skeleton skeleton-${variant}${className ? ` ${className}` : ''}`}
      style={style}
    />
  );
}

/**
 * Groups skeleton placeholders under a single live region so screen readers
 * announce the localized loading label once for the whole group.
 */
export function SkeletonGroup({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={`skeleton-group${className ? ` ${className}` : ''}`}
      role="status"
      aria-label={label}
    >
      {children}
      <span className="sr-only">{label}</span>
    </div>
  );
}
