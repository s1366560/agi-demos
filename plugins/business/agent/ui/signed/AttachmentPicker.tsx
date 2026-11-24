import { Paperclip } from "lucide-react";
import { useRef } from "react";
import { AttachmentChip } from "../web/chat/AttachmentChip";
import type { Chat } from "./useChat";
export function AttachmentPicker({
  chat,
  enabled,
}: {
  chat: Chat;
  enabled: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  if (!enabled) return null;
  return (
    <div>
      <input
        ref={input}
        type="file"
        hidden
        onChange={(e) => {
          const file = e.currentTarget.files?.[0];
          e.currentTarget.value = "";
          if (file) void chat.attach(file);
        }}
      />
      <button
        type="button"
        disabled={chat.busy || chat.files.length >= 10}
        aria-label={chat.label("Attach file", "添加附件")}
        onClick={() => input.current?.click()}
      >
        <Paperclip size={18} />
      </button>
      {chat.files.map((file) => (
        <AttachmentChip
          key={file.id}
          file={{
            id: file.id,
            filename: file.filename,
            mimeType: file.mime_type,
            sizeBytes: file.size_bytes,
            status: "uploaded",
            progress: 100,
          }}
          onRemove={chat.removeFile}
          onRetry={() => {}}
        />
      ))}
    </div>
  );
}
