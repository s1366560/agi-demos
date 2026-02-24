/**
 * ArtifactRenderer Compound Component Types
 *
 * Defines the type system for the compound ArtifactRenderer component.
 */

import type { Artifact } from '../../types/agent';

/**
 * ArtifactRenderer context shared across compound components
 */
export interface ArtifactRendererContextValue {
  /** The artifact to render */
  artifact: Artifact;
  /** Compact mode for inline display */
  compact: boolean;
  /** Maximum width for the rendered content */
  maxWidth: number | string;
  /** Maximum height for the rendered content */
  maxHeight: number | string;
  /** Show metadata information */
  showMeta: boolean;
  /** Loading state */
  loading: boolean;
  /** Error state */
  error: string | null;
  /** Set loading state */
  setLoading: (loading: boolean) => void;
  /** Set error state */
  setError: (error: string | null) => void;
}

/**
 * Props for the root ArtifactRenderer component
 */
export interface ArtifactRendererRootProps {
  /** The artifact to render */
  artifact: Artifact;
  /** Children for compound component pattern */
  children?: React.ReactNode | undefined;
  /** Compact mode for inline display */
  compact?: boolean | undefined;
  /** Maximum width for the rendered content */
  maxWidth?: number | string | undefined;
  /** Maximum height for the rendered content */
  maxHeight?: number | string | undefined;
  /** Called when artifact is clicked for full-screen view */
  onExpand?: ((artifact: Artifact) => void) | undefined;
  /** Show metadata information */
  showMeta?: boolean | undefined;
  /** Custom class name */
  className?: string | undefined;
}

/**
 * Props for Image sub-component
 */
export interface ArtifactImageProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Video sub-component
 */
export interface ArtifactVideoProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Audio sub-component
 */
export interface ArtifactAudioProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Code sub-component
 */
export interface ArtifactCodeProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Document sub-component
 */
export interface ArtifactDocumentProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Download sub-component (for archives and other files)
 */
export interface ArtifactDownloadProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Loading sub-component
 */
export interface ArtifactLoadingProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Error sub-component
 */
export interface ArtifactErrorProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Meta sub-component (metadata footer)
 */
export interface ArtifactMetaProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Header sub-component
 */
export interface ArtifactHeaderProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Props for Actions sub-component (download, expand buttons)
 */
export interface ArtifactActionsProps {
  /** Optional custom class name */
  className?: string | undefined;
}

/**
 * Legacy ArtifactRendererProps for backward compatibility
 * @deprecated Use ArtifactRendererRootProps with compound components instead
 */
export interface LegacyArtifactRendererProps {
  /** The artifact to render */
  artifact: Artifact;
  /** Compact mode for inline display */
  compact?: boolean | undefined;
  /** Maximum width for the rendered content */
  maxWidth?: number | string | undefined;
  /** Maximum height for the rendered content */
  maxHeight?: number | string | undefined;
  /** Called when artifact is clicked for full-screen view */
  onExpand?: ((artifact: Artifact) => void) | undefined;
  /** Show metadata information */
  showMeta?: boolean | undefined;
  /** Custom class name */
  className?: string | undefined;
}
