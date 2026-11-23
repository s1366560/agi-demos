import { AUTHORITATIVE, OWNED } from './blackboardSurfaceContract';
import { SurfaceBadge } from './SurfaceBadge';

interface OwnedSurfaceBadgeProps {
  labelKey: string;
  fallbackLabel: string;
}

/** Thin wrapper over `SurfaceBadge`, kept for existing consumers. */
export function OwnedSurfaceBadge({ labelKey, fallbackLabel }: OwnedSurfaceBadgeProps) {
  return (
    <SurfaceBadge
      labelKey={labelKey}
      fallbackLabel={fallbackLabel}
      boundary={OWNED}
      authority={AUTHORITATIVE}
    />
  );
}
