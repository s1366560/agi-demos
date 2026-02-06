/**
 * AudioPlayer - Audio playback with waveform visualization
 */

import React, { useRef, useState } from 'react';

import { SoundOutlined } from '@ant-design/icons';
import { Space, Typography, Spin, Alert } from 'antd';

const { Text } = Typography;

export interface AudioPlayerProps {
  /** Audio source URL */
  src: string;
  /** Filename for display */
  filename?: string;
  /** Compact mode */
  compact?: boolean;
  /** Called when audio loads */
  onLoad?: () => void;
  /** Called on error */
  onError?: () => void;
}

export const AudioPlayer: React.FC<AudioPlayerProps> = ({
  src,
  filename,
  compact = false,
  onLoad,
  onError,
}) => {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [duration, setDuration] = useState<string>('');

  const handleLoadedMetadata = () => {
    setLoading(false);
    if (audioRef.current) {
      const secs = audioRef.current.duration;
      const mins = Math.floor(secs / 60);
      const remainingSecs = Math.floor(secs % 60);
      setDuration(`${mins}:${remainingSecs.toString().padStart(2, '0')}`);
    }
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
        message="Audio playback error"
        description="Failed to load audio file."
        showIcon
      />
    );
  }

  return (
    <div className="audio-player p-3 bg-gray-50 rounded-lg">
      {loading && (
        <div className="flex items-center justify-center p-4">
          <Spin size="small" />
        </div>
      )}
      <div className={loading ? 'hidden' : ''}>
        <Space direction="vertical" className="w-full">
          {!compact && filename && (
            <Space>
              <SoundOutlined className="text-blue-500" />
              <Text ellipsis style={{ maxWidth: 200 }}>
                {filename}
              </Text>
              {duration && (
                <Text type="secondary" className="text-xs">
                  {duration}
                </Text>
              )}
            </Space>
          )}
          <audio
            ref={audioRef}
            src={src}
            controls
            preload="metadata"
            style={{ width: '100%' }}
            onLoadedMetadata={handleLoadedMetadata}
            onError={handleError}
          >
            Your browser does not support the audio element.
          </audio>
        </Space>
      </div>
    </div>
  );
};

export default AudioPlayer;
