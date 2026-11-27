import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { App } from 'antd';
import {
  ChevronDown,
  ChevronRight,
  File,
  FileArchive,
  FileAudio,
  FileCode2,
  FileImage,
  FileText,
  FileVideo,
  Folder,
  FolderOpen,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
} from 'lucide-react';
import type { Artifact } from '../../../../../web/src/types/agent';
import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { useCanvasStore } from '../../../../../web/src/stores/canvasStore';
import {
  buildArtifactFileTree,
  buildSandboxFileTree,
  parseSandboxGlobPaths,
  type CanvasFileNode,
  type CanvasFileSource,
} from '../web/canvas/canvasFileTreeModel';
import { invoke } from './reviewAuthority';

// The files the page opens as text, as the file browser of the original workbench
// knows them. Anything else is opened by what the agent produced from it.
const TEXT_EXTENSIONS = new Set([
  'txt', 'md', 'markdown', 'json', 'jsonl', 'yaml', 'yml', 'toml', 'csv', 'tsv', 'xml',
  'html', 'htm', 'svg', 'css', 'scss', 'less', 'js', 'jsx', 'ts', 'tsx', 'mjs', 'cjs',
  'py', 'pyi', 'go', 'rs', 'java', 'kt', 'kts', 'rb', 'php', 'sh', 'bash', 'zsh', 'fish',
  'sql', 'log', 'ini', 'cfg', 'conf', 'env', 'dockerfile', 'gitignore', 'gitattributes',
  'prettierrc', 'eslintrc',
]);
const BINARY_EXTENSIONS = new Set([
  'png', 'jpg', 'jpeg', 'gif', 'webp', 'avif', 'ico', 'pdf', 'doc', 'docx', 'xls', 'xlsx',
  'ppt', 'pptx', 'mp3', 'wav', 'ogg', 'mp4', 'webm', 'mov', 'zip', 'tar', 'gz', 'tgz',
  'rar', '7z', 'bin', 'wasm', 'sqlite', 'db',
]);
const CODE_NAMES = new Set(['dockerfile', 'makefile', 'gemfile', 'rakefile', 'procfile']);

function extensionOf(name: string) {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
}

function opensAsText(path: string) {
  const name = path.split(/[\\/]/).filter(Boolean).at(-1) ?? path;
  const extension = extensionOf(name);
  if (TEXT_EXTENSIONS.has(extension)) return true;
  if (BINARY_EXTENSIONS.has(extension)) return false;
  const base = extension ? name.slice(0, -(extension.length + 1)) : name;
  return CODE_NAMES.has(base.toLowerCase());
}

function fileIcon(name: string) {
  const extension = extensionOf(name);
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'avif', 'ico'].includes(extension)) return FileImage;
  if (['mp4', 'webm', 'mov'].includes(extension)) return FileVideo;
  if (['mp3', 'wav', 'ogg'].includes(extension)) return FileAudio;
  if (['zip', 'tar', 'gz', 'tgz', 'rar', '7z'].includes(extension)) return FileArchive;
  if (['md', 'markdown', 'txt', 'pdf', 'doc', 'docx'].includes(extension)) return FileText;
  if (TEXT_EXTENSIONS.has(extension)) return FileCode2;
  return File;
}

/** What the page reads of a file the agent produced, by the view of the interactions. */
interface Produced {
  url?: string;
  preview?: string;
  content?: string;
  mime_type?: string;
}

interface Listing {
  nodes: CanvasFileNode[];
  loading: boolean;
  failure: string;
}
const NOTHING: Listing = { nodes: [], loading: false, failure: '' };

const ICON_BUTTON =
  'flex h-7 w-7 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-60 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100';

/**
 * The file browser of the canvas of the original workbench: the files of the project
 * sandbox, and the files the agent produced. A text file opens as a document of the
 * canvas. The page reads them through the package, which asks the sandbox only to
 * name its files and to read one of them.
 */
export function SignedFileExplorer({
  scope,
  conversation,
}: {
  scope: RichPageContext;
  conversation: string;
}) {
  const { t } = useTranslation();
  const toast = App.useApp().message;
  const openTab = useCanvasStore((s) => s.openTab);
  const readable = scope.commands.includes('chat-canvas-files');
  const [collapsed, setCollapsed] = useState(false);
  const [source, setSource] = useState<CanvasFileSource>('sandbox');
  const [list, setList] = useState<Listing>(NOTHING);
  const [refresh, setRefresh] = useState(0);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [opening, setOpening] = useState<string | null>(null);

  useEffect(() => {
    if (!readable) return;
    const controller = new AbortController();
    setList({ ...NOTHING, loading: true });
    async function load() {
      try {
        if (source === 'sandbox') {
          const { content, is_error } = await invoke<{ content: string; is_error: boolean }>(
            'chat-canvas-files',
            { view: 'sandbox' },
            { signal: controller.signal }
          );
          if (is_error) throw new Error(content || t('agent.canvas.fileExplorer.loadFailed'));
          if (!controller.signal.aborted)
            setList({ ...NOTHING, nodes: buildSandboxFileTree(parseSandboxGlobPaths(content)) });
        } else {
          // The command names the file as the application does; the tree reads the workbench's names.
          const { artifacts } = await invoke<{ artifacts: Record<string, unknown>[] }>(
            'chat-canvas-files',
            { view: 'artifacts' },
            { signal: controller.signal }
          );
          if (!controller.signal.aborted)
            setList({
              ...NOTHING,
              nodes: buildArtifactFileTree(
                artifacts.map(
                  (row) =>
                    ({
                      ...row,
                      mimeType: row.mime_type,
                      sizeBytes: row.size_bytes,
                      sourcePath: row.source_path,
                    }) as unknown as Artifact
                )
              ),
            });
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        setList({
          ...NOTHING,
          failure: error instanceof Error ? error.message : String(error),
        });
      }
    }
    void load();
    return () => controller.abort();
  }, [readable, source, refresh, t]);

  function toggle(id: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function open(node: CanvasFileNode) {
    if (node.kind === 'directory') {
      toggle(node.id);
      return;
    }
    if (opening) return;
    setOpening(node.path);
    try {
      if (node.source === 'sandbox') {
        if (!opensAsText(node.path)) {
          toast.info(t('agent.canvas.fileExplorer.noPreview'));
          return;
        }
        const { content, is_error } = await invoke<{ content: string; is_error: boolean }>(
          'chat-canvas-files',
          { view: 'read', path: node.path }
        );
        if (is_error) throw new Error(content || t('agent.canvas.fileExplorer.openFailed'));
        openTab({
          id: `sandbox:${node.path}`,
          title: node.name,
          type: /\.md$/i.test(node.name) ? 'markdown' : 'code',
          content,
          language: extensionOf(node.name),
        });
        return;
      }
      const produced = node.artifact;
      if (!produced) return;
      const { artifact } = await invoke<{ artifact?: Produced }>('chat-interactions', {
        conversation_id: conversation,
        view: 'artifact',
        artifact_id: produced.id,
      });
      if (!artifact) throw new Error(t('agent.canvas.fileExplorer.openFailed'));
      // A picture or a document the page can show opens here; anything else is left to its address.
      if (!artifact.preview && artifact.content === undefined) {
        if (artifact.url) void window.memstack.openUrl?.(artifact.url);
        else toast.info(t('agent.canvas.fileExplorer.noPreview'));
        return;
      }
      openTab({
        id: `artifact:${produced.id}`,
        title: node.name,
        type: artifact.preview ? 'preview' : /\.md$/i.test(node.name) ? 'markdown' : 'code',
        content: artifact.preview ?? artifact.content ?? '',
        language: extensionOf(node.name),
        mimeType: artifact.mime_type ?? produced.mimeType,
      });
    } catch (error) {
      toast.error(
        t('agent.canvas.fileExplorer.openFailedWithMessage', {
          message: error instanceof Error ? error.message : String(error),
          defaultValue: 'Failed to open file: {{message}}',
        })
      );
    } finally {
      setOpening(null);
    }
  }

  if (!readable) return null;
  if (collapsed)
    return (
      <aside className="hidden h-full w-10 shrink-0 border-r border-slate-200 bg-slate-50/90 md:flex dark:border-slate-800 dark:bg-slate-950/90">
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          title={t('agent.canvas.fileExplorer.expand')}
          aria-label={t('agent.canvas.fileExplorer.expand')}
          className="flex h-10 w-full items-center justify-center text-slate-500 hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100"
        >
          <PanelLeftOpen size={16} />
        </button>
      </aside>
    );

  function row(node: CanvasFileNode, depth: number) {
    const Icon =
      node.kind === 'directory'
        ? expanded.has(node.id)
          ? FolderOpen
          : Folder
        : fileIcon(node.name);
    return (
      <div key={node.id}>
        <button
          type="button"
          onClick={() => void open(node)}
          title={node.path}
          aria-expanded={node.kind === 'directory' ? expanded.has(node.id) : undefined}
          className="flex w-full items-center gap-1.5 rounded py-1 pr-1.5 text-left text-xs hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 dark:hover:bg-slate-800"
          style={{ paddingLeft: `${8 + depth * 12}px` }}
        >
          {node.kind === 'directory' ? (
            expanded.has(node.id) ? (
              <ChevronDown size={12} className="shrink-0 text-slate-400" />
            ) : (
              <ChevronRight size={12} className="shrink-0 text-slate-400" />
            )
          ) : (
            <span className="w-3 shrink-0" />
          )}
          <Icon size={14} className="shrink-0 text-slate-500 dark:text-slate-400" />
          <span className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-200">
            {node.name}
          </span>
          {opening === node.path && (
            <Loader2 size={12} className="shrink-0 animate-spin text-slate-400 motion-reduce:animate-none" />
          )}
        </button>
        {node.kind === 'directory' &&
          expanded.has(node.id) &&
          node.children.map((child) => row(child, depth + 1))}
      </div>
    );
  }

  const tab = (name: CanvasFileSource, label: string) => (
    <button
      key={name}
      type="button"
      onClick={() => setSource(name)}
      aria-pressed={source === name}
      className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
        source === name
          ? 'bg-white text-slate-800 shadow-sm dark:bg-slate-800 dark:text-slate-100'
          : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100'
      }`}
    >
      {label}
    </button>
  );

  return (
    <aside className="hidden h-full w-[260px] shrink-0 flex-col border-r border-slate-200 bg-slate-50/90 md:flex xl:w-[272px] dark:border-slate-800 dark:bg-slate-950/90">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-slate-200 px-2 dark:border-slate-800">
        <span className="min-w-0 flex-1 truncate text-xs font-semibold uppercase tracking-label text-slate-500 dark:text-slate-400">
          {t('agent.canvas.fileExplorer.title')}
        </span>
        <button
          type="button"
          onClick={() => setRefresh((value) => value + 1)}
          title={t('agent.canvas.fileExplorer.refresh')}
          aria-label={t('agent.canvas.fileExplorer.refresh')}
          disabled={list.loading}
          className={ICON_BUTTON}
        >
          <RefreshCw
            size={14}
            className={list.loading ? 'animate-spin motion-reduce:animate-none' : undefined}
          />
        </button>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          title={t('agent.canvas.fileExplorer.collapse')}
          aria-label={t('agent.canvas.fileExplorer.collapse')}
          className={ICON_BUTTON}
        >
          <PanelLeftClose size={16} />
        </button>
      </div>
      <div
        role="tablist"
        aria-label={t('agent.canvas.fileExplorer.title')}
        className="flex shrink-0 gap-1 border-b border-slate-200 p-1.5 dark:border-slate-800"
      >
        {tab('sandbox', t('agent.canvas.fileExplorer.sandbox'))}
        {tab('artifacts', t('agent.canvas.fileExplorer.artifacts'))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto py-1">
        {list.failure ? (
          <p role="alert" className="px-2 py-1.5 text-xs text-red-600 dark:text-red-400">
            {list.failure}
          </p>
        ) : list.loading && list.nodes.length === 0 ? (
          <p className="px-2 py-1.5 text-xs text-slate-500 dark:text-slate-400">
            {t('agent.canvas.fileExplorer.loading')}
          </p>
        ) : list.nodes.length === 0 ? (
          <p className="px-2 py-1.5 text-xs text-slate-500 dark:text-slate-400">
            {t('agent.canvas.fileExplorer.empty')}
          </p>
        ) : (
          list.nodes.map((node) => row(node, 0))
        )}
      </div>
    </aside>
  );
}
