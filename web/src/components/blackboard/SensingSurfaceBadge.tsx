import { NON_AUTHORITATIVE, SENSING_CAPABLE } from './blackboardSurfaceContract';
import { SurfaceBadge } from './SurfaceBadge';

interface SensingSurfaceBadgeProps {
  labelKey: string;
  fallbackLabel: string;
}

/** Thin wrapper over `SurfaceBadge`, kept for existing consumers. */
export function SensingSurfaceBadge({ labelKey, fallbackLabel }: SensingSurfaceBadgeProps) {
  return (
    <SurfaceBadge
      labelKey={labelKey}
      fallbackLabel={fallbackLabel}
      boundary="sensing"
      authority={NON_AUTHORITATIVE}
      signalRole={SENSING_CAPABLE}
    />
  );
}
