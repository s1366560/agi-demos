import { Badge, Button, Flex, Text, TextArea, TextField } from '@radix-ui/themes';
import { ArchiveIcon, MagnifyingGlassIcon } from '@radix-ui/react-icons';

import type { LocalMemoryResult } from '../../types';

type MemoryPanelProps = {
  projectId: string;
  content: string;
  query: string;
  tauriAvailable: boolean;
  busy: boolean;
  result: LocalMemoryResult | null;
  onContentChange: (value: string) => void;
  onQueryChange: (value: string) => void;
  onIngest: () => void;
  onSearch: () => void;
  onSemanticSearch: () => void;
};

export function MemoryPanel({
  projectId,
  content,
  query,
  tauriAvailable,
  busy,
  result,
  onContentChange,
  onQueryChange,
  onIngest,
  onSearch,
  onSemanticSearch,
}: MemoryPanelProps) {
  const desktopUnavailable = !tauriAvailable;
  const memoryActionDisabled = busy || desktopUnavailable;
  const backendLabel = result
    ? result.usedFallback
      ? 'desktop required'
      : result.label === 'Error'
        ? 'error'
        : 'desktop mode'
    : tauriAvailable
      ? 'desktop mode'
      : 'desktop required';
  const backendColor: 'red' | 'green' | 'amber' =
    backendLabel === 'error' ? 'red' : backendLabel === 'desktop mode' ? 'green' : 'amber';
  const readyText = desktopUnavailable
    ? 'Open the Tauri desktop app to run local memory commands.'
    : 'Ready.';

  return (
    <section className="memory-panel">
      <Flex align="center" justify="between">
        <Text size="1" color="gray" weight="bold">
          LOCAL MEMORY
        </Text>
        <Badge color={backendColor} variant="soft">
          {backendLabel}
        </Badge>
      </Flex>
      <Text size="1" color="gray">
        {desktopUnavailable
          ? 'Local memory is backed by native Tauri commands and is unavailable in browser preview.'
          : 'Save a note locally, then search it from this desktop session.'}
      </Text>
      <label className="field-label">
        <span>Memory content</span>
        <TextArea
          aria-label="Local memory content"
          value={content}
          onChange={(event) => onContentChange(event.target.value)}
          placeholder="Memory content to ingest locally..."
        />
      </label>
      <Flex gap="2" wrap="wrap">
        <Button
          size="2"
          aria-label="Ingest local memory"
          onClick={onIngest}
          loading={busy}
          disabled={memoryActionDisabled}
        >
          <ArchiveIcon /> Ingest
        </Button>
      </Flex>
      <label className="field-label">
        <span>Search query</span>
        <TextField.Root
          aria-label="Local memory query"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Search local memory"
        />
      </label>
      <Flex gap="2" wrap="wrap">
        <Button
          size="2"
          variant="surface"
          aria-label="Run keyword memory search"
          onClick={onSearch}
          loading={busy}
          disabled={memoryActionDisabled}
        >
          <MagnifyingGlassIcon /> Keyword
        </Button>
        <Button
          size="2"
          variant="surface"
          aria-label="Run semantic memory search"
          onClick={onSemanticSearch}
          loading={busy}
          disabled={memoryActionDisabled}
        >
          Semantic
        </Button>
      </Flex>
      <pre className="json-output">{result ? JSON.stringify(result.data, null, 2) : readyText}</pre>
    </section>
  );
}
