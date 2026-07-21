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

import React, { useState, useCallback, Children, useEffect } from 'react';

import { useTranslation } from 'react-i18next';

import { Card, Spin, Alert, Typography, Space, Tag, Tooltip, Button } from 'antd';
import {
  Image as ImageIcon,
  Video,
  Volume2,
  FileText,
  Code,
  Database,
  Folder,
  FileQuestion,
  Download,
  Maximize2,
  Loader2,
} from 'lucide-react';

import { AudioPlayer } from './AudioPlayer';
import { CodeViewer } from './CodeViewer';
import { FileDownloader } from './FileDownloader';
import { ImageViewer } from './ImageViewer';
import { VideoPlayer } from './VideoPlayer';

import { formatFileSize } from '@/utils/format';

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
  image: <ImageIcon size={16} />,
  video: <Video size={16} />,
  audio: <Volume2 size={16} />,
  document: <FileText size={16} />,
  code: <Code size={16} />,
  data: <Database size={16} />,
  archive: <Folder size={16} />,
  other: <FileQuestion size={16} />,
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

function markComponent<P>(component: React.FC<P>, marker: symbol, displayName: string): void {
  const marked = component as React.FC<P> &
    Record<symbol, unknown> & {
      displayName?: string | undefined;
    };
  marked[marker] = true;
  marked.displayName = displayName;
}

function hasMarker<P>(child: React.ReactNode, marker: symbol): child is React.ReactElement<P> {
  if (!React.isValidElement(child)) {
    return false;
  }

  const elementType = child.type as unknown;
  if (
    typeof elementType !== 'function' &&
    (typeof elementType !== 'object' || elementType === null)
  ) {
    return false;
  }

  return (elementType as Record<symbol, unknown>)[marker] === true;
}

// ========================================
// Sub-Components (Marker Components)
// ========================================

ArtifactRenderer.Image = function ArtifactRendererImageMarker(_props: ArtifactImageProps) {
  return null;
};
markComponent(ArtifactRenderer.Image, IMAGE_SYMBOL, 'ArtifactRendererImage');

ArtifactRenderer.Video = function ArtifactRendererVideoMarker(_props: ArtifactVideoProps) {
  return null;
};
markComponent(ArtifactRenderer.Video, VIDEO_SYMBOL, 'ArtifactRendererVideo');

ArtifactRenderer.Audio = function ArtifactRendererAudioMarker(_props: ArtifactAudioProps) {
  return null;
};
markComponent(ArtifactRenderer.Audio, AUDIO_SYMBOL, 'ArtifactRendererAudio');

ArtifactRenderer.Code = function ArtifactRendererCodeMarker(_props: ArtifactCodeProps) {
  return null;
};
markComponent(ArtifactRenderer.Code, CODE_SYMBOL, 'ArtifactRendererCode');

ArtifactRenderer.Document = function ArtifactRendererDocumentMarker(_props: ArtifactDocumentProps) {
  return null;
};
markComponent(ArtifactRenderer.Document, DOCUMENT_SYMBOL, 'ArtifactRendererDocument');

ArtifactRenderer.Download = function ArtifactRendererDownloadMarker(_props: ArtifactDownloadProps) {
  return null;
};
markComponent(ArtifactRenderer.Download, DOWNLOAD_SYMBOL, 'ArtifactRendererDownload');

ArtifactRenderer.Loading = function ArtifactRendererLoadingMarker(_props: ArtifactLoadingProps) {
  return null;
};
markComponent(ArtifactRenderer.Loading, LOADING_SYMBOL, 'ArtifactRendererLoading');

ArtifactRenderer.Error = function ArtifactRendererErrorMarker(_props: ArtifactErrorProps) {
  return null;
};
markComponent(ArtifactRenderer.Error, ERROR_SYMBOL, 'ArtifactRendererError');

ArtifactRenderer.Meta = function ArtifactRendererMetaMarker(_props: ArtifactMetaProps) {
  return null;
};
markComponent(ArtifactRenderer.Meta, META_SYMBOL, 'ArtifactRendererMeta');

ArtifactRenderer.Header = function ArtifactRendererHeaderMarker(_props: ArtifactHeaderProps) {
  return null;
};
markComponent(ArtifactRenderer.Header, HEADER_SYMBOL, 'ArtifactRendererHeader');

ArtifactRenderer.Actions = function ArtifactRendererActionsMarker(_props: ArtifactActionsProps) {
  return null;
};
markComponent(ArtifactRenderer.Actions, ACTIONS_SYMBOL, 'ArtifactRendererActions');

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
  const { t } = useTranslation();

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
        onError(
          t('components.artifactRenderer.loadImageFailed', { defaultValue: 'Failed to load image' })
        );
      }}
    />
  );
}

function VideoContent({ artifact, maxHeight, compact, onLoad, onError }: ContentRendererProps) {
  const { t } = useTranslation();

  if (!artifact.url) return null;
  return (
    <VideoPlayer
      src={artifact.url}
      mimeType={artifact.mimeType}
      maxHeight={maxHeight}
      compact={compact}
      onLoad={onLoad}
      onError={() => {
        onError(
          t('components.artifactRenderer.loadVideoFailed', { defaultValue: 'Failed to load video' })
        );
      }}
    />
  );
}

function AudioContent({ artifact, compact, onLoad, onError }: ContentRendererProps) {
  const { t } = useTranslation();

  if (!artifact.url) return null;
  return (
    <AudioPlayer
      src={artifact.url}
      filename={artifact.filename}
      compact={compact}
      onLoad={onLoad}
      onError={() => {
        onError(
          t('components.artifactRenderer.loadAudioFailed', { defaultValue: 'Failed to load audio' })
        );
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

function DocumentContent({ artifact, maxHeight, onLoad, onError }: ContentRendererProps) {
  const { t } = useTranslation();

  useEffect(() => {
    if (artifact.url && artifact.mimeType !== 'application/pdf') {
      onLoad();
    }
  }, [artifact.mimeType, artifact.url, onLoad]);

  if (!artifact.url) return null;
  // For PDFs, try to embed
  if (artifact.mimeType === 'application/pdf') {
    return (
      <iframe
        src={artifact.url}
        style={{
          width: '100%',
          height: maxHeight,
          border: 'none',
        }}
        title={artifact.filename}
        onLoad={onLoad}
        onError={() => {
          onError(
            t('components.artifactRenderer.loadPdfFailed', { defaultValue: 'Failed to load PDF' })
          );
        }}
      />
    );
  }
  // For non-PDF documents, show download
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
  const { t } = useTranslation();

  return (
    <div className="flex items-center justify-center p-8">
      <Space orientation="vertical">
        <Spin indicator={<Loader2 className="animate-spin" size={24} />} />
        <Text type="secondary">
          {artifact.status === 'pending'
            ? t('components.artifactRenderer.preparing', { defaultValue: 'Preparing...' })
            : t('components.artifactRenderer.uploading', { defaultValue: 'Uploading...' })}
        </Text>
      </Space>
    </div>
  );
}

function ErrorContent({ artifact, error }: { artifact: Artifact; error: string | null }) {
  const { t } = useTranslation();

  return (
    <Alert
      type="error"
      title={t('components.artifactRenderer.loadFailed', {
        defaultValue: 'Failed to load artifact',
      })}
      description={artifact.errorMessage || error}
      showIcon
    />
  );
}

function DeletedContent() {
  const { t } = useTranslation();

  return (
    <Alert
      type="warning"
      title={t('components.artifactRenderer.deletedTitle', { defaultValue: 'Artifact deleted' })}
      description={t('components.artifactRenderer.deletedDescription', {
        defaultValue: 'This artifact has been removed.',
      })}
      showIcon
    />
  );
}

function NoUrlContent() {
  const { t } = useTranslation();

  return (
    <Alert
      type="info"
      title={t('components.artifactRenderer.noContentTitle', {
        defaultValue: 'No content available',
      })}
      description={t('components.artifactRenderer.noContentDescription', {
        defaultValue: 'Artifact URL is not yet available.',
      })}
      showIcon
    />
  );
}

// ========================================
// Main Component
// ========================================

export function ArtifactRenderer(props: ArtifactRendererRootProps) {
  const { t } = useTranslation();
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
  const imageChild = childrenArray.find((child): child is React.ReactElement<ArtifactImageProps> =>
    hasMarker<ArtifactImageProps>(child, IMAGE_SYMBOL)
  );
  const videoChild = childrenArray.find((child): child is React.ReactElement<ArtifactVideoProps> =>
    hasMarker<ArtifactVideoProps>(child, VIDEO_SYMBOL)
  );
  const audioChild = childrenArray.find((child): child is React.ReactElement<ArtifactAudioProps> =>
    hasMarker<ArtifactAudioProps>(child, AUDIO_SYMBOL)
  );
  const codeChild = childrenArray.find((child): child is React.ReactElement<ArtifactCodeProps> =>
    hasMarker<ArtifactCodeProps>(child, CODE_SYMBOL)
  );
  const documentChild = childrenArray.find(
    (child): child is React.ReactElement<ArtifactDocumentProps> =>
      hasMarker<ArtifactDocumentProps>(child, DOCUMENT_SYMBOL)
  );
  const downloadChild = childrenArray.find(
    (child): child is React.ReactElement<ArtifactDownloadProps> =>
      hasMarker<ArtifactDownloadProps>(child, DOWNLOAD_SYMBOL)
  );
  const loadingChild = childrenArray.find(
    (child): child is React.ReactElement<ArtifactLoadingProps> =>
      hasMarker<ArtifactLoadingProps>(child, LOADING_SYMBOL)
  );
  const errorChild = childrenArray.find((child): child is React.ReactElement<ArtifactErrorProps> =>
    hasMarker<ArtifactErrorProps>(child, ERROR_SYMBOL)
  );
  const metaChild = childrenArray.find((child): child is React.ReactElement<ArtifactMetaProps> =>
    hasMarker<ArtifactMetaProps>(child, META_SYMBOL)
  );
  const headerChild = childrenArray.find(
    (child): child is React.ReactElement<ArtifactHeaderProps> =>
      hasMarker<ArtifactHeaderProps>(child, HEADER_SYMBOL)
  );
  const actionsChild = childrenArray.find(
    (child): child is React.ReactElement<ArtifactActionsProps> =>
      hasMarker<ArtifactActionsProps>(child, ACTIONS_SYMBOL)
  );

  // Determine if using compound mode
  const hasSubComponents = Boolean(
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
    actionsChild
  );

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
              <Tooltip
                title={t('components.artifactRenderer.download', { defaultValue: 'Download' })}
              >
                <Button
                  type="text"
                  size="small"
                  icon={<Download size={14} />}
                  href={artifact.url}
                  target="_blank"
                  rel="noopener noreferrer"
                />
              </Tooltip>
            )}
            {onExpand && (
              <Tooltip title={t('components.artifactRenderer.expand', { defaultValue: 'Expand' })}>
                <Button
                  type="text"
                  size="small"
                  icon={<Maximize2 size={14} />}
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
          {t('components.artifactRenderer.generatedBy', { defaultValue: 'Generated by' })}{' '}
          <code>{artifact.sourceTool}</code>
          {artifact.sourcePath && (
            <>
              {' '}
              {t('components.artifactRenderer.generatedFrom', { defaultValue: 'from' })}{' '}
              <code>{artifact.sourcePath}</code>
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
