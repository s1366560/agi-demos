import { NON_AUTHORITATIVE } from './blackboardSurfaceContract';
import { SurfaceBadge } from './SurfaceBadge';

interface DerivedSurfaceBadgeProps {
  labelKey: string;
  fallbackLabel: string;
}

/**
 * @deprecated Use `SurfaceBadge` with `boundary="derived"` directly.
 * Thin wrapper kept for existing consumers.
 */
export function DerivedSurfaceBadge({ labelKey, fallbackLabel }: DerivedSurfaceBadgeProps) {
  return (
    <SurfaceBadge
      labelKey={labelKey}
      fallbackLabel={fallbackLabel}
      boundary="derived"
      authority={NON_AUTHORITATIVE}
    />
  );
}
