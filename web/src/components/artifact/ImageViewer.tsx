/**
 * ImageViewer - Display images with zoom and preview capabilities
 */

import React, { useState } from "react";

import { Image, Spin } from "antd";

export interface ImageViewerProps {
  /** Image source URL */
  src: string;
  /** Alt text for accessibility */
  alt?: string;
  /** Preview/thumbnail URL (optional) */
  previewSrc?: string;
  /** Maximum height */
  maxHeight?: number | string;
  /** Compact mode */
  compact?: boolean;
  /** Called when image loads */
  onLoad?: () => void;
  /** Called on error */
  onError?: () => void;
}

export const ImageViewer: React.FC<ImageViewerProps> = ({
  src,
  alt = "Artifact image",
  previewSrc,
  maxHeight = 400,
  compact: _compact = false,
  onLoad,
  onError,
}) => {
  const [loading, setLoading] = useState(true);

  const handleLoad = () => {
    setLoading(false);
    onLoad?.();
  };

  const handleError = () => {
    setLoading(false);
    onError?.();
  };

  return (
    <div
      className="image-viewer relative"
      style={{
        maxHeight: typeof maxHeight === "number" ? maxHeight : undefined,
        overflow: "hidden",
      }}
    >
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-50">
          <Spin />
        </div>
      )}
      <Image
        src={src}
        alt={alt}
        preview={{
          src: src, // Full resolution for preview
        }}
        placeholder={
          previewSrc ? (
            <Image src={previewSrc} preview={false} alt="Loading..." />
          ) : (
            <div className="flex items-center justify-center h-32 bg-gray-100">
              <Spin />
            </div>
          )
        }
        style={{
          maxHeight: typeof maxHeight === "number" ? maxHeight : undefined,
          maxWidth: "100%",
          objectFit: "contain",
          display: loading ? "none" : "block",
        }}
        onLoad={handleLoad}
        onError={handleError}
      />
    </div>
  );
};

export default ImageViewer;
