/**
 * CommunitiesList Compound Component Types
 *
 * Defines the type system for the compound CommunitiesList component.
 */

import type { TimelineEvent } from '../../../types/agent';

// ========================================
// Domain Types
// ========================================

export interface Community {
  uuid: string
  name: string
  summary: string
  member_count: number
  formed_at?: string
  created_at?: string
}

export interface Entity {
  uuid: string
  name: string
  entity_type: string
  summary: string
}

export interface BackgroundTask {
  task_id: string
  task_type: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  created_at: string
  started_at?: string
  completed_at?: string
  progress: number
  message: string
  result?: {
    communities_count?: number
    edges_count?: number
  }
  error?: string
}

// ========================================
// Component Props
// ========================================

/**
 * Props for the root CommunitiesList component
 */
export interface CommunitiesListRootProps {
  /** Children for compound component pattern */
  children?: React.ReactNode;
}

/**
 * Props for Header sub-component
 */
export interface CommunitiesListHeaderProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for Stats sub-component
 */
export interface CommunitiesListStatsProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for List sub-component (community grid)
 */
export interface CommunitiesListListProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for Pagination sub-component
 */
export interface CommunitiesListPaginationProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for Detail sub-component (right panel)
 */
export interface CommunitiesListDetailProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for TaskStatus sub-component (background task)
 */
export interface CommunitiesListTaskStatusProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * Props for Error sub-component
 */
export interface CommunitiesListErrorProps {
  /** Optional custom class name */
  className?: string;
}

/**
 * CommunitiesList compound component interface
 */
export interface CommunitiesListCompound extends React.FC<CommunitiesListRootProps> {
  /** Page header sub-component */
  Header: React.FC<CommunitiesListHeaderProps>;
  /** Stats display sub-component */
  Stats: React.FC<CommunitiesListStatsProps>;
  /** Community grid/list sub-component */
  List: React.FC<CommunitiesListListProps>;
  /** Pagination controls sub-component */
  Pagination: React.FC<CommunitiesListPaginationProps>;
  /** Community detail panel sub-component */
  Detail: React.FC<CommunitiesListDetailProps>;
  /** Background task status sub-component */
  TaskStatus: React.FC<CommunitiesListTaskStatusProps>;
  /** Error message sub-component */
  Error: React.FC<CommunitiesListErrorProps>;
  /** Root component alias */
  Root: React.FC<CommunitiesListRootProps>;
}
