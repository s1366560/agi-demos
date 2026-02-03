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
  onProjectSelect?: (project: Project) => void;

  /**
   * Variant preset - 'full' renders all sub-components automatically
   * @default 'controlled'
   */
  variant?: 'controlled' | 'full';

  /**
   * Additional CSS class names
   */
  className?: string;

  /**
   * Child components for compound pattern
   */
  children?: React.ReactNode;
}

// ============================================================================
// SEARCH COMPONENT PROPS
// ============================================================================

export interface ProjectManagerSearchProps {
  /**
   * Current search term value (controlled)
   */
  value?: string;

  /**
   * Initial search term value (uncontrolled)
   */
  defaultValue?: string;

  /**
   * Callback when search term changes
   */
  onChange?: (term: string) => void;

  /**
   * Search input placeholder
   * @default 'Search projects...'
   */
  placeholder?: string;

  /**
   * Additional CSS class names
   */
  className?: string;
}

// ============================================================================
// FILTERS COMPONENT PROPS
// ============================================================================

export interface ProjectManagerFiltersProps {
  /**
   * Current filter status (controlled)
   */
  value?: string;

  /**
   * Initial filter status (uncontrolled)
   */
  defaultValue?: string;

  /**
   * Callback when filter changes
   */
  onChange?: (filter: string) => void;

  /**
   * Available filter options
   * @default [{ value: 'all', label: 'All' }]
   */
  options?: Array<{ value: string; label: string }>;

  /**
   * Additional CSS class names
   */
  className?: string;
}

// ============================================================================
// LIST COMPONENT PROPS
// ============================================================================

export interface ProjectManagerListProps {
  /**
   * Custom render function for each project item
   */
  children?: (project: Project, index: number) => React.ReactNode;

  /**
   * Callback when a project is clicked
   */
  onProjectClick?: (project: Project) => void;

  /**
   * Callback when settings button is clicked
   */
  onSettingsClick?: (project: Project, e: React.MouseEvent) => void;

  /**
   * Callback when delete button is clicked
   */
  onDeleteClick?: (project: Project, e: React.MouseEvent) => void;

  /**
   * Layout variant
   * @default 'grid'
   */
  layout?: 'grid' | 'list';

  /**
   * Grid columns (for grid layout)
   * @default 'md:grid-cols-2 lg:grid-cols-3'
   */
  gridCols?: string;

  /**
   * Additional CSS class names
   */
  className?: string;
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
  isSelected?: boolean;

  /**
   * Callback when item is clicked
   */
  onClick?: (project: Project) => void;

  /**
   * Callback when settings button is clicked
   */
  onSettingsClick?: (project: Project, e: React.MouseEvent) => void;

  /**
   * Callback when delete button is clicked
   */
  onDeleteClick?: (project: Project, e: React.MouseEvent) => void;

  /**
   * Display variant
   * @default 'card'
   */
  variant?: 'card' | 'compact';

  /**
   * Additional CSS class names
   */
  className?: string;
}

// ============================================================================
// MODAL COMPONENTS PROPS
// ============================================================================

export interface ProjectManagerCreateModalProps {
  /**
   * Whether the modal is open (controlled)
   */
  isOpen?: boolean;

  /**
   * Callback when modal is closed
   */
  onClose?: () => void;

  /**
   * Callback when project is created successfully
   */
  onSuccess?: () => void;

  /**
   * Additional CSS class names
   */
  className?: string;
}

export interface ProjectManagerSettingsModalProps {
  /**
   * The project to edit settings for
   */
  project: Project;

  /**
   * Whether the modal is open (controlled)
   */
  isOpen?: boolean;

  /**
   * Callback when modal is closed
   */
  onClose?: () => void;

  /**
   * Callback when settings are saved
   */
  onSave?: (projectId: string, updates: Partial<Project>) => void | Promise<void>;

  /**
   * Callback when project is deleted from settings
   */
  onDelete?: (projectId: string) => void | Promise<void>;

  /**
   * Additional CSS class names
   */
  className?: string;
}

// ============================================================================
// LOADING AND EMPTY STATES
// ============================================================================

export interface ProjectManagerLoadingProps {
  /**
   * Custom loading message
   */
  message?: string;

  /**
   * Additional CSS class names
   */
  className?: string;
}

export interface ProjectManagerEmptyProps {
  /**
   * Empty state message
   */
  message?: string;

  /**
   * Whether to show create button
   */
  showCreateButton?: boolean;

  /**
   * Callback when create button is clicked
   */
  onCreateClick?: () => void;

  /**
   * Empty state variant
   * @default 'no-projects'
   */
  variant?: 'no-projects' | 'no-results' | 'no-tenant';

  /**
   * Additional CSS class names
   */
  className?: string;
}

// ============================================================================
// ERROR STATE PROPS
// ============================================================================

export interface ProjectManagerErrorProps {
  /**
   * Error message to display
   */
  error?: string | null;

  /**
   * Callback when error is dismissed
   */
  onDismiss?: () => void;

  /**
   * Additional CSS class names
   */
  className?: string;
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
  onProjectSelect?: (project: Project) => void;
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
