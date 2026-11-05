import Foundation
import Darwin

enum MeetingAudioStore {
    static func directory(_ raw: Any?) throws -> URL {
        guard let path = raw as? String, path.hasPrefix("/"), !path.utf8.contains(0) else {
            throw error("audio_artifact_root_invalid")
        }
        var info = stat()
        guard lstat(path, &info) == 0, info.st_mode & S_IFMT == S_IFDIR,
              info.st_uid == geteuid(), info.st_mode & 0o077 == 0 else {
            throw error("audio_artifact_root_invalid")
        }
        let url = URL(fileURLWithPath: path).standardizedFileURL
        // /var is a system alias on macOS; canonicalize once for stable binding.
        return url.resolvingSymlinksInPath()
    }
    static func hasCapacity(_ root: URL) -> Bool {
        guard let stats = try? FileManager.default.attributesOfFileSystem(forPath: root.path),
              let free = stats[.systemFreeSize] as? NSNumber else { return false }
        // Reserve two full source segments plus bookkeeping, not a semantic verdict.
        return free.uint64Value > 64 * 1024 * 1024
    }
    static func save(_ record: MeetingAudioSessions.Record) throws {
        var value = record.receipt
        value["schema"] = 1; value["generation_offsets"] = record.offsets
        let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        let target = record.root.appendingPathComponent("session.json")
        var info = stat()
        if lstat(target.path, &info) == 0 {
            guard info.st_mode & S_IFMT == S_IFREG, info.st_uid == geteuid() else { throw error("audio_session_storage_invalid") }
        } else if errno != ENOENT { throw error("audio_session_storage_unavailable") }
        try data.write(to: target, options: [.atomic])
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: target.path)
    }
    static func load(id: String, owner: [String: String], root: URL) throws -> MeetingAudioSessions.Record? {
        let path = root.appendingPathComponent("session.json")
        let fd = open(path.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
        if fd < 0 && errno == ENOENT { return nil }
        guard fd >= 0 else { throw error("audio_session_storage_invalid") }
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? handle.close() }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_uid == geteuid(), info.st_mode & S_IFMT == S_IFREG,
              info.st_size <= 4 * 1024 * 1024,
              let data = try handle.readToEnd(),
              let raw = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              raw["schema"] as? Int == 1, raw["audio_session_id"] as? String == id,
              raw["owner"] as? [String: String] == owner,
              let source = raw["source"] as? String, ["microphone", "system", "mixed"].contains(source),
              let mode = raw["mode"] as? String, ["dictation", "meeting", "voice"].contains(mode),
              let generation = raw["generation"] as? NSNumber, generation.uint64Value > 0,
              let state = raw["state"] as? String, ["recording", "paused", "interrupted", "stopped"].contains(state),
              let captured = raw["captured_ms"] as? Int, (0...28_800_000).contains(captured) else {
            throw error("audio_session_storage_invalid")
        }
        let record = MeetingAudioSessions.Record(id: id, owner: owner, root: root, source: source, mode: mode,
            generation: generation.uint64Value, maximumMilliseconds: try MeetingAudioSessions.duration(raw["max_duration_ms"]),
            startedAt: raw["started_at"] as? String)
        record.capturedMilliseconds = captured
        record.state = state == "recording" ? "interrupted" : state
        record.reason = state == "recording" ? "process_interrupted" : raw["end_reason"] as? String
        record.failure = raw["error_code"] as? String
        record.offsets = raw["generation_offsets"] as? [String: Int] ?? [:]
        for segment in raw["segments"] as? [[String: Any]] ?? [] { record.append(segment) }
        try recoverFiles(record)
        try save(record)
        return record
    }
    private static func recoverFiles(_ record: MeetingAudioSessions.Record) throws {
        let known = Set(record.segmentSnapshot().compactMap { $0["segment_id"] as? String })
        let files = try FileManager.default.contentsOfDirectory(at: record.root, includingPropertiesForKeys: nil)
        guard files.count <= 4_000 else { throw error("audio_session_segment_limit") }
        for file in files where file.pathExtension == "wav" {
            let parts = file.deletingPathExtension().lastPathComponent.split(separator: "-")
            guard parts.count == 3, let generation = UInt64(parts[0]), generation <= record.generation,
                  ["microphone", "system"].contains(String(parts[1])), let sequence = Int(parts[2]),
                  (0..<960).contains(sequence), let offset = record.offsets[String(generation)] else { continue }
            let id = "\(generation):\(parts[1]):\(sequence)"
            if known.contains(id) { continue }
            let frames = try MeetingPCMFile.recover(url: file)
            let start = offset + sequence * 30_000, end = start + frames * 1000 / MeetingPCMFile.rate
            record.append(["segment_id": id, "generation": generation, "sequence": sequence,
                "source": String(parts[1]), "start_ms": start, "end_ms": end,
                "sample_rate": MeetingPCMFile.rate, "channels": 2, "encoding": "pcm_s16le",
                "status": "partial", "recovered": true, "url": file.absoluteString,
                "size_bytes": 44 + frames * MeetingPCMFile.frameBytes])
            record.capturedMilliseconds = min(record.maximumMilliseconds, max(record.capturedMilliseconds, end))
        }
    }
    private static func error(_ code: String) -> ActionError {
        .failure(kind: code, message: "Meeting audio storage is unavailable")
    }
}
