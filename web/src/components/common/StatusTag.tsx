import type { ReactNode } from 'react';

import { Tag } from 'antd';

/**
 * Props for the shared StatusTag component
 */
export interface StatusTagProps {
  /** AntD Tag color preset (or custom color) describing the status */
  color?: string | undefined;
  /** Optional leading status icon */
  icon?: ReactNode;
  /**
   * Display label. Callers own the i18n: pass text already resolved
   * through `t()` so status copy is never hardcoded here.
   */
  label: ReactNode;
}

/**
 * StatusTag - shared status pill (color + icon + label).
 *
 * Generic primitive for "color + icon + label" status tags used across
 * admin/monitoring pages (DLQ message status, pool instance status, tier,
 * health, ...). The caller injects the translated label via `t()`; this
 * component only owns presentation.
 */
export const StatusTag = ({ color = 'default', icon, label }: StatusTagProps) => (
  <Tag color={color} icon={icon}>
    {label}
  </Tag>
);

export default StatusTag;
