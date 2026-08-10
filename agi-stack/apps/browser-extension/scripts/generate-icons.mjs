#!/usr/bin/env node
/**
 * Generates the extension icons (public/icons/icon-{16,48,128}.png) with no
 * third-party dependencies: pixels are rasterized by hand (rounded-square
 * indigo tile + white "M" mark) and encoded as PNG via zlib + manual CRC32.
 *
 * Usage: node scripts/generate-icons.mjs
 */
import { deflateSync } from 'node:zlib';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT_DIR = join(ROOT, 'public', 'icons');

const BG = [79, 70, 229]; // #4F46E5 indigo
const FG = [255, 255, 255];

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf) {
  let crc = 0xffffffff;
  for (const byte of buf) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const typeBuf = Buffer.from(type, 'ascii');
  const out = Buffer.alloc(8 + data.length + 4);
  out.writeUInt32BE(data.length, 0);
  typeBuf.copy(out, 4);
  data.copy(out, 8);
  out.writeUInt32BE(crc32(Buffer.concat([typeBuf, data])), 8 + data.length);
  return out;
}

function encodePng(width, height, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // color type RGBA
  // scanlines, filter byte 0 per row
  const raw = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (width * 4 + 1)] = 0;
    rgba.copy(raw, y * (width * 4 + 1) + 1, y * width * 4, (y + 1) * width * 4);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', deflateSync(raw, { level: 9 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

function distToSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const lenSq = dx * dx + dy * dy;
  let t = lenSq === 0 ? 0 : ((px - ax) * dx + (py - ay) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  const cx = ax + t * dx;
  const cy = ay + t * dy;
  return Math.hypot(px - cx, py - cy);
}

/** The "M" mark as stroke segments in unit-square coordinates. */
const M_SEGMENTS = [
  [0.28, 0.72, 0.28, 0.28],
  [0.28, 0.28, 0.5, 0.56],
  [0.5, 0.56, 0.72, 0.28],
  [0.72, 0.28, 0.72, 0.72],
];

function roundedRectCoverage(x, y, size, radius) {
  // distance outside the rounded rect, in pixels (negative = inside)
  const r = radius;
  const qx = Math.abs(x - size / 2) - (size / 2 - r);
  const qy = Math.abs(y - size / 2) - (size / 2 - r);
  const outside = Math.hypot(Math.max(qx, 0), Math.max(qy, 0)) + Math.min(Math.max(qx, qy), 0) - r;
  return Math.max(0, Math.min(1, 0.5 - outside)); // 1px antialias band
}

function rasterize(size) {
  const rgba = Buffer.alloc(size * size * 4);
  const radius = size * 0.22;
  const stroke = size * 0.09;
  const samples = 4; // 4x4 supersampling
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let bgAcc = 0;
      let fgAcc = 0;
      for (let sy = 0; sy < samples; sy++) {
        for (let sx = 0; sx < samples; sx++) {
          const px = x + (sx + 0.5) / samples;
          const py = y + (sy + 0.5) / samples;
          bgAcc += roundedRectCoverage(px, py, size, radius) > 0.5 ? 1 : 0;
          const ux = px / size;
          const uy = py / size;
          const hit = M_SEGMENTS.some(
            ([ax, ay, bx, by]) =>
              distToSegment(ux, uy, ax, ay, bx, by) * size <= stroke / 2,
          );
          if (hit) fgAcc += 1;
        }
      }
      const total = samples * samples;
      const bgA = bgAcc / total;
      const fgA = (fgAcc / total) * bgA; // mark only inside the tile
      const i = (y * size + x) * 4;
      for (let c = 0; c < 3; c++) {
        // composite fg over bg over transparent
        rgba[i + c] = Math.round(FG[c] * fgA + BG[c] * bgA * (1 - fgA));
      }
      rgba[i + 3] = Math.round(255 * (fgA + bgA * (1 - fgA)));
    }
  }
  return rgba;
}

mkdirSync(OUT_DIR, { recursive: true });
for (const size of [16, 48, 128]) {
  const png = encodePng(size, size, rasterize(size));
  const file = join(OUT_DIR, `icon-${size}.png`);
  writeFileSync(file, png);
  console.log(`wrote ${file} (${png.length} bytes)`);
}
