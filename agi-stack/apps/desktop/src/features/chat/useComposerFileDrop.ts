import { useCallback, useEffect, useRef, useState } from 'react';
import type { DragEvent } from 'react';

import { composerFileDragActive, composerFileDropAction } from './composerFileDropModel';

type UseComposerFileDropOptions = {
  disabled: boolean;
  supportsUpload: boolean;
  onUploadFiles: (files: File[]) => void | Promise<void>;
  onUnsupported: () => void;
};

export function useComposerFileDrop({
  disabled,
  supportsUpload,
  onUploadFiles,
  onUnsupported,
}: UseComposerFileDropOptions) {
  const [isFileDragging, setIsFileDragging] = useState(false);
  const dragDepthRef = useRef(0);

  useEffect(() => {
    if (!disabled && supportsUpload) return;
    dragDepthRef.current = 0;
    setIsFileDragging(false);
  }, [disabled, supportsUpload]);

  const handleFileDragEnter = useCallback(
    (event: DragEvent<HTMLElement>) => {
      event.preventDefault();
      event.stopPropagation();
      dragDepthRef.current += 1;
      if (
        composerFileDragActive({
          disabled,
          supportsUpload,
          types: Array.from(event.dataTransfer.types),
        })
      ) {
        setIsFileDragging(true);
      }
    },
    [disabled, supportsUpload],
  );

  const handleFileDragOver = useCallback((event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
  }, []);

  const handleFileDragLeave = useCallback((event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setIsFileDragging(false);
  }, []);

  const handleFileDrop = useCallback(
    (event: DragEvent<HTMLElement>) => {
      event.preventDefault();
      event.stopPropagation();
      dragDepthRef.current = 0;
      setIsFileDragging(false);

      const files = Array.from(event.dataTransfer.files);
      const action = composerFileDropAction({
        disabled,
        supportsUpload,
        fileCount: files.length,
      });
      if (action === 'unsupported') {
        onUnsupported();
      } else if (action === 'upload') {
        void onUploadFiles(files);
      }
    },
    [disabled, onUnsupported, onUploadFiles, supportsUpload],
  );

  return {
    isFileDragging,
    handleFileDragEnter,
    handleFileDragOver,
    handleFileDragLeave,
    handleFileDrop,
  };
}
