import React from 'react';
import type { FC } from 'react';

import { isFeatureEnabled } from '@/utils/featureCheck';

interface FeatureGateProps {
  feature: string;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export const FeatureGate: FC<FeatureGateProps> = ({ feature, children, fallback = null }) => {
  return isFeatureEnabled(feature) ? <>{children}</> : <>{fallback}</>;
};
