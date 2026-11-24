type Upload = (payload: Record<string, unknown>) => Promise<unknown>;
export interface UploadedAttachment {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
}

async function encode(blob: Blob) {
  return btoa(String.fromCharCode(...new Uint8Array(await blob.arrayBuffer())));
}

export async function uploadAttachment(
  conversation: string,
  file: File,
  upload: Upload,
) {
  const chunkSize = 45 * 1024;
  const input = {
    conversation_id: conversation,
    filename: file.name,
    mime_type: file.type || "application/octet-stream",
  };
  if (file.size <= chunkSize)
    return (await upload({
      ...input,
      content: await encode(file),
    })) as UploadedAttachment;
  const { attachment_id, part_size } = (await upload({
    ...input,
    action: "begin",
    size_bytes: file.size,
  })) as { attachment_id: string; part_size: number };
  const session = { conversation_id: conversation, attachment_id };
  try {
    for (
      let start = 0, part = 1;
      start < file.size;
      start += part_size, part++
    ) {
      const length = Math.min(part_size, file.size - start);
      for (let offset = 0; offset < length; offset += chunkSize) {
        const data = file.slice(
          start + offset,
          start + Math.min(length, offset + chunkSize),
        );
        await upload({
          ...session,
          action: "chunk",
          part_number: part,
          offset,
          content: await encode(data),
        });
      }
    }
    return (await upload({
      ...session,
      action: "finish",
    })) as UploadedAttachment;
  } catch (error) {
    await upload({ ...session, action: "abort" }).catch(() => undefined);
    throw error;
  }
}
