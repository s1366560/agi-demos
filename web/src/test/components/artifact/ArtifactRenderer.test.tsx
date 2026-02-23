/**
 * Tests for ArtifactRenderer Compound Component Pattern
 *
 * TDD: Tests written first for the new compound component API.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { ArtifactRenderer } from '../../../components/artifact/ArtifactRenderer';

import type { Artifact } from '../../../types/agent';

// Mock the viewer components
vi.mock('../../../components/artifact/ImageViewer', () => ({
  ImageViewer: ({ src, onLoad }: { src: string; onLoad: () => void }) => (
    <div data-testid="image-viewer" data-src={src} onLoad={onLoad}>
      <img src={src} alt="Test Image" />
    </div>
  ),
}));

vi.mock('../../../components/artifact/VideoPlayer', () => ({
  VideoPlayer: ({ src, onLoad }: { src: string; onLoad: () => void }) => (
    <div data-testid="video-player" data-src={src} onLoad={onLoad}>
      <video src={src} />
    </div>
  ),
}));

vi.mock('../../../components/artifact/AudioPlayer', () => ({
  AudioPlayer: ({ src, onLoad }: { src: string; onLoad: () => void }) => (
    <div data-testid="audio-player" data-src={src} onLoad={onLoad}>
      <audio src={src} />
    </div>
  ),
}));

vi.mock('../../../components/artifact/CodeViewer', () => ({
  CodeViewer: ({ onLoad }: { onLoad: () => void }) => (
    <div data-testid="code-viewer" onLoad={onLoad}>
      <pre>code content</pre>
    </div>
  ),
}));

vi.mock('../../../components/artifact/FileDownloader', () => ({
  FileDownloader: ({ filename, url }: { filename: string; url: string }) => (
    <div data-testid="file-downloader" data-filename={filename}>
      <a href={url}>{filename}</a>
    </div>
  ),
}));

// Mock artifact data
const createMockArtifact = (category: string, status: string = 'ready'): Artifact => ({
  id: 'artifact-1',
  projectId: 'project-1',
  tenantId: 'tenant-1',
  filename: `test.${category === 'image' ? 'png' : category === 'video' ? 'mp4' : category === 'audio' ? 'mp3' : category}`,
  mimeType:
    category === 'image'
      ? 'image/png'
      : category === 'video'
        ? 'video/mp4'
        : 'application/octet-stream',
  category: category as any,
  sizeBytes: 1024,
  url: 'http://example.com/file.png',
  previewUrl: 'http://example.com/preview.png',
  status: status as any,
  createdAt: '2024-01-01T00:00:00Z',
});

const mockImageArtifact: Artifact = createMockArtifact('image');
const mockVideoArtifact: Artifact = createMockArtifact('video');
const mockAudioArtifact: Artifact = createMockArtifact('audio');
const mockCodeArtifact: Artifact = {
  ...createMockArtifact('code'),
  filename: 'test.py',
  mimeType: 'text/x-python',
};
const mockDocumentArtifact: Artifact = {
  ...createMockArtifact('document'),
  filename: 'test.pdf',
  mimeType: 'application/pdf',
};
const mockArchiveArtifact: Artifact = {
  ...createMockArtifact('archive'),
  filename: 'test.zip',
  mimeType: 'application/zip',
};
const mockPendingArtifact: Artifact = createMockArtifact('image', 'pending');
const mockErrorArtifact: Artifact = {
  ...createMockArtifact('image', 'error'),
  errorMessage: 'Failed to process',
};

describe('ArtifactRenderer Compound Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Root Component', () => {
    it('should render with artifact data', () => {
      render(
        <ArtifactRenderer artifact={mockImageArtifact}>
          <ArtifactRenderer.Image />
        </ArtifactRenderer>
      );

      expect(screen.getByText('test.png')).toBeInTheDocument();
    });

    it('should show compact mode when compact is true', () => {
      render(
        <ArtifactRenderer artifact={mockImageArtifact} compact>
          <ArtifactRenderer.Image />
        </ArtifactRenderer>
      );

      expect(document.querySelector('.artifact-renderer--compact')).toBeInTheDocument();
    });

    it('should show metadata when showMeta is true', () => {
      const artifactWithMeta: Artifact = {
        ...mockImageArtifact,
        sourceTool: 'test_tool',
        sourcePath: '/path/to/file',
      };

      render(
        <ArtifactRenderer artifact={artifactWithMeta} showMeta>
          <ArtifactRenderer.Image />
          <ArtifactRenderer.Meta />
        </ArtifactRenderer>
      );

      expect(screen.getByText(/test_tool/)).toBeInTheDocument();
    });

    it('should call onExpand when expand button is clicked', async () => {
      const mockOnExpand = vi.fn();
      const { container } = render(
        <ArtifactRenderer artifact={mockImageArtifact} onExpand={mockOnExpand}>
          <ArtifactRenderer.Image />
        </ArtifactRenderer>
      );

      const expandButton = container.querySelector('[title="Expand"]');
      if (expandButton) {
        fireEvent.click(expandButton);
        expect(mockOnExpand).toHaveBeenCalledWith(mockImageArtifact);
      }
    });
  });

  describe('Image Sub-Component', () => {
    it('should render image viewer for image artifacts', () => {
      render(
        <ArtifactRenderer artifact={mockImageArtifact}>
          <ArtifactRenderer.Image />
        </ArtifactRenderer>
      );

      expect(screen.getByTestId('image-viewer')).toBeInTheDocument();
    });

    it('should not render image viewer when Image component is excluded', () => {
      render(
        <ArtifactRenderer artifact={mockImageArtifact}>
          <ArtifactRenderer.Meta />
        </ArtifactRenderer>
      );

      expect(screen.queryByTestId('image-viewer')).not.toBeInTheDocument();
    });

    it('should show loading state for pending images', () => {
      render(
        <ArtifactRenderer artifact={mockPendingArtifact}>
          <ArtifactRenderer.Image />
        </ArtifactRenderer>
      );

      expect(screen.getByText(/Preparing/i)).toBeInTheDocument();
    });

    it('should show error state for failed images', () => {
      render(
        <ArtifactRenderer artifact={mockErrorArtifact}>
          <ArtifactRenderer.Image />
        </ArtifactRenderer>
      );

      expect(screen.getByText(/Failed to load/i)).toBeInTheDocument();
    });
  });

  describe('Video Sub-Component', () => {
    it('should render video player for video artifacts', () => {
      render(
        <ArtifactRenderer artifact={mockVideoArtifact}>
          <ArtifactRenderer.Video />
        </ArtifactRenderer>
      );

      expect(screen.getByTestId('video-player')).toBeInTheDocument();
    });

    it('should not render video player when Video component is excluded', () => {
      render(
        <ArtifactRenderer artifact={mockVideoArtifact}>
          <ArtifactRenderer.Meta />
        </ArtifactRenderer>
      );

      expect(screen.queryByTestId('video-player')).not.toBeInTheDocument();
    });
  });

  describe('Audio Sub-Component', () => {
    it('should render audio player for audio artifacts', () => {
      render(
        <ArtifactRenderer artifact={mockAudioArtifact}>
          <ArtifactRenderer.Audio />
        </ArtifactRenderer>
      );

      expect(screen.getByTestId('audio-player')).toBeInTheDocument();
    });

    it('should not render audio player when Audio component is excluded', () => {
      render(
        <ArtifactRenderer artifact={mockAudioArtifact}>
          <ArtifactRenderer.Meta />
        </ArtifactRenderer>
      );

      expect(screen.queryByTestId('audio-player')).not.toBeInTheDocument();
    });
  });

  describe('Code Sub-Component', () => {
    it('should render code viewer for code artifacts', () => {
      render(
        <ArtifactRenderer artifact={mockCodeArtifact}>
          <ArtifactRenderer.Code />
        </ArtifactRenderer>
      );

      expect(screen.getByTestId('code-viewer')).toBeInTheDocument();
    });

    it('should render code viewer for data artifacts', () => {
      const dataArtifact: Artifact = {
        ...mockCodeArtifact,
        category: 'data' as any,
        mimeType: 'application/json',
      };

      render(
        <ArtifactRenderer artifact={dataArtifact}>
          <ArtifactRenderer.Code />
        </ArtifactRenderer>
      );

      expect(screen.getByTestId('code-viewer')).toBeInTheDocument();
    });

    it('should not render code viewer when Code component is excluded', () => {
      render(
        <ArtifactRenderer artifact={mockCodeArtifact}>
          <ArtifactRenderer.Meta />
        </ArtifactRenderer>
      );

      expect(screen.queryByTestId('code-viewer')).not.toBeInTheDocument();
    });
  });

  describe('Document Sub-Component', () => {
    it('should render PDF iframe for PDF documents', () => {
      render(
        <ArtifactRenderer artifact={mockDocumentArtifact}>
          <ArtifactRenderer.Document />
        </ArtifactRenderer>
      );

      const iframe = document.querySelector('iframe');
      expect(iframe).toBeInTheDocument();
      expect(iframe).toHaveAttribute('src', mockDocumentArtifact.url);
    });
  });

  describe('Download Sub-Component', () => {
    it('should render file downloader for archive artifacts', () => {
      render(
        <ArtifactRenderer artifact={mockArchiveArtifact}>
          <ArtifactRenderer.Download />
        </ArtifactRenderer>
      );

      expect(screen.getByTestId('file-downloader')).toBeInTheDocument();
    });

    it('should render file downloader for other artifacts', () => {
      const otherArtifact: Artifact = {
        ...createMockArtifact('other'),
        filename: 'test.bin',
      };

      render(
        <ArtifactRenderer artifact={otherArtifact}>
          <ArtifactRenderer.Download />
        </ArtifactRenderer>
      );

      expect(screen.getByTestId('file-downloader')).toBeInTheDocument();
    });
  });

  describe('Meta Sub-Component', () => {
    it('should render metadata when sourceTool is provided', () => {
      const artifactWithMeta: Artifact = {
        ...mockImageArtifact,
        sourceTool: 'test_tool',
      };

      render(
        <ArtifactRenderer artifact={artifactWithMeta}>
          <ArtifactRenderer.Image />
          <ArtifactRenderer.Meta />
        </ArtifactRenderer>
      );

      expect(screen.getByText(/test_tool/)).toBeInTheDocument();
    });

    it('should render metadata with sourcePath when provided', () => {
      const artifactWithMeta: Artifact = {
        ...mockImageArtifact,
        sourceTool: 'test_tool',
        sourcePath: '/path/to/file',
      };

      render(
        <ArtifactRenderer artifact={artifactWithMeta}>
          <ArtifactRenderer.Image />
          <ArtifactRenderer.Meta />
        </ArtifactRenderer>
      );

      expect(screen.getByText(/test_tool/)).toBeInTheDocument();
      expect(screen.getByText(/\/path\/to\/file/)).toBeInTheDocument();
    });

    it('should not render metadata when Meta component is excluded', () => {
      const artifactWithMeta: Artifact = {
        ...mockImageArtifact,
        sourceTool: 'test_tool',
      };

      render(
        <ArtifactRenderer artifact={artifactWithMeta}>
          <ArtifactRenderer.Image />
        </ArtifactRenderer>
      );

      expect(screen.queryByText(/test_tool/)).not.toBeInTheDocument();
    });

    it('should show file size when showMeta is true', () => {
      render(
        <ArtifactRenderer artifact={mockImageArtifact} showMeta>
          <ArtifactRenderer.Image />
        </ArtifactRenderer>
      );

      // 1024 bytes = 1.0 KB
      expect(screen.getByText(/1\.0 KB/)).toBeInTheDocument();
    });
  });

  describe('Backward Compatibility', () => {
    it('should work with legacy props when no sub-components provided', () => {
      render(<ArtifactRenderer artifact={mockImageArtifact} />);

      // Should render with default behavior
      expect(screen.getByText('test.png')).toBeInTheDocument();
      expect(screen.getByTestId('image-viewer')).toBeInTheDocument();
    });

    it('should support legacy compact prop', () => {
      render(<ArtifactRenderer artifact={mockImageArtifact} compact />);

      expect(document.querySelector('.artifact-renderer--compact')).toBeInTheDocument();
    });

    it('should support legacy maxWidth prop', () => {
      render(<ArtifactRenderer artifact={mockImageArtifact} maxWidth={500} />);

      const container = document.querySelector('.artifact-renderer');
      expect(container?.style.maxWidth).toBe('500px');
    });
  });

  describe('Status States', () => {
    it('should show pending state', () => {
      const pendingArtifact: Artifact = {
        ...mockImageArtifact,
        status: 'pending' as any,
      };

      render(<ArtifactRenderer artifact={pendingArtifact} />);

      expect(screen.getByText(/Preparing/i)).toBeInTheDocument();
    });

    it('should show uploading state', () => {
      const uploadingArtifact: Artifact = {
        ...mockImageArtifact,
        status: 'uploading' as any,
      };

      render(<ArtifactRenderer artifact={uploadingArtifact} />);

      expect(screen.getByText(/Uploading/i)).toBeInTheDocument();
    });

    it('should show error state', () => {
      const errorArtifact: Artifact = {
        ...mockImageArtifact,
        status: 'error' as any,
        errorMessage: 'Processing failed',
      };

      render(<ArtifactRenderer artifact={errorArtifact} />);

      expect(screen.getByText(/Processing failed/)).toBeInTheDocument();
    });

    it('should show deleted state', () => {
      const deletedArtifact: Artifact = {
        ...mockImageArtifact,
        status: 'deleted' as any,
      };

      render(<ArtifactRenderer artifact={deletedArtifact} />);

      expect(screen.getByText(/deleted/i)).toBeInTheDocument();
    });
  });

  describe('ArtifactRenderer Namespace', () => {
    it('should export all sub-components', () => {
      expect(ArtifactRenderer.Root).toBeDefined();
      expect(ArtifactRenderer.Image).toBeDefined();
      expect(ArtifactRenderer.Video).toBeDefined();
      expect(ArtifactRenderer.Audio).toBeDefined();
      expect(ArtifactRenderer.Code).toBeDefined();
      expect(ArtifactRenderer.Document).toBeDefined();
      expect(ArtifactRenderer.Download).toBeDefined();
      expect(ArtifactRenderer.Meta).toBeDefined();
      expect(ArtifactRenderer.Header).toBeDefined();
      expect(ArtifactRenderer.Actions).toBeDefined();
    });

    it('should use Root component as alias', () => {
      render(
        <ArtifactRenderer.Root artifact={mockImageArtifact}>
          <ArtifactRenderer.Image />
        </ArtifactRenderer.Root>
      );

      expect(screen.getByText('test.png')).toBeInTheDocument();
    });
  });

  describe('Edge Cases', () => {
    it('should handle artifact without URL', () => {
      const noUrlArtifact: Artifact = {
        ...mockImageArtifact,
        url: undefined,
      };

      render(<ArtifactRenderer artifact={noUrlArtifact} />);

      expect(screen.getByText(/No content available/i)).toBeInTheDocument();
    });

    it('should handle empty filename', () => {
      const emptyFilenameArtifact: Artifact = {
        ...mockImageArtifact,
        filename: '',
      };

      render(<ArtifactRenderer artifact={emptyFilenameArtifact} />);

      // Should not crash, render empty title
      expect(screen.getByTestId('image-viewer')).toBeInTheDocument();
    });

    it('should handle zero size', () => {
      const zeroSizeArtifact: Artifact = {
        ...mockImageArtifact,
        sizeBytes: 0,
      };

      render(<ArtifactRenderer artifact={zeroSizeArtifact} showMeta />);

      expect(screen.getByText(/0 B/)).toBeInTheDocument();
    });
  });
});
