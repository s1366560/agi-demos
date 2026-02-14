/**
 * McpServerList Page Types
 */

export type McpTabKey = 'servers' | 'tools' | 'apps';

export interface McpTab {
  key: McpTabKey;
  label: string;
  icon: string;
  count: number;
}

export interface McpServerListProps {
  className?: string;
}

export interface StatsCardProps {
  title: string;
  value: number | string;
  icon: string;
  iconColor?: string;
  valueColor?: string;
}
