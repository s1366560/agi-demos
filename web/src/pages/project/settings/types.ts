/**
 * ProjectSettings Compound Component Types
 *
 * Type definitions for the ProjectSettings compound component pattern.
 */

import type { Project } from '../../../types';

// ============================================================================
// Settings Data Types
// ============================================================================

export interface BasicSettingsData {
  name: string;
  description: string;
  isPublic: boolean;
}

export interface MemoryRulesData {
  maxEpisodes: number;
  retentionDays: number;
  autoRefresh: boolean;
  refreshInterval: number;
}

export interface GraphConfigData {
  maxNodes: number;
  maxEdges: number;
  similarityThreshold: number;
  communityDetection: boolean;
}

// ============================================================================
// Context State
// ============================================================================

export interface ProjectSettingsState {
  project: Project | null;
  isSaving: boolean;
  message: { type: 'success' | 'error'; text: string } | null;

  // Basic settings
  basicSettings: BasicSettingsData;

  // Memory rules
  memoryRules: MemoryRulesData;

  // Graph config
  graphConfig: GraphConfigData;
}

// ============================================================================
// Context Actions
// ============================================================================

export interface ProjectSettingsActions {
  // Basic settings actions
  setName: (name: string) => void;
  setDescription: (description: string) => void;
  setIsPublic: (isPublic: boolean) => void;
  saveBasicSettings: () => Promise<void>;

  // Memory rules actions
  setMaxEpisodes: (maxEpisodes: number) => void;
  setRetentionDays: (retentionDays: number) => void;
  setAutoRefresh: (autoRefresh: boolean) => void;
  setRefreshInterval: (refreshInterval: number) => void;
  saveMemoryRules: () => Promise<void>;

  // Graph config actions
  setMaxNodes: (maxNodes: number) => void;
  setMaxEdges: (maxEdges: number) => void;
  setSimilarityThreshold: (similarityThreshold: number) => void;
  setCommunityDetection: (communityDetection: boolean) => void;
  saveGraphConfig: () => Promise<void>;

  // Advanced actions
  exportData: () => Promise<void>;
  clearCache: () => Promise<void>;
  rebuildCommunities: () => Promise<void>;

  // Danger zone actions
  deleteProject: () => Promise<void>;

  // Message actions
  clearMessage: () => void;
}

// ============================================================================
// Context Value
// ============================================================================

export interface ProjectSettingsContextValue extends ProjectSettingsState, ProjectSettingsActions {}

// ============================================================================
// Sub-Component Props
// ============================================================================

// Header
export interface ProjectSettingsHeaderProps {
  title: string;
}

// Message Banner
export interface ProjectSettingsMessageProps {
  message: { type: 'success' | 'error'; text: string } | null;
  onClose: () => void;
}

// Basic Settings Section
export interface ProjectSettingsBasicProps {
  data: BasicSettingsData;
  isSaving: boolean;
  onNameChange: (name: string) => void;
  onDescriptionChange: (description: string) => void;
  onIsPublicChange: (isPublic: boolean) => void;
  onSave: () => Promise<void>;
}

// Memory Rules Section
export interface ProjectSettingsMemoryProps {
  data: MemoryRulesData;
  isSaving: boolean;
  onMaxEpisodesChange: (maxEpisodes: number) => void;
  onRetentionDaysChange: (retentionDays: number) => void;
  onAutoRefreshChange: (autoRefresh: boolean) => void;
  onRefreshIntervalChange: (refreshInterval: number) => void;
  onSave: () => Promise<void>;
}

// Graph Config Section
export interface ProjectSettingsGraphProps {
  data: GraphConfigData;
  isSaving: boolean;
  onMaxNodesChange: (maxNodes: number) => void;
  onMaxEdgesChange: (maxEdges: number) => void;
  onSimilarityThresholdChange: (similarityThreshold: number) => void;
  onCommunityDetectionChange: (communityDetection: boolean) => void;
  onSave: () => Promise<void>;
}

// Advanced Section
export interface ProjectSettingsAdvancedProps {
  onExportData: () => Promise<void>;
  onClearCache: () => Promise<void>;
  onRebuildCommunities: () => Promise<void>;
}

// Danger Zone Section
export interface ProjectSettingsDangerProps {
  projectName: string;
  onDelete: () => Promise<void>;
}

// No Project State
export interface ProjectSettingsNoProjectProps {}

// ============================================================================
// Main Component Props
// ============================================================================

export interface ProjectSettingsProps {
  className?: string;
}
