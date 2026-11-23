/** Capabilities available to a signed rich-page IIFE inside its isolated document. */
export interface RichPageContext {
  readonly tenantId: string;
  readonly projectId: string;
  readonly target: "web" | "desktop-renderer";
  readonly platform: "web" | "desktop-renderer";
  readonly locale: string;
  readonly pathname: string;
  readonly commands: readonly string[];
  readonly deviceTools: readonly string[];
}

export interface RichPageCallOptions {
  readonly signal?: AbortSignal;
  readonly onEvent?: (value: unknown) => void;
}

export interface RichPageRuntime {
  scope(): Promise<RichPageContext>;
  getContext(): Promise<RichPageContext>;
  navigate(path: string): Promise<void>;
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
