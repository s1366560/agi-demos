import type { CursorPose } from './engine';

export const CURSOR_WIDTH_PX = 23;
export const CURSOR_HEIGHT_PX = 24;
export const CURSOR_Z_INDEX = 2147483646;
export const GLOW_COLOR = '#339cff';

/**
 * Hand-drawn arrow pointer (23x24, tip at the top-left corner).
 * Dark body, white outline; the blue glow is a CSS drop-shadow so the
 * asset stays a single flat shape.
 */
const CURSOR_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="${CURSOR_WIDTH_PX}" height="${CURSOR_HEIGHT_PX}" viewBox="0 0 23 24"><path d="M3.2 1.6 L3.2 18.9 L7.9 14.6 L10.8 21.2 L13.6 19.9 L10.7 13.4 L17.2 13.1 Z" fill="#20242b" stroke="#ffffff" stroke-width="1.6" stroke-linejoin="round"/></svg>`;

export const CURSOR_IMAGE_URI = `data:image/svg+xml,${encodeURIComponent(CURSOR_SVG)}`;

export interface CursorOverlay {
  setPose(pose: CursorPose): void;
  destroy(): void;
}

/**
 * Fixed, click-through overlay hosting the fake cursor inside a closed
 * shadow root on document.documentElement. A MutationObserver re-appends
 * the host if the page removes it. Hidden when printing.
 */
export function createCursorOverlay(doc: Document): CursorOverlay {
  const host = doc.createElement('div');
  host.setAttribute('data-memstack-agent-cursor', '');
  const shadow = host.attachShadow({ mode: 'closed' });

  const style = doc.createElement('style');
  style.textContent = `
    :host {
      position: fixed;
      inset: 0;
      z-index: ${CURSOR_Z_INDEX};
      pointer-events: none;
    }
    @media print {
      :host { display: none; }
    }
    .cursor {
      position: absolute;
      top: 0;
      left: 0;
      width: ${CURSOR_WIDTH_PX}px;
      height: ${CURSOR_HEIGHT_PX}px;
      background: url("${CURSOR_IMAGE_URI}") no-repeat center / contain;
      will-change: transform, opacity;
      filter: drop-shadow(0 0 2px ${GLOW_COLOR}) drop-shadow(0 2px 6px rgba(51, 156, 255, 0.45));
    }
  `;
  const cursor = doc.createElement('div');
  cursor.className = 'cursor';
  cursor.style.opacity = '0';
  shadow.append(style, cursor);

  const mount = () => {
    if (!host.isConnected) doc.documentElement.appendChild(host);
  };
  mount();

  const observer = new MutationObserver(mount);
  observer.observe(doc.documentElement, { childList: true });

  return {
    setPose(pose: CursorPose): void {
      cursor.style.opacity = String(pose.opacity);
      if (!pose.visible && pose.opacity <= 0.01) return;
      cursor.style.transform =
        `translate(${pose.x}px, ${pose.y}px) ` +
        `rotate(${pose.headingDeg}deg) scale(${pose.stretch}, 1) ` +
        `rotate(${pose.rotationDeg - pose.headingDeg}deg)`;
    },
    destroy(): void {
      observer.disconnect();
      host.remove();
    },
  };
}
