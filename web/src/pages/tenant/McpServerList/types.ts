/**
 * McpServerList Compound Component Types
 *
 * Type definitions for the McpServerList compound component pattern.
 */

import type { MCPServerResponse, MCPServerType } from '../../../types/agent';

// ============================================================================
// Context State
// ============================================================================

export interface McpServerListState {
  // Filters
  search: string;
  enabledFilter: 'all' | 'enabled' | 'disabled';
  typeFilter: 'all' | MCPServerType;

  // Modals
  isModalOpen: boolean;
  editingServer: MCPServerResponse | null;
  toolsModalServer: MCPServerResponse | null;

  // Computed values
  enabledCount: number;
  totalToolsCount: number;
  total: number;
  serversByType: Record<MCPServerType, number>;
  filteredServers: MCPServerResponse[];

  // Store state
  servers: MCPServerResponse[];
  syncingServers: Set<string>;
  testingServers: Set<string>;
  isLoading: boolean;
  error: string | null;
}

// ============================================================================
// Context Actions
// ============================================================================

export interface McpServerListActions {
  setSearch: (search: string) => void;
  setEnabledFilter: (filter: 'all' | 'enabled' | 'disabled') => void;
  setTypeFilter: (filter: 'all' | MCPServerType) => void;
  handleCreate: () => void;
  handleEdit: (server: MCPServerResponse) => void;
  handleToggleEnabled: (server: MCPServerResponse, enabled: boolean) => Promise<void>;
  handleSync: (server: MCPServerResponse) => Promise<void>;
  handleTest: (server: MCPServerResponse) => Promise<void>;
  handleDelete: (id: string) => Promise<void>;
  handleModalClose: () => void;
  handleModalSuccess: () => void;
  handleRefresh: () => void;
  handleShowTools: (server: MCPServerResponse) => void;
  handleCloseToolsModal: () => void;
  formatLastSync: (dateStr?: string) => string;
}

// ============================================================================
// Context Value
// ============================================================================

export interface McpServerListContextValue extends McpServerListState, McpServerListActions {}

// ============================================================================
// Sub-Component Props
// ============================================================================

// Header
export interface McpServerListHeaderProps {
  onCreate: () => void;
}

// Stats Cards
export interface McpServerListStatsProps {
  total: number;
  enabledCount: number;
  totalToolsCount: number;
  serversByType: Record<MCPServerType, number>;
}

export interface McpServerListStatsCardProps {
  title: string;
  value: string | number;
  icon: string;
  iconColor?: string;
  valueColor?: string;
  extra?: React.ReactNode;
}

// Filters
export interface McpServerListFiltersProps {
  search: string;
  onSearchChange: (value: string) => void;
  enabledFilter: 'all' | 'enabled' | 'disabled';
  onEnabledFilterChange: (filter: 'all' | 'enabled' | 'disabled') => void;
  typeFilter: 'all' | MCPServerType;
  onTypeFilterChange: (filter: 'all' | MCPServerType) => void;
  onRefresh: () => void;
}

// Server Card
export interface McpServerCardProps {
  server: MCPServerResponse;
  syncingServers: Set<string>;
  testingServers: Set<string>;
  onToggle: (server: MCPServerResponse, enabled: boolean) => void;
  onSync: (server: MCPServerResponse) => void;
  onTest: (server: MCPServerResponse) => void;
  onEdit: (server: MCPServerResponse) => void;
  onDelete: (id: string) => void;
  onShowTools: (server: MCPServerResponse) => void;
  formatLastSync: (dateStr?: string) => string;
}

// Server Type Badge
export interface ServerTypeBadgeProps {
  type: MCPServerType;
}

// Tools Modal
export interface ToolsModalProps {
  server: MCPServerResponse;
  onClose: () => void;
}

// Loading State
// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface McpServerListLoadingProps {}

// Empty State
// eslint-disable-next-line @typescript-eslint/no-empty-object-type
export interface McpServerListEmptyProps {}

// Server Grid
export interface McpServerListGridProps {
  servers: MCPServerResponse[];
  syncingServers: Set<string>;
  testingServers: Set<string>;
  onToggle: (server: MCPServerResponse, enabled: boolean) => void;
  onSync: (server: MCPServerResponse) => void;
  onTest: (server: MCPServerResponse) => void;
  onEdit: (server: MCPServerResponse) => void;
  onDelete: (id: string) => void;
  onShowTools: (server: MCPServerResponse) => void;
  formatLastSync: (dateStr?: string) => string;
}

// Server Modal Wrapper
export interface McpServerListModalProps {
  isOpen: boolean;
  server: MCPServerResponse | null;
  onClose: () => void;
  onSuccess: () => void;
}

// ============================================================================
// Main Component Props
// ============================================================================

export interface McpServerListProps {
  className?: string;
}
