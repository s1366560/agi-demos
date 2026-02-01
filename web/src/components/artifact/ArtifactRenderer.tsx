/**
 * ArtifactRenderer - Universal renderer for all artifact types
 *
 * Routes artifacts to appropriate viewer components based on category/mime type.
 * Provides a consistent interface for displaying any type of artifact.
 */

import { useState } from "react";
import { Card, Spin, Alert, Typography, Space, Tag, Tooltip, Button } from "antd";
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
} from "@ant-design/icons";

import type { Artifact, ArtifactCategory } from "../../types/agent";
import { ImageViewer } from "./ImageViewer";
import { VideoPlayer } from "./VideoPlayer";
import { AudioPlayer } from "./AudioPlayer";
import { CodeViewer } from "./CodeViewer";
import { FileDownloader } from "./FileDownloader";

const { Text } = Typography;

export interface ArtifactRendererProps {
  /** The artifact to render */
  artifact: Artifact;
  /** Compact mode for inline display */
  compact?: boolean;
  /** Maximum width for the rendered content */
  maxWidth?: number | string;
  /** Maximum height for the rendered content */
  maxHeight?: number | string;
  /** Called when artifact is clicked for full-screen view */
  onExpand?: (artifact: Artifact) => void;
  /** Show metadata information */
  showMeta?: boolean;
  /** Custom class name */
  className?: string;
}

// Category icons
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

// Category colors for tags
const CATEGORY_COLORS: Record<ArtifactCategory, string> = {
  image: "blue",
  video: "purple",
  audio: "cyan",
  document: "orange",
  code: "green",
  data: "gold",
  archive: "magenta",
  other: "default",
};

// Format file size
function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export const ArtifactRenderer: React.FC<ArtifactRendererProps> = ({
  artifact,
  compact = false,
  maxWidth = "100%",
  maxHeight = 400,
  onExpand,
  showMeta = true,
  className,
}) => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Handle loading state
  const handleLoad = () => {
    setLoading(false);
  };

  const handleError = (err: string) => {
    setLoading(false);
    setError(err);
  };

  // Render content based on category
  const renderContent = () => {
    // Show loading for pending/uploading artifacts
    if (artifact.status === "pending" || artifact.status === "uploading") {
      return (
        <div className="flex items-center justify-center p-8">
          <Space direction="vertical" align="center">
            <Spin indicator={<LoadingOutlined style={{ fontSize: 24 }} spin />} />
            <Text type="secondary">
              {artifact.status === "pending" ? "Preparing..." : "Uploading..."}
            </Text>
          </Space>
        </div>
      );
    }

    // Show error state
    if (artifact.status === "error" || error) {
      return (
        <Alert
          type="error"
          message="Failed to load artifact"
          description={artifact.errorMessage || error}
          showIcon
        />
      );
    }

    // Show deleted state
    if (artifact.status === "deleted") {
      return (
        <Alert
          type="warning"
          message="Artifact deleted"
          description="This artifact has been removed."
          showIcon
        />
      );
    }

    // No URL available
    if (!artifact.url) {
      return (
        <Alert
          type="info"
          message="No content available"
          description="Artifact URL is not yet available."
          showIcon
        />
      );
    }

    // Route to appropriate viewer
    switch (artifact.category) {
      case "image":
        return (
          <ImageViewer
            src={artifact.url}
            alt={artifact.filename}
            previewSrc={artifact.previewUrl}
            maxHeight={maxHeight}
            compact={compact}
            onLoad={handleLoad}
            onError={() => handleError("Failed to load image")}
          />
        );

      case "video":
        return (
          <VideoPlayer
            src={artifact.url}
            mimeType={artifact.mimeType}
            maxHeight={maxHeight}
            compact={compact}
            onLoad={handleLoad}
            onError={() => handleError("Failed to load video")}
          />
        );

      case "audio":
        return (
          <AudioPlayer
            src={artifact.url}
            filename={artifact.filename}
            compact={compact}
            onLoad={handleLoad}
            onError={() => handleError("Failed to load audio")}
          />
        );

      case "code":
      case "data":
        return (
          <CodeViewer
            url={artifact.url}
            filename={artifact.filename}
            mimeType={artifact.mimeType}
            maxHeight={maxHeight}
            compact={compact}
            onLoad={handleLoad}
            onError={handleError}
          />
        );

      case "document":
        // For PDFs, try to embed; for others, show download
        if (artifact.mimeType === "application/pdf") {
          return (
            <iframe
              src={artifact.url}
              style={{
                width: "100%",
                height: typeof maxHeight === "number" ? maxHeight : 400,
                border: "none",
              }}
              title={artifact.filename}
              onLoad={handleLoad}
              onError={() => handleError("Failed to load PDF")}
            />
          );
        }
        // For non-PDF documents, fall through to download
        setLoading(false);
        return (
          <FileDownloader
            url={artifact.url}
            filename={artifact.filename}
            mimeType={artifact.mimeType}
            sizeBytes={artifact.sizeBytes}
            compact={compact}
          />
        );

      case "archive":
      case "other":
      default:
        setLoading(false);
        return (
          <FileDownloader
            url={artifact.url}
            filename={artifact.filename}
            mimeType={artifact.mimeType}
            sizeBytes={artifact.sizeBytes}
            compact={compact}
          />
        );
    }
  };

  // Compact mode - minimal UI
  if (compact) {
    return (
      <div
        className={`artifact-renderer artifact-renderer--compact ${className || ""}`}
        style={{ maxWidth }}
      >
        {renderContent()}
      </div>
    );
  }

  // Full mode with card wrapper
  return (
    <Card
      className={`artifact-renderer ${className || ""}`}
      style={{ maxWidth }}
      size="small"
      title={
        <Space>
          {CATEGORY_ICONS[artifact.category]}
          <Text ellipsis style={{ maxWidth: 200 }}>
            {artifact.filename}
          </Text>
          <Tag color={CATEGORY_COLORS[artifact.category]}>
            {artifact.category}
          </Tag>
        </Space>
      }
      extra={
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
                onClick={() => onExpand(artifact)}
              />
            </Tooltip>
          )}
        </Space>
      }
    >
      <div style={{ maxHeight, overflow: "auto" }}>
        {loading && artifact.status === "ready" && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/50 z-10">
            <Spin />
          </div>
        )}
        {renderContent()}
      </div>
      {showMeta && artifact.sourceTool && (
        <div className="mt-2 text-xs text-gray-400">
          Generated by <code>{artifact.sourceTool}</code>
          {artifact.sourcePath && (
            <>
              {" "}from <code>{artifact.sourcePath}</code>
            </>
          )}
        </div>
      )}
    </Card>
  );
};

export default ArtifactRenderer;
