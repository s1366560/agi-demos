import type { MessageFile } from '../web/chat/MessageFileList';
import { uploadAttachment, type UploadedAttachment } from './uploadAttachment';
import { PAGE } from './useInteractions';
import { useEffect, useRef, useState } from 'react';
import type { ExecutionSummary } from '@/types/agent';
import type {
  RichPageContext,
  RichPageRuntime,
} from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';

export type Target = 'cloud' | 'local';
export interface Conversation {
  id: string;
  title: string;
  execution_target: Target;
  workspace_id?: string;
  local_root_label?: string;
  created_at?: string;
  updated_at?: string;
}
export interface Message {
  timestamp?: number;
  eventTimeUs?: number;
  eventCounter?: number;
  files?: MessageFile[];
  /** Steps, calls, tokens and cost of a finished answer. */
  summary?: ExecutionSummary;
  id: string;
  role: 'user_message' | 'assistant_message';
  content: string;
}
/** Reasoning text of a turn, as the history and the turn stream report it. */
export interface Thought {
  id: string;
  content: string;
  timestamp?: number;
  eventTimeUs?: number;
  eventCounter?: number;
  /** Reasoning that streams in has no position yet: it follows the events read when it arrived. */
  after?: [time: number, counter: number];
}
type Cursor = { before_time_us: number; before_counter: number };
type Run =
  | { target: 'cloud'; id: string; revision: number; conversation: string }
  | { target: 'local'; conversation: string; key: string };
const sdk = window.memstack;
const command = <T>(
  name: string,
  payload: Record<string, unknown>,
  options?: Parameters<RichPageRuntime['invoke']>[2]
) => sdk.invoke(name, payload, options) as Promise<T>;

export function useChat(
  scope: RichPageContext,
  /** The last position among the events the page has read, to place streaming reasoning. */
  latest?: () => [number, number] | undefined,
) {
  const local = scope.platform === 'desktop-renderer';
  const hasDevice = local && scope.deviceTools.includes('local_chat');
  const [list, setList] = useState<Conversation[]>([]);
  const query = new URLSearchParams(scope.search);
  const workspace = query.get('workspaceId');
  const segment = scope.pathname.match(/\/(?:agent-workspace|agent\/chat)\/([^/]+)\/?$/)?.[1];
  const linked = query.get('conversationId') || (segment ? decodeURIComponent(segment) : null);
  const [selected, setSelected] = useState(linked ?? '');
  const [messages, setMessages] = useState<Message[]>([]);
  const [thoughts, setThoughts] = useState<Thought[]>([]);
  const [draft, setDraft] = useState('');
  const [files, setFiles] = useState<UploadedAttachment[]>([]);
  const [target, setTarget] = useState<Target>(local ? 'local' : 'cloud');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [run, setRun] = useState<Run>();
  const [cursor, setCursor] = useState<Cursor>();
  const [loading, setLoading] = useState(true);
  // Counts the reads that start a history over, so what was read before them is dropped.
  const [page, setPage] = useState(0);
  const locked = useRef(false),
    reading = useRef(false),
    revision = useRef(0);
  const pending = useRef<{ id: string; text: string; key: string } | null>(null);
  const label = (en: string, zh: string) => (scope.locale.startsWith('zh') ? zh : en);
  const selectedRow = list.find((row) => row.id === selected);
  const writable = !!selectedRow && (selectedRow.execution_target === 'cloud' || hasDevice);
  function report(cause: unknown) {
    const message = cause instanceof Error ? cause.message : String(cause);
    if (message.includes('device_local_workspace_required'))
      setError(
        label(
          'Choose a workspace in device settings before sending.',
          '请先在设备设置中选择工作目录。'
        )
      );
    else if (
      message.includes('device_plugin_installation_required') ||
      message.includes('device_plugin_grant_')
    )
      setError(
        label(
          'Approve this Agent release in device settings. ',
          '请在设备设置中批准当前 Agent 版本。'
        ) + message
      );
    else setError(message);
  }
  const heading = label('New conversation', '新会话');

  async function read(
    id: string,
    before?: Cursor,
    targetForRead = list.find((row) => row.id === id)?.execution_target
  ) {
    const version = ++revision.current;
    setLoading(true);
    try {
      const page = await command<{
        messages: Message[];
        thoughts?: Thought[];
        before?: Cursor;
      }>('chat-history', {
        conversation_id: id,
        limit: PAGE,
        ...before,
      });
      const renderingFiles =
        targetForRead === 'cloud' &&
        scope.commands.includes('chat-interactions') &&
        page.messages.some((row) => row.role === 'user_message');
      const recorded = renderingFiles
        ? (
            await command<{ attachments: Record<string, MessageFile[]> }>('chat-interactions', {
              conversation_id: id,
              limit: PAGE,
              ...before,
              view: 'attachments',
            })
          ).attachments
        : {};
      if (version !== revision.current) return;
      if (!before) setPage((count) => count + 1);
      const rows = page.messages.map((row) => ({
        ...row,
        id: row.id ?? crypto.randomUUID(),
        files: recorded[row.id] ?? [],
      }));
      setMessages((old) => (before ? [...rows, ...old] : rows));
      setThoughts((old) => (before ? [...(page.thoughts ?? []), ...old] : (page.thoughts ?? [])));
      // Deleted history can leave an earlier page with nothing to show. That page ends
      // the history, so the transcript stops offering it.
      const emptied = !!before && !rows.length && !(page.thoughts ?? []).length;
      setCursor(emptied ? undefined : page.before);
    } finally {
      if (version === revision.current) setLoading(false);
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    void command<{ items: Conversation[] }>(
      'chat-list',
      {
        workbench: true,
        ...(linked ? { conversation_id: linked } : {}),
        ...(workspace ? { workspace_id: workspace } : {}),
      },
      { signal: controller.signal }
    )
      .then(({ items }) => {
        if (controller.signal.aborted) return;
        setList(items);
        if (linked && !items.some((row) => row.id === linked))
          throw new Error('conversation_unavailable');
        const id = linked;
        if (id) {
          setSelected(id);
          return read(id, undefined, items.find((row) => row.id === id)?.execution_target);
        }
        setLoading(false);
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          setLoading(false);
          report(err);
        }
      });
    return () => {
      controller.abort();
      revision.current++;
    };
  }, [linked, workspace, scope.projectId, scope.tenantId]);

  async function perform(action: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      report(e);
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  async function createRow() {
    const row = await command<Conversation>('chat-create', {
      title: heading,
      ...(workspace ? { workspace_id: workspace } : {}),
      ...(local && target === 'local' ? { execution_target: 'local' } : {}),
    });
    revision.current++;
    setLoading(false);
    setList((old) => [row, ...old.filter((item) => item.id !== row.id)]);
    setSelected(row.id);
    setMessages([]);
    setThoughts([]);
    setFiles([]);
    setCursor(undefined);
    return row;
  }
  function create() {
    return perform(async () => {
      const row = await createRow();
      await sdk.navigate(conversationPath(row.id));
      await read(row.id);
    });
  }
  function conversationPath(id: string) {
    const tenantRoute = scope.pathname.match(/^\/tenant\/[^/]+\/agent-workspace(?:\/|$)/);
    const base = tenantRoute ? tenantRoute[0].replace(/\/$/, '') : '/agent/chat';
    const query = new URLSearchParams(scope.search);
    query.delete('conversationId');
    const search = query.toString();
    return base + '/' + encodeURIComponent(id) + (search ? '?' + search : '');
  }
  function rename(title: string) {
    return perform(async () => {
      const row = await command<{ title: string }>('chat-rename', {
        conversation_id: selected,
        title: title.trim(),
      });
      setList((old) =>
        old.map((item) => (item.id === selected ? { ...item, title: row.title } : item))
      );
    });
  }
  function attachFiles(items: File[]) {
    return perform(async () => {
      if (!items.length) return;
      if (files.length + items.length > 10)
        throw new Error(label('Attach up to 10 files.', '最多可添加 10 个附件。'));
      const row = selectedRow ?? (await createRow());
      if (row.execution_target !== 'cloud')
        throw new Error(label('Select a cloud conversation', '请选择云端会话'));
      for (const file of items) {
        const item = await uploadAttachment(row.id, file, (payload) =>
          command('chat-upload', payload)
        );
        setFiles((old) => [...old, item]);
      }
    });
  }
  function attach(file: File) {
    return attachFiles([file]);
  }
  function send(prompt?: string, skill?: string) {
    return perform(async () => {
      const text = (prompt ?? draft).trim();
      if (!text || ((selectedRow?.execution_target ?? target) === 'local' && !hasDevice)) return;
      const row = selectedRow ?? (await createRow());
      if (row.execution_target === 'local' && !hasDevice) {
        throw new Error(
          label(
            'Open the desktop app and approve this release to send to a device.',
            '请在桌面应用批准当前版本后发送到本机。'
          )
        );
      }
      const conversation = row.id;
      try {
        if (row.execution_target === 'local') {
          if (pending.current?.id !== conversation || pending.current.text !== text)
            pending.current = {
              id: conversation,
              text,
              key: crypto.randomUUID(),
            };
          const key = pending.current.key;
          setRun({ target: 'local', conversation, key });
          const result = (await sdk.device('local_chat', {
            action: 'execute',
            conversation_id: conversation,
            idempotency_key: key,
            message: text,
          })) as {
            executed?: boolean;
            sync?: string;
            status?: string;
            detail?: string;
          };
          if (result.executed || result.sync === 'synced' || result.status === 'cancelled') {
            pending.current = null;
            setDraft('');
          }
          setError([result.status, result.sync, result.detail].filter(Boolean).join(' · '));
        } else {
          const id = crypto.randomUUID();
          setMessages((old) => [
            ...old,
            {
              id: crypto.randomUUID(),
              role: 'user_message',
              content: text,
              files,
            },
          ]);
          await command(
            files.length ? 'chat-attached-turn' : 'chat-turn',
            {
              conversation_id: conversation,
              message: text,
              ...(skill ? {forced_skill_name:skill} : {}),
              ...(files.length ? { attachment_ids: files.map((file) => file.id) } : {}),
              message_id: crypto.randomUUID(),
            },
            {
              onEvent(raw) {
                const event = raw as {
                  type: string;
                  run_id: string;
                  revision: number;
                  text: string;
                };
                if (event.type === 'accepted') {
                  setRun({
                    target: 'cloud',
                    conversation,
                    id: event.run_id,
                    revision: event.revision,
                  });
                  setDraft('');
                  setFiles([]);
                }
                if (event.type === 'thought') {
                  // Reasoning arrives one piece at a time ahead of the answer it leads to.
                  const after = latest?.();
                  setThoughts((old) => [
                    ...old,
                    { id: crypto.randomUUID(), content: event.text, ...(after ? { after } : {}) },
                  ]);
                }
                if (event.type === 'assistant_message' || event.type === 'text_delta') {
                  setMessages((old) => {
                    const last = old.at(-1),
                      base = last?.id === id ? last.content : '';
                    const next: Message = {
                      id,
                      role: 'assistant_message',
                      content: event.type === 'text_delta' ? base + event.text : event.text,
                    };
                    return [...(last?.id === id ? old.slice(0, -1) : old), next];
                  });
                }
              },
            }
          );
        }
      } catch (error) {
        await read(conversation).catch(() => {});
        throw error;
      } finally {
        setRun(undefined);
        setStopping(false);
      }
      await read(conversation);
      if (!linked) await sdk.navigate(conversationPath(conversation), { replace: true });
    });
  }
  async function stop() {
    if (!run || stopping) return;
    setStopping(true);
    try {
      if (run.target === 'cloud')
        await command('chat-cancel', {
          conversation_id: run.conversation,
          run_id: run.id,
          expected_revision: run.revision,
        });
      else
        await sdk.device('local_chat', {
          action: 'stop',
          conversation_id: run.conversation,
          idempotency_key: run.key,
        });
    } catch (e) {
      report(e);
    } finally {
      setStopping(false);
    }
  }
  async function older() {
    if (!selected || !cursor || reading.current || busy) return;
    reading.current = true;
    try {
      await read(selected, cursor);
    } catch (e) {
      report(e);
    } finally {
      reading.current = false;
    }
  }
  function choose(id: string) {
    if (busy || selected === id) return;
    void perform(async () => {
      await sdk.navigate(conversationPath(id));
      setSelected(id);
      setMessages([]);
      setThoughts([]);
      setFiles([]);
      setDraft('');
      await read(id);
    });
  }
  return {
    label,
    files,
    attach,
    attachFiles,
    removeFile: (id: string) => setFiles((old) => old.filter((file) => file.id !== id)),
    list,
    selected,
    selectedRow,
    messages,
    thoughts,
    draft,
    setDraft,
    target,
    setTarget,
    local,
    hasDevice,
    busy,
    loading,
    report,
    run,
    stopping,
    error,
    cursor,
    page,
    writable,
    create,
    rename,
    send,
    stop,
    older,
    choose,
    refresh: () => selected && perform(() => read(selected)),
  };
}
export type Chat = ReturnType<typeof useChat>;
