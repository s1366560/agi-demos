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

export interface RichPageNavigateOptions {
  readonly replace?: boolean | undefined;
  /** The page keeps its view and state at the new address. */
  readonly keepMounted?: boolean | undefined;
}

export interface RichPageFileContent {
  readonly text?: string | undefined;
  readonly bytes_base64?: string | undefined;
}

export interface RichPageCallOptions {
  readonly signal?: AbortSignal | undefined;
  readonly onEvent?: (value: unknown) => void;
}

export interface RichPageRuntime {
  anchorSlot(
    name: string,
    element: HTMLElement,
    search?: string,
    onError?: (reason: string) => void,
  ): () => void;
  voice(
    mode: "voice" | "dictation",
    conversationId: string,
    options: RichPageCallOptions,
  ): Promise<void>;
  muteVoice(handle: string, value: boolean): Promise<void>;
  assetUrl(path: string): string;
  scope(): Promise<RichPageContext>;
  getContext(): Promise<RichPageContext>;
  reviewDevice?(): Promise<void>;
  openPage(
    pluginId: string,
    pageId: string,
    destination?: string,
  ): Promise<void>;
  /** Move to another route of this page. With `keepMounted` the page is not loaded again. */
  navigate(path: string, options?: RichPageNavigateOptions): Promise<void>;
  /**
   * Call the listener whenever the context changes while the page stays loaded, as the
   * address does after a navigation with `keepMounted`. Returns what ends the calls.
   * A host of an earlier version has none; read it as optional.
   */
  onContextChange?(listener: (context: RichPageContext) => void): () => void;
  /**
   * Open an address of the web (http or https) for the page in a new tab or the
   * system browser. Other schemes are refused. A host of an earlier version has
   * none; read it as optional.
   *
   * The page also finds its own `localStorage` and `sessionStorage`: what it stores
   * in the first is kept by the workbench for this tenant, project and package.
   */
  openUrl?(url: string): Promise<void>;
  exportCsv(
    name: string,
    payload: Record<string, unknown>,
    options?: Pick<RichPageCallOptions, "signal">,
  ): Promise<void>;
  /**
   * Hand a file to the user, which the workbench offers to save under this name.
   * The content is text, or bytes as base64. A host of an earlier version has
   * none; read it as optional.
   */
  saveFile?(
    name: string,
    content: RichPageFileContent,
    mimeType?: string,
    options?: Pick<RichPageCallOptions, "signal">,
  ): Promise<void>;
  /**
   * Print an HTML document to a PDF file and offer it to the user under this name.
   * The workbench lays the document out as it prints its own. The document runs no
   * script and reaches no address. A host of an earlier version has none.
   */
  printPdf?(
    name: string,
    html: string,
    options?: Pick<RichPageCallOptions, "signal">,
  ): Promise<void>;
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
