/**
 * Type declarations for vendored noVNC (core/rfb.js)
 */
declare module '*/vendor/novnc/rfb.js' {
  interface RFBCredentials {
    username?: string;
    password?: string;
    target?: string;
  }

  interface RFBCapabilities {
    power: boolean;
  }

  interface RFBOptions {
    shared?: boolean;
    credentials?: RFBCredentials;
    repeaterID?: string;
    wsProtocols?: string[];
  }

  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, urlOrChannel: string | WebSocket, options?: RFBOptions);

    viewOnly: boolean;
    focusOnClick: boolean;
    clipViewport: boolean;
    dragViewport: boolean;
    scaleViewport: boolean;
    resizeSession: boolean;
    showDotCursor: boolean;
    background: string;
    qualityLevel: number;
    compressionLevel: number;
    capabilities: RFBCapabilities;

    disconnect(): void;
    sendCredentials(credentials: RFBCredentials): void;
    sendKey(keysym: number, code: string | null, down?: boolean): void;
    sendCtrlAltDel(): void;
    focus(): void;
    blur(): void;
    machineShutdown(): void;
    machineReboot(): void;
    machineReset(): void;
    clipboardPasteFrom(text: string): void;
    getImageData(): ImageData;
    toDataURL(type?: string, encoderOptions?: number): string;
    toBlob(callback: (blob: Blob | null) => void, type?: string, quality?: number): void;
  }
}
