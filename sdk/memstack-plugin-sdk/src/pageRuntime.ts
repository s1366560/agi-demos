/** Capabilities available to a signed rich-page IIFE inside its isolated document. */
export interface RichPageContext {
  readonly tenantId: string;
  readonly projectId: string | null;
  readonly target: "web" | "desktop-renderer";
  readonly platform: "web" | "desktop-renderer";
  readonly locale: string;
  readonly pathname: string;
  readonly search: string;
  readonly hash: string;
  readonly commands: readonly string[];
  readonly voiceAvailable?: boolean;
  readonly deviceTools: readonly string[];
}

export interface RichPageCallOptions {
  readonly signal?: AbortSignal | undefined;
  readonly onEvent?: (value: unknown) => void;
}

export interface RichPageRuntime {
  anchorSlot(name: string, element: HTMLElement, search?: string, onError?: (reason: string) => void): () => void;
  voice(mode: "voice" | "dictation", conversationId: string, options: RichPageCallOptions): Promise<void>;
  muteVoice(handle: string, value: boolean): Promise<void>;
  assetUrl(path: string): string;
  scope(): Promise<RichPageContext>;
  getContext(): Promise<RichPageContext>;
  reviewDevice?(): Promise<void>;
  openPage(pluginId: string, pageId: string, destination?: string): Promise<void>;
  navigate(path: string, options?: { replace?: boolean }): Promise<void>;
  exportCsv(name: string, payload: Record<string, unknown>, options?: Pick<RichPageCallOptions, "signal">): Promise<void>;
  invoke(
    command: string,
    payload?: Record<string, unknown>,
    options?: RichPageCallOptions,
  ): Promise<unknown>;
  device(
    tool: string,
    payload?: Record<string, unknown>,
    options?: Pick<RichPageCallOptions, "signal">,
  ): Promise<unknown>;
}

declare global {
  interface Window {
    readonly memstack: RichPageRuntime;
  }
}
