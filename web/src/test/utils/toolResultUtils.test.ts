/**
 * Tests for toolResultUtils - shared utility functions for tool result parsing
 *
 * TDD: Extracted duplicated code from ToolExecutionCard and ToolExecutionDetail
 */

import { describe, it, expect } from 'vitest';

import {
  isImageUrl,
  parseBase64Image,
  extractImageUrl,
  foldText,
} from '../../utils/toolResultUtils';

describe('toolResultUtils', () => {
  describe('isImageUrl', () => {
    it('returns false for empty string', () => {
      expect(isImageUrl('')).toBe(false);
    });

    it('returns false for non-image URL', () => {
      expect(isImageUrl('https://example.com/page.html')).toBe(false);
    });

    it('returns true for common image extensions', () => {
      expect(isImageUrl('https://example.com/image.jpg')).toBe(true);
      expect(isImageUrl('https://example.com/image.jpeg')).toBe(true);
      expect(isImageUrl('https://example.com/image.png')).toBe(true);
      expect(isImageUrl('https://example.com/image.gif')).toBe(true);
      expect(isImageUrl('https://example.com/image.webp')).toBe(true);
      expect(isImageUrl('https://example.com/image.svg')).toBe(true);
      expect(isImageUrl('https://example.com/image.bmp')).toBe(true);
      expect(isImageUrl('https://example.com/image.ico')).toBe(true);
    });

    it('returns true for image URLs with query params', () => {
      expect(isImageUrl('https://example.com/image.png?width=200')).toBe(true);
    });

    it('returns true for known image hosting domains', () => {
      expect(isImageUrl('https://mdn.alipayobjects.com/a/b')).toBe(true);
      expect(isImageUrl('https://img.alicdn.com/a/b')).toBe(true);
      expect(isImageUrl('https://cdn.jsdelivr.net/gh/user/repo/image')).toBe(true);
      expect(isImageUrl('https://i.imgur.com/abc')).toBe(true);
      expect(isImageUrl('https://images.unsplash.com/photo-123')).toBe(true);
    });

    it('returns true for URLs ending with /original', () => {
      expect(isImageUrl('https://example.com/path/original')).toBe(true);
    });

    it('handles invalid URL gracefully', () => {
      expect(isImageUrl('not-a-url')).toBe(false);
    });

    it('trims whitespace before checking', () => {
      expect(isImageUrl('  https://example.com/image.png  ')).toBe(true);
    });
  });

  describe('parseBase64Image', () => {
    it('returns null for empty string', () => {
      expect(parseBase64Image('')).toBe(null);
    });

    it('returns null for non-base64 content', () => {
      expect(parseBase64Image('hello world')).toBe(null);
    });

    it('detects PNG format from magic bytes', () => {
      // The implementation requires length > 100 for non-JSON wrapped base64
      const base64Png = 'iVBORw0KGgo' + 'A'.repeat(100);
      const result = parseBase64Image(base64Png);
      expect(result).toEqual({ data: base64Png, format: 'png' });
    });

    it('detects JPEG format from magic bytes', () => {
      // The implementation requires length > 100 for non-JSON wrapped base64
      const base64Jpeg = '/9j/' + 'A'.repeat(100);
      const result = parseBase64Image(base64Jpeg);
      expect(result).toEqual({ data: base64Jpeg, format: 'jpeg' });
    });

    it('detects GIF format from magic bytes', () => {
      // The implementation requires length > 100 for non-JSON wrapped base64
      const base64Gif = 'R0lGOD' + 'A'.repeat(100);
      const result = parseBase64Image(base64Gif);
      expect(result).toEqual({ data: base64Gif, format: 'gif' });
    });

    it('detects WebP format from magic bytes', () => {
      // The implementation requires length > 100 for non-JSON wrapped base64
      const base64Webp = 'UklGR' + 'A'.repeat(100);
      const result = parseBase64Image(base64Webp);
      expect(result).toEqual({ data: base64Webp, format: 'webp' });
    });

    it('parses JSON wrapped base64 data', () => {
      const jsonWithBase64 = `{'data': 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='}`;
      const result = parseBase64Image(jsonWithBase64);
      expect(result).toEqual({
        data: 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
        format: 'png',
      });
    });

    it('handles double quotes in JSON', () => {
      const jsonWithBase64 = `{"data": "iVBORw0KGgo"}`;
      const result = parseBase64Image(jsonWithBase64);
      expect(result).toEqual({
        data: 'iVBORw0KGgo',
        format: 'png',
      });
    });

    it('defaults to PNG format for unknown base64', () => {
      const longBase64 = 'A'.repeat(200);
      const result = parseBase64Image(longBase64);
      expect(result).toEqual({ data: longBase64, format: 'png' });
    });

    it('returns null for short base64 strings', () => {
      const shortBase64 = 'iVBORw0KGgo';
      const result = parseBase64Image(shortBase64);
      expect(result).toBe(null);
    });

    it('handles parse errors gracefully', () => {
      expect(parseBase64Image('{invalid json}')).toBe(null);
    });
  });

  describe('extractImageUrl', () => {
    it('returns null for empty string', () => {
      expect(extractImageUrl('')).toBe(null);
    });

    it('returns the URL if entire string is an image URL', () => {
      expect(extractImageUrl('https://example.com/image.png')).toBe(
        'https://example.com/image.png'
      );
    });

    it('extracts image URL from text containing URLs', () => {
      const text = 'Check out this image: https://example.com/photo.jpg and more text';
      expect(extractImageUrl(text)).toBe('https://example.com/photo.jpg');
    });

    it('returns null if no image URL found', () => {
      expect(extractImageUrl('Check out https://example.com/page.html')).toBe(null);
    });

    it('finds first image URL when multiple URLs present', () => {
      const text = 'Image 1: https://example.com/a.jpg and Image 2: https://example.com/b.png';
      expect(extractImageUrl(text)).toBe('https://example.com/a.jpg');
    });

    it('trims whitespace before checking', () => {
      expect(extractImageUrl('  https://example.com/image.png  ')).toBe(
        'https://example.com/image.png'
      );
    });

    it('handles URLs with query parameters', () => {
      expect(extractImageUrl('https://example.com/image.png?width=200&height=150')).toBe(
        'https://example.com/image.png?width=200&height=150'
      );
    });
  });

  describe('foldText', () => {
    it('returns empty string for undefined', () => {
      expect(foldText(undefined)).toBe('');
    });

    it('returns original text when line count is below threshold', () => {
      const shortText = 'line1\nline2\nline3';
      expect(foldText(shortText, 5)).toBe('line1\nline2\nline3');
    });

    it('returns original text when line count equals threshold', () => {
      const text = 'line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10';
      expect(foldText(text, 5)).toBe(text);
    });

    it('folds text when line count exceeds threshold', () => {
      const lines = Array.from({ length: 20 }, (_, i) => `line${i + 1}`);
      const text = lines.join('\n');
      const result = foldText(text, 5);

      expect(result).toContain('line1');
      expect(result).toContain('line5');
      expect(result).toContain('line16');
      expect(result).toContain('line20');
      expect(result).toContain('10 lines collapsed');
    });

    it('uses default keepLines of 5', () => {
      const lines = Array.from({ length: 20 }, (_, i) => `line${i + 1}`);
      const text = lines.join('\n');
      const result = foldText(text);

      expect(result).toContain('line1');
      expect(result).toContain('line5');
      expect(result).toContain('... (10 lines collapsed) ...');
    });

    it('preserves line breaks in folded sections', () => {
      const lines = Array.from({ length: 20 }, (_, i) => `line${i + 1}`);
      const text = lines.join('\n');
      const result = foldText(text, 5);

      const resultLines = result.split('\n');
      // First 5 lines + folded message (contains newlines in the text) + last 5 lines
      // The folded message is "\n... (10 lines collapsed) ...\n" which adds extra lines
      expect(resultLines.length).toBeGreaterThan(10);
      expect(result).toContain('line1');
      expect(result).toContain('line20');
    });

    it('handles text with varying line lengths', () => {
      const lines = [
        'short',
        'medium length line',
        'very long line that goes on and on and on',
        'line4',
        'line5',
        'line6',
        'line7',
        'line8',
        'line9',
        'line10',
        'line11',
        'line12',
        'line13',
        'line14',
        'line15',
      ];
      const text = lines.join('\n');
      const result = foldText(text, 3);

      expect(result).toContain('short');
      expect(result).toContain('line15');
      expect(result).toContain('9 lines collapsed');
    });
  });

  describe('foldTextWithMetadata', () => {
    it('returns folded status in result object', () => {
      const { text, folded } = foldText.withMetadata('line1\nline2\nline3', 5);
      expect(text).toBe('line1\nline2\nline3');
      expect(folded).toBe(false);
    });

    it('returns folded: true when text was folded', () => {
      const lines = Array.from({ length: 20 }, (_, i) => `line${i + 1}`);
      const text = lines.join('\n');
      const { text: foldedText, folded } = foldText.withMetadata(text, 5);

      expect(folded).toBe(true);
      expect(foldedText).toContain('10 lines collapsed');
    });
  });
});
