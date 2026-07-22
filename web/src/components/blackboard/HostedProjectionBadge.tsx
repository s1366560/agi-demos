import { HOSTED, NON_AUTHORITATIVE } from './blackboardSurfaceContract';
import { SurfaceBadge } from './SurfaceBadge';

interface HostedProjectionBadgeProps {
  labelKey: string;
  fallbackLabel: string;
}

/** Thin wrapper over `SurfaceBadge`, kept for existing consumers. */
export function HostedProjectionBadge({ labelKey, fallbackLabel }: HostedProjectionBadgeProps) {
  return (
    <SurfaceBadge
      labelKey={labelKey}
      fallbackLabel={fallbackLabel}
      boundary={HOSTED}
      authority={NON_AUTHORITATIVE}
    />
  );
}
