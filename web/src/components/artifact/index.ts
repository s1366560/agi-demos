/**
 * Artifact Components - Rich output display for sandbox/MCP tool artifacts
 *
 * ## Usage
 *
 * ### Compound Components (Recommended)
 * ```tsx
 * <ArtifactRenderer artifact={artifact}>
 *   <ArtifactRenderer.Image />
 *   <ArtifactRenderer.Meta />
 * </ArtifactRenderer>
 * ```
 *
 * ### Convenience Usage
 * ```tsx
 * <ArtifactRenderer artifact={artifact} />
 * ```
 *
 * ## Available Components
 * - Images with preview and zoom
 * - Videos with player controls
 * - Audio with player
 * - Code with syntax highlighting
 * - Documents with download
 * - Data files (JSON, CSV) with formatting
 */

export { ArtifactRenderer } from './ArtifactRenderer';
export type {
  ArtifactRendererRootProps,
  ArtifactImageProps,
  ArtifactVideoProps,
  ArtifactAudioProps,
  ArtifactCodeProps,
  ArtifactDocumentProps,
  ArtifactDownloadProps,
  ArtifactLoadingProps,
  ArtifactErrorProps,
  ArtifactMetaProps,
  ArtifactHeaderProps,
  ArtifactActionsProps,
  LegacyArtifactRendererProps as ArtifactRendererProps,
} from './types';

export { ImageViewer } from './ImageViewer';
export type { ImageViewerProps } from './ImageViewer';

export { VideoPlayer } from './VideoPlayer';
export type { VideoPlayerProps } from './VideoPlayer';

export { AudioPlayer } from './AudioPlayer';
export type { AudioPlayerProps } from './AudioPlayer';

export { CodeViewer } from './CodeViewer';
export type { CodeViewerProps } from './CodeViewer';

export { FileDownloader } from './FileDownloader';
export type { FileDownloaderProps } from './FileDownloader';

export { ArtifactGallery } from './ArtifactGallery';
export type { ArtifactGalleryProps } from './ArtifactGallery';
