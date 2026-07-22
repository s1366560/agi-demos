import { NON_AUTHORITATIVE } from './blackboardSurfaceContract';
import { SurfaceBadge } from './SurfaceBadge';

interface DerivedSurfaceBadgeProps {
  labelKey: string;
  fallbackLabel: string;
}

/** Thin wrapper over `SurfaceBadge`, kept for existing consumers. */
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
