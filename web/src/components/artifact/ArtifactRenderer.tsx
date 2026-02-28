/**
 * ArtifactRenderer - Compound Component for Artifact Display
 *
 * ## Usage
 *
 * ### Convenience Usage (Default rendering)
 * ```tsx
 * <ArtifactRenderer artifact={artifact} />
 * ```
 *
 * ### Compound Components (Custom rendering)
 * ```tsx
 * <ArtifactRenderer artifact={artifact}>
 *   <ArtifactRenderer.Image />
 *   <ArtifactRenderer.Meta />
 * </ArtifactRenderer>
 * ```
 *
 * ### Namespace Usage
 * ```tsx
 * <ArtifactRenderer.Root artifact={artifact}>
 *   <ArtifactRenderer.Video />
 *   <ArtifactRenderer.Actions />
 * </ArtifactRenderer.Root>
 * ```
 */

import { useState, useCallback, Children } from 'react';

import {
  FileImageOutlined,
  VideoCameraOutlined,
  SoundOutlined,
  FileTextOutlined,
  CodeOutlined,
  DatabaseOutlined,
  FolderOutlined,
  FileUnknownOutlined,
  DownloadOutlined,
  ExpandOutlined,
  LoadingOutlined,
} from '@ant-design/icons';
import { Card, Spin, Alert, Typography, Space, Tag, Tooltip, Button } from 'antd';

import { AudioPlayer } from './AudioPlayer';
import { CodeViewer } from './CodeViewer';
import { FileDownloader } from './FileDownloader';
import { ImageViewer } from './ImageViewer';
import { VideoPlayer } from './VideoPlayer';

import type {
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
} from './types';
import type { Artifact, ArtifactCategory } from '../../types/agent';

const { Text } = Typography;

// ========================================
// Marker Symbols for Sub-Components
// ========================================

const IMAGE_SYMBOL = Symbol('ArtifactRendererImage');
const VIDEO_SYMBOL = Symbol('ArtifactRendererVideo');
const AUDIO_SYMBOL = Symbol('ArtifactRendererAudio');
const CODE_SYMBOL = Symbol('ArtifactRendererCode');
const DOCUMENT_SYMBOL = Symbol('ArtifactRendererDocument');
const DOWNLOAD_SYMBOL = Symbol('ArtifactRendererDownload');
const LOADING_SYMBOL = Symbol('ArtifactRendererLoading');
const ERROR_SYMBOL = Symbol('ArtifactRendererError');
const META_SYMBOL = Symbol('ArtifactRendererMeta');
const HEADER_SYMBOL = Symbol('ArtifactRendererHeader');
const ACTIONS_SYMBOL = Symbol('ArtifactRendererActions');

// ========================================
// Category Icons and Colors
// ========================================

const CATEGORY_ICONS: Record<ArtifactCategory, React.ReactNode> = {
  image: <FileImageOutlined />,
  video: <VideoCameraOutlined />,
  audio: <SoundOutlined />,
  document: <FileTextOutlined />,
  code: <CodeOutlined />,
  data: <DatabaseOutlined />,
  archive: <FolderOutlined />,
  other: <FileUnknownOutlined />,
};

const CATEGORY_COLORS: Record<ArtifactCategory, string> = {
  image: 'blue',
  video: 'purple',
  audio: 'cyan',
  document: 'orange',
  code: 'green',
  data: 'gold',
  archive: 'magenta',
  other: 'default',
};

// ========================================
// Utility Functions
// ========================================

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

// ========================================
// Sub-Components (Marker Components)
// ========================================

ArtifactRenderer.Image = function ArtifactRendererImageMarker(_props: ArtifactImageProps) {
  return null;
};
(ArtifactRenderer.Image as any)[IMAGE_SYMBOL] = true;

ArtifactRenderer.Video = function ArtifactRendererVideoMarker(_props: ArtifactVideoProps) {
  return null;
};
(ArtifactRenderer.Video as any)[VIDEO_SYMBOL] = true;

ArtifactRenderer.Audio = function ArtifactRendererAudioMarker(_props: ArtifactAudioProps) {
  return null;
};
(ArtifactRenderer.Audio as any)[AUDIO_SYMBOL] = true;

ArtifactRenderer.Code = function ArtifactRendererCodeMarker(_props: ArtifactCodeProps) {
  return null;
};
(ArtifactRenderer.Code as any)[CODE_SYMBOL] = true;

ArtifactRenderer.Document = function ArtifactRendererDocumentMarker(_props: ArtifactDocumentProps) {
  return null;
};
(ArtifactRenderer.Document as any)[DOCUMENT_SYMBOL] = true;

ArtifactRenderer.Download = function ArtifactRendererDownloadMarker(_props: ArtifactDownloadProps) {
  return null;
};
(ArtifactRenderer.Download as any)[DOWNLOAD_SYMBOL] = true;

ArtifactRenderer.Loading = function ArtifactRendererLoadingMarker(_props: ArtifactLoadingProps) {
  return null;
};
(ArtifactRenderer.Loading as any)[LOADING_SYMBOL] = true;

ArtifactRenderer.Error = function ArtifactRendererErrorMarker(_props: ArtifactErrorProps) {
  return null;
};
(ArtifactRenderer.Error as any)[ERROR_SYMBOL] = true;

ArtifactRenderer.Meta = function ArtifactRendererMetaMarker(_props: ArtifactMetaProps) {
  return null;
};
(ArtifactRenderer.Meta as any)[META_SYMBOL] = true;

ArtifactRenderer.Header = function ArtifactRendererHeaderMarker(_props: ArtifactHeaderProps) {
  return null;
};
(ArtifactRenderer.Header as any)[HEADER_SYMBOL] = true;

ArtifactRenderer.Actions = function ArtifactRendererActionsMarker(_props: ArtifactActionsProps) {
  return null;
};
(ArtifactRenderer.Actions as any)[ACTIONS_SYMBOL] = true;

// Set display names for testing
(ArtifactRenderer.Image as any).displayName = 'ArtifactRendererImage';
(ArtifactRenderer.Video as any).displayName = 'ArtifactRendererVideo';
(ArtifactRenderer.Audio as any).displayName = 'ArtifactRendererAudio';
(ArtifactRenderer.Code as any).displayName = 'ArtifactRendererCode';
(ArtifactRenderer.Document as any).displayName = 'ArtifactRendererDocument';
(ArtifactRenderer.Download as any).displayName = 'ArtifactRendererDownload';
(ArtifactRenderer.Loading as any).displayName = 'ArtifactRendererLoading';
(ArtifactRenderer.Error as any).displayName = 'ArtifactRendererError';
(ArtifactRenderer.Meta as any).displayName = 'ArtifactRendererMeta';
(ArtifactRenderer.Header as any).displayName = 'ArtifactRendererHeader';
(ArtifactRenderer.Actions as any).displayName = 'ArtifactRendererActions';

// ========================================
// Content Renderers
// ========================================

interface ContentRendererProps {
  artifact: Artifact;
  maxHeight: number | string;
  compact: boolean;
  onLoad: () => void;
  onError: (error: string) => void;
}

function ImageContent({ artifact, maxHeight, compact, onLoad, onError }: ContentRendererProps) {
  if (!artifact.url) return null;
  return (
    <ImageViewer
      src={artifact.url}
      alt={artifact.filename}
      previewSrc={artifact.previewUrl}
      maxHeight={maxHeight}
      compact={compact}
      onLoad={onLoad}
      onError={() => {
        onError('Failed to load image');
      }}
    />
  );
}

function VideoContent({ artifact, maxHeight, compact, onLoad, onError }: ContentRendererProps) {
  if (!artifact.url) return null;
  return (
    <VideoPlayer
      src={artifact.url}
      mimeType={artifact.mimeType}
      maxHeight={maxHeight}
      compact={compact}
      onLoad={onLoad}
      onError={() => {
        onError('Failed to load video');
      }}
    />
  );
}

function AudioContent({ artifact, compact, onLoad, onError }: ContentRendererProps) {
  if (!artifact.url) return null;
  return (
    <AudioPlayer
      src={artifact.url}
      filename={artifact.filename}
      compact={compact}
      onLoad={onLoad}
      onError={() => {
        onError('Failed to load audio');
      }}
    />
  );
}

function CodeContent({ artifact, maxHeight, compact, onLoad, onError }: ContentRendererProps) {
  if (!artifact.url) return null;
  return (
    <CodeViewer
      url={artifact.url}
      filename={artifact.filename}
      mimeType={artifact.mimeType}
      maxHeight={maxHeight}
      compact={compact}
      onLoad={onLoad}
      onError={onError}
    />
  );
}

function DocumentContent({ artifact, onLoad, onError }: ContentRendererProps) {
  if (!artifact.url) return null;
  // For PDFs, try to embed
  if (artifact.mimeType === 'application/pdf') {
    return (
      <iframe
        src={artifact.url}
        style={{
          width: '100%',
          height: typeof onError === 'number' ? onError : 400,
          border: 'none',
        }}
        title={artifact.filename}
        onLoad={onLoad}
        onError={() => {
          onError('Failed to load PDF');
        }}
      />
    );
  }
  // For non-PDF documents, show download
  onLoad();
  return (
    <FileDownloader
      url={artifact.url}
      filename={artifact.filename}
      mimeType={artifact.mimeType}
      sizeBytes={artifact.sizeBytes}
      compact={false}
    />
  );
}

function DownloadContent({ artifact }: ContentRendererProps) {
  if (!artifact.url) return null;
  return (
    <FileDownloader
      url={artifact.url}
      filename={artifact.filename}
      mimeType={artifact.mimeType}
      sizeBytes={artifact.sizeBytes}
      compact={false}
    />
  );
}

function LoadingContent({ artifact }: { artifact: Artifact }) {
  return (
    <div className="flex items-center justify-center p-8">
      <Space orientation="vertical">
        <Spin indicator={<LoadingOutlined style={{ fontSize: 24 }} spin />} />
        <Text type="secondary">
          {artifact.status === 'pending' ? 'Preparing...' : 'Uploading...'}
        </Text>
      </Space>
    </div>
  );
}

function ErrorContent({ artifact, error }: { artifact: Artifact; error: string | null }) {
  return (
    <Alert
      type="error"
      message="Failed to load artifact"
      description={artifact.errorMessage || error}
      showIcon
    />
  );
}

function DeletedContent() {
  return (
    <Alert
      type="warning"
      message="Artifact deleted"
      description="This artifact has been removed."
      showIcon
    />
  );
}

function NoUrlContent() {
  return (
    <Alert
      type="info"
      message="No content available"
      description="Artifact URL is not yet available."
      showIcon
    />
  );
}

// ========================================
// Main Component
// ========================================

export function ArtifactRenderer(props: ArtifactRendererRootProps) {
  const {
    artifact,
    compact = false,
    maxWidth = '100%',
    maxHeight = 400,
    onExpand,
    showMeta = true,
    className,
    children,
  } = props;

  // Internal state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Handlers
  const handleLoad = useCallback(() => {
    setLoading(false);
  }, []);

  const handleError = useCallback((err: string) => {
    setLoading(false);
    setError(err);
  }, []);

  // Parse children to detect sub-components
  const childrenArray = Children.toArray(children);
  const imageChild = childrenArray.find((child: any) => child?.type?.[IMAGE_SYMBOL]) as any;
  const videoChild = childrenArray.find((child: any) => child?.type?.[VIDEO_SYMBOL]) as any;
  const audioChild = childrenArray.find((child: any) => child?.type?.[AUDIO_SYMBOL]) as any;
  const codeChild = childrenArray.find((child: any) => child?.type?.[CODE_SYMBOL]) as any;
  const documentChild = childrenArray.find((child: any) => child?.type?.[DOCUMENT_SYMBOL]) as any;
  const downloadChild = childrenArray.find((child: any) => child?.type?.[DOWNLOAD_SYMBOL]) as any;
  const loadingChild = childrenArray.find((child: any) => child?.type?.[LOADING_SYMBOL]) as any;
  const errorChild = childrenArray.find((child: any) => child?.type?.[ERROR_SYMBOL]) as any;
  const metaChild = childrenArray.find((child: any) => child?.type?.[META_SYMBOL]) as any;
  const headerChild = childrenArray.find((child: any) => child?.type?.[HEADER_SYMBOL]) as any;
  const actionsChild = childrenArray.find((child: any) => child?.type?.[ACTIONS_SYMBOL]) as any;

  // Determine if using compound mode
  const hasSubComponents =
    imageChild ||
    videoChild ||
    audioChild ||
    codeChild ||
    documentChild ||
    downloadChild ||
    loadingChild ||
    errorChild ||
    metaChild ||
    headerChild ||
    actionsChild;

  // In legacy mode, include default renderers
  const includeDefaultRenderer = !hasSubComponents;

  // Render content based on artifact category
  const renderArtifactContent = () => {
    // Pending/uploading state
    if (artifact.status === 'pending' || artifact.status === 'uploading') {
      return <LoadingContent artifact={artifact} />;
    }

    // Error state
    if (artifact.status === 'error' || error) {
      return <ErrorContent artifact={artifact} error={error} />;
    }

    // Deleted state
    if (artifact.status === 'deleted') {
      return <DeletedContent />;
    }

    // No URL available
    if (!artifact.url) {
      return <NoUrlContent />;
    }

    // Route to appropriate viewer based on category
    switch (artifact.category) {
      case 'image':
        return imageChild || includeDefaultRenderer ? (
          <ImageContent
            artifact={artifact}
            maxHeight={maxHeight}
            compact={compact}
            onLoad={handleLoad}
            onError={handleError}
          />
        ) : null;

      case 'video':
        return videoChild || includeDefaultRenderer ? (
          <VideoContent
            artifact={artifact}
            maxHeight={maxHeight}
            compact={compact}
            onLoad={handleLoad}
            onError={handleError}
          />
        ) : null;

      case 'audio':
        return audioChild || includeDefaultRenderer ? (
          <AudioContent
            artifact={artifact}
            maxHeight={maxHeight}
            compact={compact}
            onLoad={handleLoad}
            onError={handleError}
          />
        ) : null;

      case 'code':
      case 'data':
        return codeChild || includeDefaultRenderer ? (
          <CodeContent
            artifact={artifact}
            maxHeight={maxHeight}
            compact={compact}
            onLoad={handleLoad}
            onError={handleError}
          />
        ) : null;

      case 'document':
        return documentChild || includeDefaultRenderer ? (
          <DocumentContent
            artifact={artifact}
            maxHeight={maxHeight}
            compact={compact}
            onLoad={handleLoad}
            onError={handleError}
          />
        ) : null;

      case 'archive':
      case 'other':
      default:
        return downloadChild || includeDefaultRenderer ? (
          <DownloadContent
            artifact={artifact}
            maxHeight={maxHeight}
            compact={compact}
            onLoad={handleLoad}
            onError={handleError}
          />
        ) : null;
    }
  };

  // Compact mode - minimal UI
  if (compact) {
    return (
      <div
        className={`artifact-renderer artifact-renderer--compact ${className || ''}`}
        style={{ maxWidth }}
      >
        {renderArtifactContent()}
      </div>
    );
  }

  // Full mode with card wrapper
  const content = renderArtifactContent();

  if (!content) {
    return null;
  }

  return (
    <Card
      className={`artifact-renderer ${className || ''}`}
      style={{ maxWidth }}
      size="small"
      title={
        !headerChild && (
          <Space>
            {CATEGORY_ICONS[artifact.category]}
            <Text ellipsis style={{ maxWidth: 200 }}>
              {artifact.filename}
            </Text>
            <Tag color={CATEGORY_COLORS[artifact.category]}>{artifact.category}</Tag>
          </Space>
        )
      }
      extra={
        !actionsChild && (
          <Space>
            {showMeta && (
              <Text type="secondary" className="text-xs">
                {formatFileSize(artifact.sizeBytes)}
              </Text>
            )}
            {artifact.url && (
              <Tooltip title="Download">
                <Button
                  type="text"
                  size="small"
                  icon={<DownloadOutlined />}
                  href={artifact.url}
                  target="_blank"
                  rel="noopener noreferrer"
                />
              </Tooltip>
            )}
            {onExpand && (
              <Tooltip title="Expand">
                <Button
                  type="text"
                  size="small"
                  icon={<ExpandOutlined />}
                  onClick={() => {
                    onExpand(artifact);
                  }}
                />
              </Tooltip>
            )}
          </Space>
        )
      }
    >
      <div style={{ maxHeight, overflow: 'auto' }}>
        {loading && artifact.status === 'ready' && !error && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/50 z-10">
            <Spin />
          </div>
        )}
        {content}
      </div>
      {metaChild && showMeta && artifact.sourceTool && (
        <div className="mt-2 text-xs text-gray-400">
          Generated by <code>{artifact.sourceTool}</code>
          {artifact.sourcePath && (
            <>
              {' '}
              from <code>{artifact.sourcePath}</code>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

// Export Root alias
ArtifactRenderer.Root = ArtifactRenderer;

// Set display name
ArtifactRenderer.displayName = 'ArtifactRenderer';

export default ArtifactRenderer;
