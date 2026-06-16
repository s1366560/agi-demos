/**
 * Skill detail page.
 *
 * Shows the Agent Skills package metadata, content, and version history.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FC, ReactNode } from 'react';

import { useTranslation } from 'react-i18next';
import ReactMarkdown from 'react-markdown';
import { useLocation, useNavigate, useParams } from 'react-router-dom';

import { Alert, Tag } from 'antd';
import {
  ArrowLeft,
  ChevronRight,
  CheckCircle2,
  ClipboardList,
  Code2,
  Copy,
  Download,
  Eye,
  FileText,
  Folder,
  FolderOpen,
  GitBranch,
  History,
  KeyRound,
  Pencil,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Wrench,
  XCircle,
} from 'lucide-react';

import { useTenantStore } from '@/stores/tenant';

import { skillAPI } from '@/services/skillService';

import { SkillModal } from '@/components/skill/SkillModal';
import { LazyEmpty, LazyPopconfirm, LazySpin, useLazyMessage } from '@/components/ui/lazyAntd';

import {
  safeMarkdownComponents,
  useMarkdownPlugins,
} from '../../components/agent/chat/markdownPlugins';
import { MARKDOWN_PROSE_CLASSES } from '../../components/agent/styles';

import type {
  SkillEvolutionDetailResponse,
  SkillEvolutionRouteEntry,
  SkillResponse,
  SkillVersionResponse,
} from '@/types/agent';

type SkillSource = NonNullable<SkillResponse['source']>;
type SkillContentMode = 'preview' | 'raw';
type SkillDetailMode = 'preview' | 'manage' | 'report';
type SkillPreviewFileKind = 'markdown' | 'text';
type SkillAssessmentGroup = 'p0' | 'p1' | 'p2';
type SkillAssessmentStatus = 'pass' | 'warn';

interface SkillPreviewFile {
  path: string;
  content: string;
  kind: SkillPreviewFileKind;
}

interface SkillPreviewTreeFile {
  type: 'file';
  file: SkillPreviewFile;
}

interface SkillPreviewTreeDirectory {
  type: 'directory';
  path: string;
  name: string;
  children: SkillPreviewTreeNode[];
}

type SkillPreviewTreeNode = SkillPreviewTreeDirectory | SkillPreviewTreeFile;

interface SkillAssessmentItem {
  id: string;
  group: SkillAssessmentGroup;
  status: SkillAssessmentStatus;
  title: string;
  description: string;
}

interface SkillAssessmentGroupSummary {
  group: SkillAssessmentGroup;
  passed: number;
  total: number;
}

interface SkillAssessmentReport {
  status: 'safe' | 'attention';
  generatedAt: string;
  items: SkillAssessmentItem[];
  groups: SkillAssessmentGroupSummary[];
  text: string;
}

const pageText = 'text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.94_0.006_255)]';
const mutedText = 'text-[oklch(0.48_0.01_255)] dark:text-[oklch(0.68_0.008_255)]';
const surface =
  'border border-[oklch(0.9_0.006_255)] bg-[oklch(0.99_0.004_255)] dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.18_0.006_255)]';
const actionButton =
  'inline-flex h-9 items-center justify-center gap-2 rounded-[4px] border border-[oklch(0.86_0.006_255)] px-3 text-sm font-medium text-[oklch(0.34_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] disabled:cursor-not-allowed disabled:opacity-60 dark:border-[oklch(0.34_0.006_255)] dark:text-[oklch(0.82_0.006_255)] dark:hover:bg-[oklch(0.24_0.006_255)]';

function formatDate(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : '';
}

function jsonBlock(value: Record<string, unknown> | undefined): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function stringifyResourceFile(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function getPreviewFileKind(path: string): SkillPreviewFileKind {
  return path.toLowerCase().endsWith('.md') || path.toLowerCase().endsWith('.mdx')
    ? 'markdown'
    : 'text';
}

function sortPreviewTreeNodes(nodes: SkillPreviewTreeNode[]): SkillPreviewTreeNode[] {
  return [...nodes].sort((left, right) => {
    if (left.type !== right.type) {
      return left.type === 'directory' ? -1 : 1;
    }

    const leftName = left.type === 'directory' ? left.name : left.file.path;
    const rightName = right.type === 'directory' ? right.name : right.file.path;
    return leftName.localeCompare(rightName);
  });
}

function buildPreviewFileTree(files: SkillPreviewFile[]): SkillPreviewTreeNode[] {
  const roots: SkillPreviewTreeNode[] = [];
  const directories = new Map<string, SkillPreviewTreeDirectory>();

  const getDirectory = (
    directoryPath: string,
    name: string,
    siblings: SkillPreviewTreeNode[]
  ): SkillPreviewTreeDirectory => {
    const existing = directories.get(directoryPath);
    if (existing) {
      return existing;
    }

    const directory: SkillPreviewTreeDirectory = {
      type: 'directory',
      path: directoryPath,
      name,
      children: [],
    };
    directories.set(directoryPath, directory);
    siblings.push(directory);
    return directory;
  };

  files.forEach((file) => {
    const parts = file.path.split('/').filter(Boolean);
    let siblings = roots;
    let currentPath = '';

    parts.slice(0, -1).forEach((part) => {
      currentPath = currentPath ? `${currentPath}/${part}` : part;
      siblings = getDirectory(currentPath, part, siblings).children;
    });

    siblings.push({ type: 'file', file });
  });

  const sortRecursively = (nodes: SkillPreviewTreeNode[]): SkillPreviewTreeNode[] =>
    sortPreviewTreeNodes(nodes).map((node) =>
      node.type === 'directory' ? { ...node, children: sortRecursively(node.children) } : node
    );

  return sortRecursively(roots);
}

function getPreviewDirectoryPaths(nodes: SkillPreviewTreeNode[]): string[] {
  return nodes.flatMap((node) => {
    if (node.type === 'file') {
      return [];
    }

    return [node.path, ...getPreviewDirectoryPaths(node.children)];
  });
}

function getAssessmentItemClasses(status: SkillAssessmentStatus): string {
  return status === 'pass'
    ? 'border-[oklch(0.82_0.06_145)] bg-[oklch(0.97_0.018_145)] text-[oklch(0.34_0.11_145)] dark:border-[oklch(0.36_0.06_145)] dark:bg-[oklch(0.19_0.035_145)] dark:text-[oklch(0.78_0.09_145)]'
    : 'border-[oklch(0.84_0.08_75)] bg-[oklch(0.98_0.022_75)] text-[oklch(0.45_0.1_75)] dark:border-[oklch(0.38_0.07_75)] dark:bg-[oklch(0.21_0.035_75)] dark:text-[oklch(0.82_0.1_75)]';
}

function buildAssessmentReport({
  skill,
  previewFiles,
  versions,
  t,
}: {
  skill: SkillResponse;
  previewFiles: SkillPreviewFile[];
  versions: SkillVersionResponse[];
  t: (key: string, options?: Record<string, unknown>) => string;
}): SkillAssessmentReport {
  const skillContent = previewFiles.map((file) => file.content).join('\n');
  const possibleSecretPattern =
    /(api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*["']?[A-Za-z0-9_\-.]{16,}/i;
  const hasPossibleSecret = possibleSecretPattern.test(skillContent);
  const hasHiddenCharacters = /[\u200B-\u200D\uFEFF]/.test(skillContent);
  const hasAllowedTools = skill.tools.length > 0;
  const hasBundledFiles = previewFiles.length > 1;
  const hasVersionSnapshot = versions.length > 0 || skill.current_version > 0;
  const hasMetadata = Boolean(skill.metadata && Object.keys(skill.metadata).length > 0);
  const hasLicense = Boolean(skill.license);
  const hasCompatibility = Boolean(skill.compatibility);

  const items: SkillAssessmentItem[] = [
    {
      id: 'secrets',
      group: 'p0',
      status: hasPossibleSecret ? 'warn' : 'pass',
      title: t('tenant.skills.detail.assessment.items.secrets.title'),
      description: t(
        hasPossibleSecret
          ? 'tenant.skills.detail.assessment.items.secrets.warn'
          : 'tenant.skills.detail.assessment.items.secrets.pass'
      ),
    },
    {
      id: 'hiddenCharacters',
      group: 'p0',
      status: hasHiddenCharacters ? 'warn' : 'pass',
      title: t('tenant.skills.detail.assessment.items.hiddenCharacters.title'),
      description: t(
        hasHiddenCharacters
          ? 'tenant.skills.detail.assessment.items.hiddenCharacters.warn'
          : 'tenant.skills.detail.assessment.items.hiddenCharacters.pass'
      ),
    },
    {
      id: 'allowedTools',
      group: 'p1',
      status: hasAllowedTools ? 'pass' : 'warn',
      title: t('tenant.skills.detail.assessment.items.allowedTools.title'),
      description: t(
        hasAllowedTools
          ? 'tenant.skills.detail.assessment.items.allowedTools.pass'
          : 'tenant.skills.detail.assessment.items.allowedTools.warn'
      ),
    },
    {
      id: 'packageFiles',
      group: 'p1',
      status: previewFiles.length > 0 ? 'pass' : 'warn',
      title: t('tenant.skills.detail.assessment.items.packageFiles.title'),
      description: t('tenant.skills.detail.assessment.items.packageFiles.pass', {
        count: previewFiles.length,
      }),
    },
    {
      id: 'metadata',
      group: 'p1',
      status: hasMetadata ? 'pass' : 'warn',
      title: t('tenant.skills.detail.assessment.items.metadata.title'),
      description: t(
        hasMetadata
          ? 'tenant.skills.detail.assessment.items.metadata.pass'
          : 'tenant.skills.detail.assessment.items.metadata.warn'
      ),
    },
    {
      id: 'versioning',
      group: 'p2',
      status: hasVersionSnapshot ? 'pass' : 'warn',
      title: t('tenant.skills.detail.assessment.items.versioning.title'),
      description: t(
        hasVersionSnapshot
          ? 'tenant.skills.detail.assessment.items.versioning.pass'
          : 'tenant.skills.detail.assessment.items.versioning.warn'
      ),
    },
    {
      id: 'documentation',
      group: 'p2',
      status: hasBundledFiles ? 'pass' : 'warn',
      title: t('tenant.skills.detail.assessment.items.documentation.title'),
      description: t(
        hasBundledFiles
          ? 'tenant.skills.detail.assessment.items.documentation.pass'
          : 'tenant.skills.detail.assessment.items.documentation.warn'
      ),
    },
    {
      id: 'licenseCompatibility',
      group: 'p2',
      status: hasLicense && hasCompatibility ? 'pass' : 'warn',
      title: t('tenant.skills.detail.assessment.items.licenseCompatibility.title'),
      description: t(
        hasLicense && hasCompatibility
          ? 'tenant.skills.detail.assessment.items.licenseCompatibility.pass'
          : 'tenant.skills.detail.assessment.items.licenseCompatibility.warn'
      ),
    },
  ];

  const groups = (['p0', 'p1', 'p2'] as const).map((group) => {
    const groupItems = items.filter((item) => item.group === group);
    return {
      group,
      passed: groupItems.filter((item) => item.status === 'pass').length,
      total: groupItems.length,
    };
  });
  const status = items.some((item) => item.status === 'warn') ? 'attention' : 'safe';
  const generatedAt = formatDate(skill.updated_at);
  const text = [
    t('tenant.skills.detail.assessment.reportTitle'),
    `${t('tenant.skills.detail.assessment.reportSkill')}: ${skill.name}`,
    `${t('tenant.skills.detail.assessment.reportGeneratedAt')}: ${generatedAt}`,
    `${t('tenant.skills.detail.assessment.reportStatus')}: ${t(
      `tenant.skills.detail.assessment.status.${status}`
    )}`,
    '',
    ...groups.map(
      (group) =>
        `${t(`tenant.skills.detail.assessment.groups.${group.group}`)}: ${String(
          group.passed
        )}/${String(group.total)}`
    ),
    '',
    ...items.map(
      (item) =>
        `[${t(`tenant.skills.detail.assessment.itemStatus.${item.status}`)}] ${item.title}: ${
          item.description
        }`
    ),
  ].join('\n');

  return {
    status,
    generatedAt,
    items,
    groups,
    text,
  };
}

function InfoRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="grid gap-1 border-b border-[oklch(0.9_0.006_255)] py-3 last:border-b-0 dark:border-[oklch(0.28_0.006_255)] sm:grid-cols-[140px_minmax(0,1fr)]">
      <div className={`text-xs font-medium uppercase tracking-normal ${mutedText}`}>{label}</div>
      <div
        className={`min-w-0 break-words text-sm ${pageText} ${
          mono ? 'font-mono text-xs leading-5' : ''
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function getSkillSource(skill: SkillResponse): SkillSource {
  return skill.source ?? 'database';
}

function isManagedSkill(skill: SkillResponse): boolean {
  const source = getSkillSource(skill);
  return !skill.is_system_skill && (source === 'database' || source === 'hybrid');
}

function getSkillListPath(pathname: string): string {
  const segments = pathname.split('/').filter(Boolean);
  const skillsIndex = segments.lastIndexOf('skills');

  if (skillsIndex === -1) {
    return '/tenant/skills';
  }

  return `/${segments.slice(0, skillsIndex + 1).join('/')}`;
}

function SkillContentViewer({
  content,
  mode,
  flush = false,
}: {
  content: string;
  mode: SkillContentMode;
  flush?: boolean;
}) {
  const { remarkPlugins, rehypePlugins } = useMarkdownPlugins(content);

  if (mode === 'raw') {
    return (
      <pre
        className={
          flush
            ? 'min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words p-8 font-mono text-sm leading-7 text-[oklch(0.22_0.01_255)] dark:text-[oklch(0.9_0.006_255)]'
            : 'mt-4 max-h-[520px] overflow-auto rounded-[4px] border border-[oklch(0.88_0.006_255)] bg-[oklch(0.96_0.004_255)] p-4 text-xs leading-5 text-[oklch(0.24_0.01_255)] dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.14_0.006_255)] dark:text-[oklch(0.88_0.006_255)]'
        }
      >
        {content}
      </pre>
    );
  }

  return (
    <div
      className={`${
        flush
          ? 'min-h-0 flex-1 overflow-auto bg-white p-8 text-[15px] leading-7 dark:bg-[oklch(0.14_0.006_255)]'
          : 'mt-4 max-h-[520px] overflow-auto rounded-[4px] border border-[oklch(0.88_0.006_255)] bg-white p-4 text-sm dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.14_0.006_255)]'
      } text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.88_0.006_255)] ${MARKDOWN_PROSE_CLASSES}`}
    >
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={safeMarkdownComponents}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function SkillPreviewTreeItem({
  node,
  depth,
  expandedFolders,
  selectedFilePath,
  onToggleFolder,
  onSelectFile,
}: {
  node: SkillPreviewTreeNode;
  depth: number;
  expandedFolders: Set<string>;
  selectedFilePath: string;
  onToggleFolder: (path: string) => void;
  onSelectFile: (path: string) => void;
}) {
  const indent = depth * 14;

  if (node.type === 'directory') {
    const expanded = expandedFolders.has(node.path);
    return (
      <div>
        <button
          type="button"
          onClick={() => {
            onToggleFolder(node.path);
          }}
          className={`flex h-8 w-full min-w-0 items-center gap-1.5 rounded-[4px] py-1.5 pr-2 text-left text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] ${mutedText} hover:bg-white/70 hover:text-[oklch(0.24_0.01_255)] dark:hover:bg-[oklch(0.22_0.006_255)] dark:hover:text-[oklch(0.94_0.006_255)]`}
          style={{ paddingLeft: indent + 6 }}
          aria-expanded={expanded}
        >
          <ChevronRight
            size={13}
            className={`shrink-0 transition-transform ${expanded ? 'rotate-90' : ''}`}
          />
          {expanded ? (
            <FolderOpen size={14} className="shrink-0" />
          ) : (
            <Folder size={14} className="shrink-0" />
          )}
          <span className="min-w-0 truncate" title={node.path}>
            {node.name}
          </span>
        </button>
        {expanded ? (
          <div>
            {node.children.map((child) => (
              <SkillPreviewTreeItem
                key={child.type === 'directory' ? child.path : child.file.path}
                node={child}
                depth={depth + 1}
                expandedFolders={expandedFolders}
                selectedFilePath={selectedFilePath}
                onToggleFolder={onToggleFolder}
                onSelectFile={onSelectFile}
              />
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  const active = selectedFilePath === node.file.path;
  const fileName = node.file.path.split('/').pop() ?? node.file.path;
  return (
    <button
      type="button"
      onClick={() => {
        onSelectFile(node.file.path);
      }}
      className={`flex h-8 w-full min-w-0 items-center gap-2 rounded-[4px] py-1.5 pr-2 text-left text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] ${
        active
          ? 'bg-white text-[oklch(0.24_0.01_255)] shadow-sm dark:bg-[oklch(0.24_0.006_255)] dark:text-[oklch(0.94_0.006_255)]'
          : 'text-[oklch(0.48_0.01_255)] hover:bg-white/70 hover:text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.68_0.008_255)] dark:hover:bg-[oklch(0.22_0.006_255)] dark:hover:text-[oklch(0.94_0.006_255)]'
      }`}
      style={{ paddingLeft: indent + 25 }}
      title={node.file.path}
    >
      <FileText size={14} className="shrink-0" />
      <span className="min-w-0 truncate">{fileName}</span>
    </button>
  );
}

function EvolutionRouteRow({
  entry,
  isProcessing,
  onApply,
  onReject,
}: {
  entry: SkillEvolutionRouteEntry;
  isProcessing: boolean;
  onApply: (jobId: string) => void;
  onReject: (jobId: string) => void;
}) {
  const isVersion = entry.kind === 'version';
  const { t } = useTranslation();
  const actionable = entry.kind === 'evolution_job' && entry.status === 'pending_review';
  return (
    <div className="py-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div
            className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[4px] ${
              isVersion
                ? 'bg-[oklch(0.9_0.08_145)] text-[oklch(0.35_0.1_145)] dark:bg-[oklch(0.24_0.05_145)] dark:text-[oklch(0.78_0.09_145)]'
                : 'bg-[oklch(0.91_0.05_255)] text-[oklch(0.38_0.1_255)] dark:bg-[oklch(0.24_0.04_255)] dark:text-[oklch(0.76_0.08_255)]'
            }`}
          >
            {isVersion ? <History size={15} /> : <GitBranch size={15} />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`text-sm font-semibold ${pageText}`}>{entry.label}</span>
              <Tag>{isVersion ? 'version' : entry.action}</Tag>
              {entry.status ? (
                <Tag color={entry.status === 'applied' ? 'success' : 'default'}>{entry.status}</Tag>
              ) : null}
            </div>
            {entry.change_summary || entry.rationale ? (
              <div className={`mt-1 text-sm ${mutedText}`}>
                {entry.change_summary ?? entry.rationale}
              </div>
            ) : null}
            <div className={`mt-1 text-xs ${mutedText}`}>
              {entry.created_by ? `${entry.created_by} · ` : ''}
              {formatDate(entry.created_at)}
            </div>
            {entry.candidate_preview ? (
              <pre className="mt-2 max-h-36 overflow-auto rounded-[4px] border border-[oklch(0.88_0.006_255)] bg-[oklch(0.96_0.004_255)] p-3 text-xs leading-5 text-[oklch(0.28_0.01_255)] dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.14_0.006_255)] dark:text-[oklch(0.84_0.006_255)]">
                {entry.candidate_preview}
              </pre>
            ) : null}
          </div>
        </div>
        {actionable ? (
          <div className="flex shrink-0 gap-2">
            <button
              type="button"
              onClick={() => {
                onApply(entry.id);
              }}
              disabled={isProcessing}
              className={actionButton}
            >
              <CheckCircle2 size={14} />
              {t('tenant.skillEvolution.jobs.apply')}
            </button>
            <button
              type="button"
              onClick={() => {
                onReject(entry.id);
              }}
              disabled={isProcessing}
              className={actionButton}
            >
              <XCircle size={14} />
              {t('tenant.skillEvolution.jobs.reject')}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export const SkillDetail: FC = () => {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams<{ skillId: string }>();
  const message = useLazyMessage();
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const tenantId = currentTenant?.id ?? null;
  const skillId = params.skillId;
  const translate = useCallback(
    (key: string, options?: Record<string, unknown>) => {
      return options ? t(key, options) : t(key);
    },
    [t]
  );

  const [skill, setSkill] = useState<SkillResponse | null>(null);
  const [versions, setVersions] = useState<SkillVersionResponse[]>([]);
  const [evolution, setEvolution] = useState<SkillEvolutionDetailResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isEvolutionRunning, setIsEvolutionRunning] = useState(false);
  const [processingEvolutionJobId, setProcessingEvolutionJobId] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [rollbackVersion, setRollbackVersion] = useState<number | null>(null);
  const [contentMode, setContentMode] = useState<SkillContentMode>('preview');
  const [detailMode, setDetailMode] = useState<SkillDetailMode>('preview');
  const [resourceFiles, setResourceFiles] = useState<Record<string, string>>({});
  const [packageSkillContent, setPackageSkillContent] = useState('');
  const [selectedFilePath, setSelectedFilePath] = useState('SKILL.md');
  const [expandedPreviewFolders, setExpandedPreviewFolders] = useState<Set<string>>(new Set());
  const [isLoadingPackageFiles, setIsLoadingPackageFiles] = useState(false);

  const metadataText = useMemo(() => jsonBlock(skill?.metadata), [skill?.metadata]);
  const allowedToolsRaw = skill?.allowed_tools_raw ?? skill?.tools.join(' ') ?? '';
  const skillScope = skill ? t(`tenant.skills.detail.scopeValues.${skill.scope}`) : '';
  const skillSource = skill ? getSkillSource(skill) : 'database';
  const managed = skill ? isManagedSkill(skill) : false;
  const skillListPath = useMemo(() => getSkillListPath(location.pathname), [location.pathname]);
  const previewFiles = useMemo<SkillPreviewFile[]>(() => {
    const skillContent = packageSkillContent || skill?.full_content || '';
    return [
      {
        path: 'SKILL.md',
        content: skillContent,
        kind: 'markdown',
      },
      ...Object.entries(resourceFiles)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([path, content]) => ({
          path,
          content,
          kind: getPreviewFileKind(path),
        })),
    ];
  }, [packageSkillContent, resourceFiles, skill?.full_content]);
  const selectedPreviewFile = useMemo(() => {
    return previewFiles.find((file) => file.path === selectedFilePath) ?? previewFiles[0];
  }, [previewFiles, selectedFilePath]);
  const previewFileTree = useMemo(() => buildPreviewFileTree(previewFiles), [previewFiles]);
  const assessmentReport = useMemo(() => {
    if (!skill) {
      return null;
    }
    return buildAssessmentReport({
      skill,
      previewFiles,
      versions,
      t: translate,
    });
  }, [previewFiles, skill, translate, versions]);

  const loadSkill = useCallback(async () => {
    if (!skillId) {
      setIsLoading(false);
      return;
    }
    if (!tenantId) {
      return;
    }

    setIsLoading(true);
    setIsLoadingPackageFiles(true);
    try {
      const nextSkill = await skillAPI.get(skillId, { tenant_id: tenantId });
      setSkill(nextSkill);
      setPackageSkillContent(nextSkill.full_content ?? '');
      setResourceFiles({});
      setSelectedFilePath('SKILL.md');

      try {
        const exportId = getSkillSource(nextSkill) === 'filesystem' ? nextSkill.name : nextSkill.id;
        const exported = await skillAPI.exportPackage(exportId, { tenant_id: tenantId });
        setPackageSkillContent(exported.skill_md_content);
        setResourceFiles(
          Object.fromEntries(
            Object.entries(exported.resource_files ?? {}).map(([path, value]) => [
              path,
              stringifyResourceFile(value),
            ])
          )
        );
      } catch {
        setResourceFiles({});
      } finally {
        setIsLoadingPackageFiles(false);
      }

      if (!isManagedSkill(nextSkill)) {
        setVersions([]);
        setEvolution(null);
      } else {
        try {
          const [versionResult, evolutionResult] = await Promise.all([
            skillAPI.listVersions(nextSkill.id, { tenant_id: tenantId }),
            skillAPI.getEvolution(nextSkill.id, { tenant_id: tenantId }),
          ]);
          setVersions(versionResult.versions);
          setEvolution(evolutionResult);
        } catch {
          setVersions([]);
          setEvolution(null);
          message?.error(t('tenant.skills.detail.versionLoadFailed'));
        }
      }
    } catch {
      setSkill(null);
      setPackageSkillContent('');
      setResourceFiles({});
      message?.error(t('tenant.skills.detail.loadFailed'));
    } finally {
      setIsLoading(false);
      setIsLoadingPackageFiles(false);
    }
  }, [message, skillId, tenantId, t]);

  useEffect(() => {
    void loadSkill();
  }, [loadSkill]);

  useEffect(() => {
    setExpandedPreviewFolders(new Set(getPreviewDirectoryPaths(previewFileTree)));
  }, [previewFileTree]);

  const handleTogglePreviewFolder = useCallback((path: string) => {
    setExpandedPreviewFolders((current) => {
      const next = new Set(current);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const handleExport = useCallback(async () => {
    if (!skill || !tenantId) {
      return;
    }
    try {
      const exportId = getSkillSource(skill) === 'filesystem' ? skill.name : skill.id;
      const exported = await skillAPI.exportPackage(exportId, { tenant_id: tenantId });
      const blob = new Blob([JSON.stringify(exported, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${skill.name}.agentskill.json`;
      link.click();
      URL.revokeObjectURL(url);
      message?.success(t('tenant.skills.detail.exportSuccess'));
    } catch {
      message?.error(t('tenant.skills.detail.exportFailed'));
    }
  }, [message, skill, tenantId, t]);

  const handleCopyAssessmentReport = useCallback(async () => {
    if (!assessmentReport) {
      return;
    }
    try {
      await navigator.clipboard.writeText(assessmentReport.text);
      message?.success(t('tenant.skills.detail.assessment.copySuccess'));
    } catch {
      message?.error(t('tenant.skills.detail.assessment.copyFailed'));
    }
  }, [assessmentReport, message, t]);

  const handleRollback = useCallback(
    async (versionNumber: number) => {
      if (!skill || !tenantId) {
        return;
      }
      if (!isManagedSkill(skill)) {
        message?.info(t('tenant.skills.detail.readOnlySource'));
        return;
      }
      setRollbackVersion(versionNumber);
      try {
        await skillAPI.rollback(skill.id, versionNumber, { tenant_id: tenantId });
        message?.success(t('tenant.skills.detail.rollbackSuccess'));
        await loadSkill();
      } catch {
        message?.error(t('tenant.skills.detail.rollbackFailed'));
      } finally {
        setRollbackVersion(null);
      }
    },
    [loadSkill, message, skill, tenantId, t]
  );

  const handleRunEvolution = useCallback(async () => {
    if (!skill || !managed || !tenantId) {
      return;
    }
    setIsEvolutionRunning(true);
    try {
      await skillAPI.runEvolution(skill.id, { tenant_id: tenantId });
      message?.success(t('tenant.skills.detail.evolutionRunSuccess'));
      await loadSkill();
    } catch {
      message?.error(t('tenant.skills.detail.evolutionRunFailed'));
    } finally {
      setIsEvolutionRunning(false);
    }
  }, [loadSkill, managed, message, skill, tenantId, t]);

  const handleApplyEvolutionJob = useCallback(
    async (jobId: string) => {
      if (!tenantId) {
        return;
      }

      setProcessingEvolutionJobId(jobId);
      try {
        await skillAPI.applyEvolutionJob(jobId, { tenant_id: tenantId });
        message?.success(t('tenant.skillEvolution.jobs.applySuccess'));
        await loadSkill();
      } catch {
        message?.error(t('tenant.skillEvolution.jobs.applyFailed'));
      } finally {
        setProcessingEvolutionJobId(null);
      }
    },
    [loadSkill, message, tenantId, t]
  );

  const handleRejectEvolutionJob = useCallback(
    async (jobId: string) => {
      if (!tenantId) {
        return;
      }

      setProcessingEvolutionJobId(jobId);
      try {
        await skillAPI.rejectEvolutionJob(jobId, { tenant_id: tenantId });
        message?.success(t('tenant.skillEvolution.jobs.rejectSuccess'));
        await loadSkill();
      } catch {
        message?.error(t('tenant.skillEvolution.jobs.rejectFailed'));
      } finally {
        setProcessingEvolutionJobId(null);
      }
    },
    [loadSkill, message, tenantId, t]
  );

  const handleModalSuccess = useCallback(() => {
    setIsModalOpen(false);
    void loadSkill();
  }, [loadSkill]);

  if (isLoading) {
    return (
      <div
        className={`mx-auto flex w-full max-w-7xl justify-center rounded-[6px] py-16 ${surface}`}
      >
        <LazySpin size="large" />
      </div>
    );
  }

  if (!skill) {
    return (
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
        <button
          type="button"
          onClick={() => {
            void navigate(skillListPath);
          }}
          className={actionButton}
        >
          <ArrowLeft size={16} />
          {t('tenant.skills.detail.back')}
        </button>
        <Alert type="warning" title={t('tenant.skills.detail.notFound')} showIcon />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <button
            type="button"
            onClick={() => {
              void navigate(skillListPath);
            }}
            className={`mb-3 inline-flex h-8 items-center gap-2 text-sm font-medium ${mutedText} hover:text-[oklch(0.24_0.01_255)] dark:hover:text-[oklch(0.94_0.006_255)]`}
          >
            <ArrowLeft size={16} />
            {t('tenant.skills.detail.back')}
          </button>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className={`truncate text-2xl font-semibold leading-8 tracking-normal ${pageText}`}>
              {skill.name}
            </h1>
            <Tag color={skill.status === 'active' ? 'success' : 'default'}>
              {t(`common.status.${skill.status}`)}
            </Tag>
            <Tag>{skillScope}</Tag>
            <Tag>{t(`tenant.skills.source.${skillSource}`)}</Tag>
            {skill.version_label ? <Tag>{skill.version_label}</Tag> : null}
          </div>
          <p className={`mt-2 max-w-3xl text-sm ${mutedText}`}>{skill.description}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => {
              void loadSkill();
            }}
            className={actionButton}
          >
            <RefreshCw size={16} />
            {t('tenant.skills.detail.refresh')}
          </button>
          <button
            type="button"
            onClick={() => {
              setIsModalOpen(true);
            }}
            className={actionButton}
            disabled={!managed}
          >
            <Pencil size={16} />
            {t('tenant.skills.detail.edit')}
          </button>
          <button
            type="button"
            onClick={() => {
              void handleExport();
            }}
            className={actionButton}
          >
            <Download size={16} />
            {t('tenant.skills.detail.export')}
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div
          className="inline-flex w-fit rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-[oklch(0.97_0.004_255)] p-0.5 dark:border-[oklch(0.34_0.006_255)] dark:bg-[oklch(0.2_0.006_255)]"
          role="group"
          aria-label={t('tenant.skills.detail.viewMode')}
        >
          {(
            [
              { key: 'preview' as const, icon: Eye },
              { key: 'manage' as const, icon: Wrench },
              { key: 'report' as const, icon: ClipboardList },
            ] satisfies Array<{ key: SkillDetailMode; icon: typeof Eye }>
          ).map(({ key, icon: Icon }) => {
            const active = detailMode === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setDetailMode(key);
                }}
                className={`inline-flex h-8 items-center gap-1.5 rounded-[3px] px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] ${
                  active
                    ? 'bg-white text-[oklch(0.24_0.01_255)] shadow-sm dark:bg-[oklch(0.28_0.006_255)] dark:text-[oklch(0.94_0.006_255)]'
                    : 'text-[oklch(0.48_0.01_255)] hover:text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.68_0.008_255)] dark:hover:text-[oklch(0.94_0.006_255)]'
                }`}
                aria-pressed={active}
              >
                <Icon size={14} />
                {t(`tenant.skills.detail.viewModes.${key}`)}
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-5">
          {detailMode === 'preview' ? (
            <>
              <section className={`rounded-[6px] p-5 ${surface}`}>
                <div className="flex items-center gap-2">
                  <Wrench size={17} className={mutedText} />
                  <h2 className={`text-sm font-semibold ${pageText}`}>
                    {t('tenant.skills.detail.package')}
                  </h2>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {skill.tools.map((tool) => (
                    <Tag key={tool}>{tool}</Tag>
                  ))}
                </div>
                <div className="mt-4">
                  <InfoRow
                    label={t('tenant.skills.detail.allowedToolsRaw')}
                    value={allowedToolsRaw || t('tenant.skills.detail.notSet')}
                  />
                  <InfoRow
                    label={t('tenant.skills.detail.license')}
                    value={skill.license || t('tenant.skills.detail.notSet')}
                  />
                  <InfoRow
                    label={t('tenant.skills.detail.compatibility')}
                    value={skill.compatibility || t('tenant.skills.detail.notSet')}
                  />
                  <InfoRow
                    label={t('tenant.skills.detail.specVersion')}
                    value={skill.spec_version}
                  />
                </div>
              </section>

              <section className={`overflow-hidden rounded-[8px] p-0 ${surface}`}>
                <div className="flex min-h-12 items-center justify-between gap-3 border-b border-[oklch(0.9_0.006_255)] bg-[oklch(0.985_0.003_255)] px-5 dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.17_0.006_255)]">
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="flex shrink-0 items-center gap-2">
                      <FileText size={17} className={mutedText} />
                      <h2 className={`text-sm font-semibold ${pageText}`}>
                        {t('tenant.skills.detail.files')}
                      </h2>
                    </div>
                    <span className="h-4 w-px shrink-0 bg-[oklch(0.86_0.006_255)] dark:bg-[oklch(0.32_0.006_255)]" />
                    <div className={`min-w-0 truncate text-sm font-medium ${pageText}`}>
                      {skill.name}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {selectedPreviewFile?.kind === 'markdown' ? (
                      <div
                        className="inline-flex w-fit rounded-[4px] border border-[oklch(0.86_0.006_255)] bg-[oklch(0.97_0.004_255)] p-0.5 dark:border-[oklch(0.34_0.006_255)] dark:bg-[oklch(0.2_0.006_255)]"
                        role="group"
                        aria-label={t('tenant.skills.detail.contentMode')}
                      >
                        {(
                          [
                            { key: 'preview' as const, icon: Eye },
                            { key: 'raw' as const, icon: Code2 },
                          ] satisfies Array<{ key: SkillContentMode; icon: typeof Eye }>
                        ).map(({ key, icon: Icon }) => {
                          const active = contentMode === key;
                          return (
                            <button
                              key={key}
                              type="button"
                              onClick={() => {
                                setContentMode(key);
                              }}
                              className={`inline-flex h-8 items-center gap-1.5 rounded-[3px] px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] ${
                                active
                                  ? 'bg-white text-[oklch(0.24_0.01_255)] shadow-sm dark:bg-[oklch(0.28_0.006_255)] dark:text-[oklch(0.94_0.006_255)]'
                                  : 'text-[oklch(0.48_0.01_255)] hover:text-[oklch(0.24_0.01_255)] dark:text-[oklch(0.68_0.008_255)] dark:hover:text-[oklch(0.94_0.006_255)]'
                              }`}
                              aria-pressed={active}
                            >
                              <Icon size={14} />
                              {t(`tenant.skills.detail.contentModes.${key}`)}
                            </button>
                          );
                        })}
                      </div>
                    ) : null}
                    <button
                      type="button"
                      onClick={() => {
                        void handleExport();
                      }}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-[4px] text-[oklch(0.52_0.012_255)] transition-colors hover:bg-[oklch(0.93_0.005_255)] hover:text-[oklch(0.24_0.01_255)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[oklch(0.62_0.16_255_/_0.28)] dark:text-[oklch(0.7_0.008_255)] dark:hover:bg-[oklch(0.24_0.006_255)] dark:hover:text-[oklch(0.94_0.006_255)]"
                      aria-label={t('tenant.skills.detail.export')}
                      title={t('tenant.skills.detail.export')}
                    >
                      <Download size={17} />
                    </button>
                  </div>
                </div>
                {isLoadingPackageFiles ? (
                  <div className="mt-4 flex justify-center py-10">
                    <LazySpin />
                  </div>
                ) : selectedPreviewFile ? (
                  <div className="grid h-[760px] items-stretch lg:grid-cols-[310px_minmax(0,1fr)]">
                    <div className="flex min-h-0 flex-col border-r border-[oklch(0.9_0.006_255)] bg-white p-4 dark:border-[oklch(0.28_0.006_255)] dark:bg-[oklch(0.14_0.006_255)]">
                      <div className={`px-1 pb-3 text-xs font-medium ${mutedText}`}>
                        {t('tenant.skills.detail.packageFiles', {
                          count: previewFiles.length,
                        })}
                      </div>
                      <div className="min-h-0 flex-1 space-y-1 overflow-auto pr-1">
                        {previewFileTree.map((node) => (
                          <SkillPreviewTreeItem
                            key={node.type === 'directory' ? node.path : node.file.path}
                            node={node}
                            depth={0}
                            expandedFolders={expandedPreviewFolders}
                            selectedFilePath={selectedPreviewFile.path}
                            onToggleFolder={handleTogglePreviewFolder}
                            onSelectFile={setSelectedFilePath}
                          />
                        ))}
                      </div>
                    </div>
                    <div className="flex min-h-0 min-w-0 flex-col bg-white dark:bg-[oklch(0.14_0.006_255)]">
                      <div className="flex min-h-11 items-center justify-between gap-3 border-b border-[oklch(0.9_0.006_255)] px-6 dark:border-[oklch(0.28_0.006_255)]">
                        <div
                          className={`min-w-0 truncate font-mono text-xs font-semibold ${pageText}`}
                          title={selectedPreviewFile.path}
                        >
                          {selectedPreviewFile.path}
                        </div>
                        <span className={`shrink-0 text-xs ${mutedText}`}>
                          {selectedPreviewFile.kind === 'markdown'
                            ? t('tenant.skills.detail.fileKinds.markdown')
                            : t('tenant.skills.detail.fileKinds.text')}
                        </span>
                      </div>
                      <SkillContentViewer
                        content={selectedPreviewFile.content}
                        mode={selectedPreviewFile.kind === 'markdown' ? contentMode : 'raw'}
                        flush
                      />
                    </div>
                  </div>
                ) : (
                  <div className="mt-4 py-8">
                    <LazyEmpty description={t('tenant.skills.detail.emptyContent')} />
                  </div>
                )}
              </section>
            </>
          ) : detailMode === 'manage' ? (
            <>
              <section className={`rounded-[6px] p-5 ${surface}`}>
                <div className="flex items-center gap-2">
                  <KeyRound size={17} className={mutedText} />
                  <h2 className={`text-sm font-semibold ${pageText}`}>
                    {t('tenant.skills.detail.metadata')}
                  </h2>
                </div>
                <pre className="mt-4 max-h-[360px] overflow-auto rounded-[4px] border border-[oklch(0.88_0.006_255)] bg-[oklch(0.96_0.004_255)] p-4 text-xs leading-5 text-[oklch(0.24_0.01_255)] dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.14_0.006_255)] dark:text-[oklch(0.88_0.006_255)]">
                  {metadataText}
                </pre>
              </section>

              <section className={`rounded-[6px] p-5 ${surface}`}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex items-center gap-2">
                    <GitBranch size={17} className={mutedText} />
                    <h2 className={`text-sm font-semibold ${pageText}`}>
                      {t('tenant.skills.detail.evolutionRoute')}
                    </h2>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      void handleRunEvolution();
                    }}
                    className={actionButton}
                    disabled={!managed || isEvolutionRunning}
                  >
                    <Play size={16} />
                    {isEvolutionRunning
                      ? t('tenant.skills.detail.evolutionRunning')
                      : t('tenant.skills.detail.runEvolution')}
                  </button>
                </div>
                {evolution ? (
                  <div className="mt-4 grid gap-4">
                    <div className="grid gap-3 sm:grid-cols-3">
                      <InfoRow
                        label={t('tenant.skills.detail.capturedSessions')}
                        value={evolution.captured_session_count}
                      />
                      <InfoRow
                        label={t('tenant.skills.detail.triggerHook')}
                        value={evolution.trigger.capture_hook}
                        mono
                      />
                      <InfoRow
                        label={t('tenant.skills.detail.evolutionThreshold')}
                        value={`${String(evolution.trigger.min_sessions_per_skill)} / ${String(
                          evolution.trigger.min_avg_score
                        )}`}
                      />
                    </div>
                    <div className={`text-sm ${mutedText}`}>
                      {evolution.trigger.capture_timing}
                      <br />
                      {evolution.trigger.scheduled_timing}
                    </div>
                    {evolution.route.length === 0 ? (
                      <LazyEmpty description={t('tenant.skills.detail.emptyEvolutionRoute')} />
                    ) : (
                      <div className="divide-y divide-[oklch(0.9_0.006_255)] dark:divide-[oklch(0.28_0.006_255)]">
                        {evolution.route.map((entry) => (
                          <EvolutionRouteRow
                            key={`${entry.kind}-${entry.id}`}
                            entry={entry}
                            isProcessing={processingEvolutionJobId === entry.id}
                            onApply={(jobId) => {
                              void handleApplyEvolutionJob(jobId);
                            }}
                            onReject={(jobId) => {
                              void handleRejectEvolutionJob(jobId);
                            }}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="mt-4 py-8">
                    <LazyEmpty
                      description={
                        managed
                          ? t('tenant.skills.detail.emptyEvolutionRoute')
                          : t('tenant.skills.detail.notVersioned')
                      }
                    />
                  </div>
                )}
              </section>
            </>
          ) : assessmentReport ? (
            <>
              <section className={`rounded-[6px] p-5 ${surface}`}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="flex items-start gap-3">
                    <div
                      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-[6px] border ${getAssessmentItemClasses(
                        assessmentReport.status === 'safe' ? 'pass' : 'warn'
                      )}`}
                    >
                      <ShieldCheck size={18} />
                    </div>
                    <div>
                      <h2 className={`text-sm font-semibold ${pageText}`}>
                        {t('tenant.skills.detail.assessment.title')}
                      </h2>
                      <p className={`mt-1 max-w-2xl text-sm leading-6 ${mutedText}`}>
                        {t('tenant.skills.detail.assessment.description')}
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      void handleCopyAssessmentReport();
                    }}
                    className={actionButton}
                  >
                    <Copy size={16} />
                    {t('tenant.skills.detail.assessment.copy')}
                  </button>
                </div>

                <div className="mt-5 grid gap-3 sm:grid-cols-3">
                  {assessmentReport.groups.map((group) => (
                    <div
                      key={group.group}
                      className="rounded-[6px] border border-[oklch(0.88_0.006_255)] bg-white p-4 dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.14_0.006_255)]"
                    >
                      <div className={`text-xs font-medium uppercase tracking-normal ${mutedText}`}>
                        {t(`tenant.skills.detail.assessment.groups.${group.group}`)}
                      </div>
                      <div className={`mt-2 text-2xl font-semibold ${pageText}`}>
                        {group.passed}/{group.total}
                      </div>
                      <div className={`mt-1 text-xs ${mutedText}`}>
                        {t('tenant.skills.detail.assessment.groupPassed')}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="mt-5 rounded-[6px] border border-[oklch(0.88_0.006_255)] bg-[oklch(0.97_0.004_255)] p-4 dark:border-[oklch(0.3_0.006_255)] dark:bg-[oklch(0.14_0.006_255)]">
                  <div className="flex flex-wrap items-center gap-2">
                    <Tag color={assessmentReport.status === 'safe' ? 'success' : 'warning'}>
                      {t(`tenant.skills.detail.assessment.status.${assessmentReport.status}`)}
                    </Tag>
                    <span className={`text-xs ${mutedText}`}>
                      {t('tenant.skills.detail.assessment.generatedAt', {
                        date: assessmentReport.generatedAt,
                      })}
                    </span>
                  </div>
                  <p className={`mt-3 text-sm leading-6 ${mutedText}`}>
                    {t('tenant.skills.detail.assessment.staticNotice')}
                  </p>
                </div>
              </section>

              <section className={`rounded-[6px] p-5 ${surface}`}>
                <div className="flex items-center gap-2">
                  <ClipboardList size={17} className={mutedText} />
                  <h2 className={`text-sm font-semibold ${pageText}`}>
                    {t('tenant.skills.detail.assessment.details')}
                  </h2>
                </div>
                <div className="mt-4 divide-y divide-[oklch(0.9_0.006_255)] dark:divide-[oklch(0.28_0.006_255)]">
                  {assessmentReport.items.map((item) => (
                    <div key={item.id} className="py-4">
                      <div className="flex items-start gap-3">
                        <div
                          className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[4px] border ${getAssessmentItemClasses(
                            item.status
                          )}`}
                        >
                          {item.status === 'pass' ? (
                            <CheckCircle2 size={15} />
                          ) : (
                            <XCircle size={15} />
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={`text-sm font-semibold ${pageText}`}>
                              {item.title}
                            </span>
                            <Tag>{t(`tenant.skills.detail.assessment.groups.${item.group}`)}</Tag>
                            <Tag color={item.status === 'pass' ? 'success' : 'warning'}>
                              {t(`tenant.skills.detail.assessment.itemStatus.${item.status}`)}
                            </Tag>
                          </div>
                          <p className={`mt-1 text-sm leading-6 ${mutedText}`}>
                            {item.description}
                          </p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </>
          ) : null}
        </div>

        <aside className="flex min-w-0 flex-col gap-5">
          <section className={`rounded-[6px] p-5 ${surface}`}>
            <h2 className={`text-sm font-semibold ${pageText}`}>
              {t('tenant.skills.detail.identity')}
            </h2>
            <div className="mt-3">
              <InfoRow label={t('tenant.skills.detail.id')} value={skill.id} mono />
              <InfoRow
                label={t('tenant.skills.detail.source')}
                value={t(`tenant.skills.source.${skillSource}`)}
              />
              <InfoRow
                label={t('tenant.skills.detail.filePath')}
                value={skill.file_path || t('tenant.skills.detail.notSet')}
                mono={Boolean(skill.file_path)}
              />
              <InfoRow label={t('tenant.skills.detail.scope')} value={skillScope} />
              <InfoRow
                label={t('tenant.skills.detail.project')}
                value={skill.project_id || t('tenant.skills.detail.notSet')}
                mono={Boolean(skill.project_id)}
              />
              <InfoRow
                label={t('tenant.skills.detail.created')}
                value={formatDate(skill.created_at)}
              />
              <InfoRow
                label={t('tenant.skills.detail.updated')}
                value={formatDate(skill.updated_at)}
              />
            </div>
          </section>

          <section className={`rounded-[6px] p-5 ${surface}`}>
            <div className="flex items-center gap-2">
              <History size={17} className={mutedText} />
              <h2 className={`text-sm font-semibold ${pageText}`}>
                {t('tenant.skills.detail.versions')}
              </h2>
            </div>
            {versions.length === 0 ? (
              <div className="py-8">
                <LazyEmpty
                  description={
                    managed
                      ? t('tenant.skills.detail.emptyVersions')
                      : t('tenant.skills.detail.notVersioned')
                  }
                />
              </div>
            ) : (
              <div className="mt-3 divide-y divide-[oklch(0.9_0.006_255)] dark:divide-[oklch(0.28_0.006_255)]">
                {versions.map((version) => {
                  const isCurrent = skill.current_version === version.version_number;
                  return (
                    <div key={version.id} className="py-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={`text-sm font-semibold ${pageText}`}>
                              {version.version_label ?? `#${String(version.version_number)}`}
                            </span>
                            <span className={`text-xs ${mutedText}`}>
                              #{version.version_number}
                            </span>
                            {isCurrent ? (
                              <Tag color="success">{t('tenant.skills.detail.current')}</Tag>
                            ) : null}
                          </div>
                          {version.change_summary ? (
                            <div className={`mt-1 text-sm ${mutedText}`}>
                              {version.change_summary}
                            </div>
                          ) : null}
                          <div className={`mt-1 text-xs ${mutedText}`}>
                            {t('tenant.skills.detail.versionCreatedBy', {
                              author: version.created_by,
                              date: formatDate(version.created_at),
                            })}
                          </div>
                        </div>
                        {!isCurrent ? (
                          <LazyPopconfirm
                            title={t('tenant.skills.detail.rollbackConfirm')}
                            okText={t('common.confirm')}
                            cancelText={t('common.cancel')}
                            onConfirm={() => {
                              void handleRollback(version.version_number);
                            }}
                          >
                            <button
                              type="button"
                              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[4px] text-[oklch(0.48_0.01_255)] transition-colors hover:bg-[oklch(0.95_0.005_255)] hover:text-[oklch(0.26_0.012_255)] disabled:cursor-not-allowed disabled:opacity-60 dark:text-[oklch(0.7_0.008_255)] dark:hover:bg-[oklch(0.24_0.006_255)]"
                              title={t('tenant.skills.detail.rollback')}
                              aria-label={t('tenant.skills.detail.rollback')}
                              disabled={rollbackVersion !== null}
                            >
                              <RotateCcw size={15} />
                            </button>
                          </LazyPopconfirm>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        </aside>
      </div>

      {isModalOpen ? (
        <SkillModal
          isOpen={isModalOpen}
          skill={skill}
          tenantId={tenantId}
          onClose={() => {
            setIsModalOpen(false);
          }}
          onSuccess={handleModalSuccess}
        />
      ) : null}
    </div>
  );
};

export default SkillDetail;
