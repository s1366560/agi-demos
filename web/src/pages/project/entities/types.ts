/**
 * EntitiesList Compound Component Types
 *
 * Defines the type system for the compound EntitiesList component.
 */

/**
 * Entity data structure
 */
export interface Entity {
  uuid: string;
  name: string;
  entity_type: string;
  summary: string;
  created_at?: string | undefined;
}

/**
 * Entity type with count
 */
export interface EntityType {
  entity_type: string;
  count: number;
}

/**
 * Relationship data structure
 */
export interface Relationship {
  edge_id: string;
  relation_type: string;
  direction: string;
  fact: string;
  score: number;
  created_at?: string | undefined;
  related_entity: {
    uuid: string;
    name: string;
    entity_type: string;
    summary: string;
  };
}

/**
 * Sort options for entities
 */
export type SortOption = 'name' | 'created_at';

/**
 * Props for the root EntitiesList component
 */
export interface EntitiesListRootProps {
  /** Project ID from route */
  projectId?: string | undefined;
  /** Children for compound component pattern */
  children?: React.ReactNode | undefined;
  /** Default sort option */
  defaultSortBy?: SortOption | undefined;
  /** Items per page */
  limit?: number | undefined;
}

/**
 * Props for Header sub-component
 */
export interface EntitiesListHeaderProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Filters sub-component
 */
export interface EntitiesListFiltersProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Stats sub-component
 */
export interface EntitiesListStatsProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for List sub-component
 */
export interface EntitiesListListProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Pagination sub-component
 */
export interface EntitiesListPaginationProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Detail sub-component
 */
export interface EntitiesListDetailProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * EntitiesList compound component interface
 * Extends React.FC with sub-component properties
 */
export interface EntitiesListCompound extends React.FC<EntitiesListRootProps> {
  /** Page header sub-component */
  Header: React.FC<EntitiesListHeaderProps>;
  /** Filters panel sub-component */
  Filters: React.FC<EntitiesListFiltersProps>;
  /** Stats display sub-component */
  Stats: React.FC<EntitiesListStatsProps>;
  /** Entity list sub-component */
  List: React.FC<EntitiesListListProps>;
  /** Pagination controls sub-component */
  Pagination: React.FC<EntitiesListPaginationProps>;
  /** Entity detail panel sub-component */
  Detail: React.FC<EntitiesListDetailProps>;
  /** Root component alias */
  Root: React.FC<EntitiesListRootProps>;
}
