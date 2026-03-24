import { useState, useCallback, useRef } from 'react';

interface UseDragAndDropParams {
  disabled?: boolean;
  supportsAttachment: boolean;
  addFiles: (files: FileList) => void;
}

interface UseDragAndDropReturn {
  isDragging: boolean;
  handleDragEnter: (e: React.DragEvent) => void;
  handleDragOver: (e: React.DragEvent) => void;
  handleDragLeave: (e: React.DragEvent) => void;
  handleDrop: (e: React.DragEvent) => void;
}

export function useDragAndDrop({
  disabled,
  supportsAttachment,
  addFiles,
}: UseDragAndDropParams): UseDragAndDropReturn {
  const [isDragging, setIsDragging] = useState(false);
  const dragCounter = useRef(0);

  const handleDragEnter = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter.current += 1;
      if (!disabled && supportsAttachment && e.dataTransfer.types.includes('Files')) {
        setIsDragging(true);
      }
    },
    [disabled, supportsAttachment]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounter.current -= 1;
    if (dragCounter.current <= 0) {
      dragCounter.current = 0;
      setIsDragging(false);
    }
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragCounter.current = 0;
      setIsDragging(false);
      if (!disabled && supportsAttachment && e.dataTransfer.files.length > 0) {
        addFiles(e.dataTransfer.files);
      }
    },
    [disabled, addFiles, supportsAttachment]
  );

  return {
    isDragging,
    handleDragEnter,
    handleDragOver,
    handleDragLeave,
    handleDrop,
  };
}
