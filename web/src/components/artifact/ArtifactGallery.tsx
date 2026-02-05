/**
 * ArtifactGallery - Grid display for multiple artifacts
 *
 * Shows artifacts in a responsive grid with previews and expand capability.
 */

import React, { useState } from "react";

import {
  AppstoreOutlined,
  BarsOutlined,
  FileImageOutlined,
  VideoCameraOutlined,
  SoundOutlined,
  FileTextOutlined,
  FileOutlined,
} from "@ant-design/icons";
import { Modal, Empty, Typography, Space, Tag, Segmented } from "antd";

import { ArtifactRenderer } from "./ArtifactRenderer";

import type { Artifact, ArtifactCategory } from "../../types/agent";

const { Text } = Typography;

export interface ArtifactGalleryProps {
  /** List of artifacts to display */
  artifacts: Artifact[];
  /** Title for the gallery */
  title?: string;
  /** Initial view mode */
  viewMode?: "grid" | "list";
  /** Filter by category */
  categoryFilter?: ArtifactCategory[];
  /** Maximum items to show (with "show more" option) */
  maxItems?: number;
  /** Grid column count */
  columns?: number;
  /** Custom class name */
  className?: string;
}

// Category icons
const CATEGORY_ICONS: Record<ArtifactCategory, React.ReactNode> = {
  image: <FileImageOutlined />,
  video: <VideoCameraOutlined />,
  audio: <SoundOutlined />,
  document: <FileTextOutlined />,
  code: <FileTextOutlined />,
  data: <FileTextOutlined />,
  archive: <FileOutlined />,
  other: <FileOutlined />,
};

export const ArtifactGallery: React.FC<ArtifactGalleryProps> = ({
  artifacts,
  title,
  viewMode: initialViewMode = "grid",
  categoryFilter,
  maxItems,
  columns = 3,
  className,
}) => {
  const [viewMode, setViewMode] = useState(initialViewMode);
  const [expandedArtifact, setExpandedArtifact] = useState<Artifact | null>(null);
  const [showAll, setShowAll] = useState(false);

  // Filter artifacts by category if specified
  const filteredArtifacts = categoryFilter
    ? artifacts.filter((a) => categoryFilter.includes(a.category))
    : artifacts;

  // Limit displayed items if maxItems is set
  const displayedArtifacts =
    maxItems && !showAll
      ? filteredArtifacts.slice(0, maxItems)
      : filteredArtifacts;

  const hasMore = maxItems && filteredArtifacts.length > maxItems;

  if (artifacts.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="No artifacts"
        className={className}
      />
    );
  }

  // Group by category for summary
  const categoryCounts = artifacts.reduce(
    (acc, a) => {
      acc[a.category] = (acc[a.category] || 0) + 1;
      return acc;
    },
    {} as Record<ArtifactCategory, number>
  );

  return (
    <div className={`artifact-gallery ${className || ""}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <Space>
          {title && <Text strong>{title}</Text>}
          <Text type="secondary" className="text-xs">
            {filteredArtifacts.length} artifacts
          </Text>
          {/* Category summary tags */}
          {Object.entries(categoryCounts).map(([category, count]) => (
            <Tag key={category} icon={CATEGORY_ICONS[category as ArtifactCategory]}>
              {count}
            </Tag>
          ))}
        </Space>
        <Segmented
          size="small"
          options={[
            { value: "grid", icon: <AppstoreOutlined /> },
            { value: "list", icon: <BarsOutlined /> },
          ]}
          value={viewMode}
          onChange={(value) => setViewMode(value as "grid" | "list")}
        />
      </div>

      {/* Artifacts */}
      {viewMode === "grid" ? (
        <div
          className="grid gap-4"
          style={{
            gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
          }}
        >
          {displayedArtifacts.map((artifact) => (
            <ArtifactRenderer
              key={artifact.id}
              artifact={artifact}
              compact
              maxHeight={200}
              onExpand={setExpandedArtifact}
            />
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {displayedArtifacts.map((artifact) => (
            <ArtifactRenderer
              key={artifact.id}
              artifact={artifact}
              maxHeight={300}
              onExpand={setExpandedArtifact}
            />
          ))}
        </div>
      )}

      {/* Show more button */}
      {hasMore && !showAll && (
        <div className="text-center mt-4">
          <a onClick={() => setShowAll(true)} className="text-blue-500 hover:underline">
            Show {filteredArtifacts.length - maxItems} more artifacts
          </a>
        </div>
      )}

      {/* Expanded artifact modal */}
      <Modal
        open={!!expandedArtifact}
        onCancel={() => setExpandedArtifact(null)}
        footer={null}
        width="80%"
        style={{ top: 20 }}
        destroyOnClose
      >
        {expandedArtifact && (
          <ArtifactRenderer
            artifact={expandedArtifact}
            maxHeight="70vh"
            showMeta
          />
        )}
      </Modal>
    </div>
  );
};

export default ArtifactGallery;
