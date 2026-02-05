/**
 * VideoPlayer - Video playback with controls
 */

import React, { useRef, useState } from "react";

import { Spin, Alert } from "antd";

export interface VideoPlayerProps {
  /** Video source URL */
  src: string;
  /** MIME type for format hint */
  mimeType?: string;
  /** Maximum height */
  maxHeight?: number | string;
  /** Compact mode */
  compact?: boolean;
  /** Autoplay (muted by default) */
  autoPlay?: boolean;
  /** Called when video loads */
  onLoad?: () => void;
  /** Called on error */
  onError?: () => void;
}

export const VideoPlayer: React.FC<VideoPlayerProps> = ({
  src,
  mimeType,
  maxHeight = 400,
  compact: _compact = false,
  autoPlay = false,
  onLoad,
  onError,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const handleLoadedData = () => {
    setLoading(false);
    onLoad?.();
  };

  const handleError = () => {
    setLoading(false);
    setError(true);
    onError?.();
  };

  if (error) {
    return (
      <Alert
        type="error"
        message="Video playback error"
        description="Failed to load or play video. Try downloading it instead."
        showIcon
      />
    );
  }

  return (
    <div
      className="video-player relative"
      style={{
        maxHeight: typeof maxHeight === "number" ? maxHeight : undefined,
      }}
    >
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-900/10 z-10">
          <Spin />
        </div>
      )}
      <video
        ref={videoRef}
        src={src}
        controls
        autoPlay={autoPlay}
        muted={autoPlay} // Mute if autoplay to comply with browser policies
        playsInline
        preload="metadata"
        style={{
          maxHeight: typeof maxHeight === "number" ? maxHeight : undefined,
          maxWidth: "100%",
          width: "100%",
          backgroundColor: "#000",
        }}
        onLoadedData={handleLoadedData}
        onError={handleError}
      >
        {mimeType && <source src={src} type={mimeType} />}
        Your browser does not support the video tag.
      </video>
    </div>
  );
};

export default VideoPlayer;
