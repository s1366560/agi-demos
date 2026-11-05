import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, isAbsolute, join } from 'node:path';
import { randomUUID } from 'node:crypto';

const ownedAudioFiles = new WeakMap();
export const ownedAudioFilename = value => value && typeof value === 'object' ? ownedAudioFiles.get(value) : undefined;

export function audioBytes(value) {
  const source = value?.bytes ?? value?.data_url ?? value?.dataBase64 ?? value?.data_base64 ?? value?.data ?? value;
  let mimeType = value?.mimeType ?? value?.mime_type ?? 'audio/wav';
  let bytes;
  if (typeof source === 'string') {
    let encoded = source;
    if (source.startsWith('data:')) {
      const separator = source.indexOf(',');
      const header = source.slice(5, separator);
      if (separator < 0 || !header.endsWith(';base64')) throw new TypeError('audio data URL must be base64 encoded');
      mimeType = header.slice(0, -7); encoded = source.slice(separator + 1);
    }
    if (!/^[A-Za-z0-9+/]*={0,2}$/.test(encoded) || encoded.length % 4 !== 0) throw new TypeError('audio contains invalid base64 bytes');
    bytes = Buffer.from(encoded, 'base64');
  } else bytes = Buffer.from(source);
  if (!mimeType.startsWith('audio/')) throw new TypeError('audio MIME type is required');
  return { bytes, mimeType };
}

export function nativeAudio({ call, temporaryDirectory }) {
  let recordingId;
  let directory;
  const root = async () => {
    if (!directory) directory = (async () => {
      if (temporaryDirectory !== undefined) {
        if (!isAbsolute(temporaryDirectory)) throw new TypeError('temporaryDirectory must be absolute');
        await mkdir(temporaryDirectory, { recursive: true, mode: 0o700 });
        return temporaryDirectory;
      }
      return mkdtemp(join(tmpdir(), 'memstack-cua-audio-'));
    })();
    return directory;
  };
  const readArtifact = async ({ recording_id, artifact_id }) => {
    if (typeof recording_id !== 'string' || !recording_id) throw new TypeError('audio artifact requires a recording_id');
    const buffers = [];
    let offset = 0;
    let selectedArtifact = artifact_id;
    let expectedSize;
    for (;;) {
      const chunk = await call('computer_audio_read', { recording_id, ...(selectedArtifact ? { artifact_id: selectedArtifact } : {}), offset });
      if (chunk.recording_id !== recording_id || typeof chunk.artifact_id !== 'string' || !chunk.artifact_id || (selectedArtifact !== undefined && chunk.artifact_id !== selectedArtifact)) throw new Error('audio artifact identity changed while reading');
      selectedArtifact = chunk.artifact_id;
      if (chunk.offset !== offset || chunk.mime_type !== 'audio/wav' || !Number.isSafeInteger(chunk.size_bytes) || chunk.size_bytes < 0 || chunk.size_bytes > 64 * 1024 * 1024) throw new Error('invalid audio artifact chunk metadata');
      if (expectedSize !== undefined && expectedSize !== chunk.size_bytes) throw new Error('audio artifact size changed while reading');
      expectedSize = chunk.size_bytes;
      const { bytes } = audioBytes({ data_base64: chunk.data_base64, mime_type: chunk.mime_type });
      if (!Number.isSafeInteger(chunk.next_offset) || chunk.next_offset !== offset + bytes.length || chunk.next_offset > chunk.size_bytes) throw new Error('invalid audio artifact chunk offset');
      buffers.push(bytes); offset = chunk.next_offset;
      if (chunk.eof === true) {
        if (offset !== chunk.size_bytes) throw new Error('audio artifact ended before its declared size');
        return { bytes: Buffer.concat(buffers), mimeType: 'audio/wav' };
      }
      if (!bytes.length || offset >= chunk.size_bytes) throw new Error('audio artifact read made no progress');
    }
  };
  const start = async (options = {}) => {
    if (!options || typeof options !== 'object' || Array.isArray(options)) throw new TypeError('audio options must be an object');
    for (const key of Object.keys(options)) if (key !== 'max_duration_ms') throw new TypeError(`unknown audio option ${key}`);
    const maximum = options.max_duration_ms ?? 60_000;
    if (!Number.isSafeInteger(maximum) || maximum < 100 || maximum > 300_000) throw new TypeError('audio duration must be an integer from 100 through 300000');
    if (recordingId) throw new Error('a legacy system recording is already active; stop it before starting another');
    const receipt = await call('computer_audio_start', { source: 'system', max_duration_ms: maximum });
    if (typeof receipt.recording_id !== 'string' || !receipt.recording_id) throw new Error('host did not return an owned recording identity');
    recordingId = receipt.recording_id;
  };
  const stop = async () => {
    if (!recordingId) throw new Error('no legacy system recording was started in this session');
    const receipt = await call('computer_audio_stop', { recording_id: recordingId });
    const recordings = receipt.recordings ?? [receipt];
    const recording = recordings.find(item => item.recording_id === recordingId);
    const inline = (recording?.media ?? receipt.media ?? []).find(item => item.inline === true && (item.data ?? item.dataBase64 ?? item.data_base64));
    const artifactId = recording?.artifact_id ?? recording?.artifacts?.[0]?.artifact_id;
    const audio = inline ? audioBytes(inline) : await readArtifact({ recording_id: recordingId, artifact_id: artifactId });
    const filepath = join(await root(), `${randomUUID()}.wav`);
    await writeFile(filepath, audio.bytes, { mode: 0o600, flag: 'wx' });
    recordingId = undefined;
    const result = { filepath, bytes: Uint8Array.from(audio.bytes), data_url: `data:${audio.mimeType};base64,${audio.bytes.toString('base64')}` };
    ownedAudioFiles.set(result, basename(filepath));
    return result;
  };
  return { start_audio_recording: start, stop_audio_recording: stop, readArtifact };
}
