/**
 * ProjectManager Component Types
 *
 * Compound component pattern types for ProjectManager
 */

import type { Project } from '@/types/memory';

// ============================================================================
// ROOT COMPONENT PROPS
// ============================================================================

export interface ProjectManagerProps {
  /**
   * Callback when a project is selected
   */
  onProjectSelect?: ((project: Project) => void) | undefined;

  /**
   * Variant preset - 'full' renders all sub-components automatically
   * @default 'controlled'
   */
  variant?: 'controlled' | 'full' | undefined;

  /**
   * Additional CSS class names
   */
  className?: string | undefined;

  /**
   * Child components for compound pattern
   */
  children?: React.ReactNode | undefined;
}

// ============================================================================
// SEARCH COMPONENT PROPS
// ============================================================================

export interface ProjectManagerSearchProps {
  /**
   * Current search term value (controlled)
   */
  value?: string | undefined;

  /**
   * Initial search term value (uncontrolled)
   */
  defaultValue?: string | undefined;

  /**
   * Callback when search term changes
   */
  onChange?: ((term: string) => void) | undefined;

  /**
   * Search input placeholder
   * @default 'Search projects...'
   */
  placeholder?: string | undefined;

  /**
   * Additional CSS class names
   */
  className?: string | undefined;
}

// ============================================================================
// FILTERS COMPONENT PROPS
// ============================================================================

export interface ProjectManagerFiltersProps {
  /**
   * Current filter status (controlled)
   */
  value?: string | undefined;

  /**
   * Initial filter status (uncontrolled)
   */
  defaultValue?: string | undefined;

  /**
   * Callback when filter changes
   */
  onChange?: ((filter: string) => void) | undefined;

  /**
   * Available filter options
   * @default [{ value: 'all', label: 'All' }]
   */
  options?: Array<{ value: string; label: string }> | undefined;

  /**
   * Additional CSS class names
   */
  className?: string | undefined;
}

// ============================================================================
// LIST COMPONENT PROPS
// ============================================================================

export interface ProjectManagerListProps {
  /**
   * Custom render function for each project item
   */
  children?: ((project: Project, index: number) => React.ReactNode) | undefined;

  /**
   * Callback when a project is clicked
   */
  onProjectClick?: ((project: Project) => void) | undefined;

  /**
   * Callback when settings button is clicked
   */
  onSettingsClick?: ((project: Project, e: React.MouseEvent) => void) | undefined;

  /**
   * Callback when delete button is clicked
   */
  onDeleteClick?: ((project: Project, e: React.MouseEvent) => void) | undefined;

  /**
   * Layout variant
   * @default 'grid'
   */
  layout?: 'grid' | 'list' | undefined;

  /**
   * Grid columns (for grid layout)
   * @default 'md:grid-cols-2 lg:grid-cols-3'
   */
  gridCols?: string | undefined;

  /**
   * Additional CSS class names
   */
  className?: string | undefined;
}

// ============================================================================
// ITEM COMPONENT PROPS
// ============================================================================

export interface ProjectManagerItemProps {
  /**
   * The project to display
   */
  project: Project;

  /**
   * Whether this project is currently selected
   */
  isSelected?: boolean | undefined;

  /**
   * Callback when item is clicked
   */
  onClick?: ((project: Project) => void) | undefined;

  /**
   * Callback when settings button is clicked
   */
  onSettingsClick?: ((project: Project, e: React.MouseEvent) => void) | undefined;

  /**
   * Callback when delete button is clicked
   */
  onDeleteClick?: ((project: Project, e: React.MouseEvent) => void) | undefined;

  /**
   * Display variant
   * @default 'card'
   */
  variant?: 'card' | 'compact' | undefined;

  /**
   * Additional CSS class names
   */
  className?: string | undefined;
}

// ============================================================================
// MODAL COMPONENTS PROPS
// ============================================================================

export interface ProjectManagerCreateModalProps {
  /**
   * Whether the modal is open (controlled)
   */
  isOpen?: boolean | undefined;

  /**
   * Callback when modal is closed
   */
  onClose?: (() => void) | undefined;

  /**
   * Callback when project is created successfully
   */
  onSuccess?: (() => void) | undefined;

  /**
   * Additional CSS class names
   */
  className?: string | undefined;
}

export interface ProjectManagerSettingsModalProps {
  /**
   * The project to edit settings for
   */
  project: Project;

  /**
   * Whether the modal is open (controlled)
   */
  isOpen?: boolean | undefined;

  /**
   * Callback when modal is closed
   */
  onClose?: (() => void) | undefined;

  /**
   * Callback when settings are saved
   */
  onSave?: ((projectId: string, updates: Partial<Project>) => void | Promise<void>) | undefined;

  /**
   * Callback when project is deleted from settings
   */
  onDelete?: ((projectId: string) => void | Promise<void>) | undefined;

  /**
   * Additional CSS class names
   */
  className?: string | undefined;
}

// ============================================================================
// LOADING AND EMPTY STATES
// ============================================================================

export interface ProjectManagerLoadingProps {
  /**
   * Custom loading message
   */
  message?: string | undefined;

  /**
   * Additional CSS class names
   */
  className?: string | undefined;
}

export interface ProjectManagerEmptyProps {
  /**
   * Empty state message
   */
  message?: string | undefined;

  /**
   * Whether to show create button
   */
  showCreateButton?: boolean | undefined;

  /**
   * Callback when create button is clicked
   */
  onCreateClick?: (() => void) | undefined;

  /**
   * Empty state variant
   * @default 'no-projects'
   */
  variant?: 'no-projects' | 'no-results' | 'no-tenant' | undefined;

  /**
   * Additional CSS class names
   */
  className?: string | undefined;
}

// ============================================================================
// ERROR STATE PROPS
// ============================================================================

export interface ProjectManagerErrorProps {
  /**
   * Error message to display
   */
  error?: string | null | undefined;

  /**
   * Callback when error is dismissed
   */
  onDismiss?: (() => void) | undefined;

  /**
   * Additional CSS class names
   */
  className?: string | undefined;
}

// ============================================================================
// INTERNAL CONTEXT TYPES
// ============================================================================

export interface ProjectManagerContextValue {
  // Data
  projects: Project[];
  currentProject: Project | null;
  isLoading: boolean;
  error: string | null;
  currentTenant: { id: string; name: string } | null;

  // Search and filter state
  searchTerm: string;
  setSearchTerm: (term: string) => void;
  filterStatus: string;
  setFilterStatus: (filter: string) => void;

  // Error handling
  clearError: () => void;

  // Modal state
  isCreateModalOpen: boolean;
  setIsCreateModalOpen: (open: boolean) => void;
  isSettingsModalOpen: boolean;
  setIsSettingsModalOpen: (open: boolean) => void;
  selectedProjectForSettings: Project | null;
  setSelectedProjectForSettings: (project: Project | null) => void;

  // Actions
  handleProjectSelect: (project: Project) => void;
  handleDeleteProject: (projectId: string) => Promise<void>;
  handleOpenSettings: (project: Project, e: React.MouseEvent) => void;
  handleSaveSettings: (projectId: string, updates: Partial<Project>) => Promise<void>;
  handleDeleteFromSettings: (projectId: string) => Promise<void>;

  // External callback
  onProjectSelect?: ((project: Project) => void) | undefined;
}

// ============================================================================
// HELPER TYPES
// ============================================================================

export type ProjectManagerComponent = React.FC<ProjectManagerProps> & {
  Search: React.FC<ProjectManagerSearchProps>;
  Filters: React.FC<ProjectManagerFiltersProps>;
  List: React.FC<ProjectManagerListProps>;
  Item: React.FC<ProjectManagerItemProps>;
  CreateModal: React.FC<ProjectManagerCreateModalProps>;
  SettingsModal: React.FC<ProjectManagerSettingsModalProps>;
  Loading: React.FC<ProjectManagerLoadingProps>;
  Empty: React.FC<ProjectManagerEmptyProps>;
  Error: React.FC<ProjectManagerErrorProps>;
};
