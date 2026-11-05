import AVFoundation
import Foundation
import Darwin

/// User-owned audio sessions are deliberately outside Sessions.stopAll and run
/// cancellation. The authenticated host supplies owner and generation bindings.
final class MeetingAudioSessions {
    static let shared = MeetingAudioSessions()
    static let methods: Set<String> = ["audio_session_start", "audio_session_pause", "audio_session_resume",
        "audio_session_stop", "audio_session_status"]
    final class Record {
        let id: String, owner: [String: String], root: URL, source: String, mode: String
        let maximumMilliseconds: Int, startedAt: String
        var generation: UInt64, state = "paused", capturedMilliseconds = 0
        var activeSince: Double?, reason: String?, failure: String?
        var leases: [AudioCaptureCoordinator.Lease] = [], writers: [MeetingAudioWriter] = []
        var timer: DispatchSourceTimer?
        var offsets: [String: Int] = [:]
        private let segmentLock = NSLock()
        private var segments: [String: [String: Any]] = [:]
        init(id: String, owner: [String: String], root: URL, source: String, mode: String,
             generation: UInt64, maximumMilliseconds: Int, startedAt: String? = nil) {
            self.id = id; self.owner = owner; self.root = root; self.source = source; self.mode = mode
            self.generation = generation; self.maximumMilliseconds = maximumMilliseconds
            self.startedAt = startedAt ?? ISO8601DateFormatter().string(from: Date())
        }
        func append(_ value: [String: Any]) {
            guard let id = value["segment_id"] as? String else { return }
            segmentLock.lock(); segments[id] = value; segmentLock.unlock()
        }
        func segmentSnapshot() -> [[String: Any]] {
            segmentLock.lock(); defer { segmentLock.unlock() }
            return segments.values.sorted {
                let lhs = $0["start_ms"] as? Int ?? 0, rhs = $1["start_ms"] as? Int ?? 0
                return lhs == rhs ? ($0["segment_id"] as? String ?? "") < ($1["segment_id"] as? String ?? "") : lhs < rhs
            }
        }
        var elapsed: Int {
            min(maximumMilliseconds, capturedMilliseconds + activeSince.map {
                max(0, Int((ProcessInfo.processInfo.systemUptime - $0) * 1000))
            }.defaulting(to: 0))
        }
        var receipt: [String: Any] { snapshot() }
        func snapshot(includeSegments: Bool = true) -> [String: Any] {
            var value: [String: Any] = ["audio_session_id": id, "generation": generation, "owner": owner,
                "source": source, "mode": mode, "state": state, "started_at": startedAt,
                "captured_ms": elapsed, "max_duration_ms": maximumMilliseconds,
                "artifact_root": root.path,
                "segments_complete": includeSegments,
                "segments": includeSegments ? segmentSnapshot() : []]
            if let reason = reason { value["end_reason"] = reason }
            if let failure = failure { value["error_code"] = failure }
            return value
        }
    }
    private let queue = DispatchQueue(label: "memstack.audio.sessions")
    private let coordinator: AudioCaptureCoordinator
    private var records: [String: Record] = [:]
    init(coordinator: AudioCaptureCoordinator = .shared) { self.coordinator = coordinator }
    static func duration(_ raw: Any?) throws -> Int {
        guard let raw = raw else { return 28_800_000 }
        guard let value = raw as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(),
              value.doubleValue.isFinite, value.doubleValue.rounded() == value.doubleValue,
              (100...28_800_000).contains(value.doubleValue) else {
            throw ActionError.failure(kind: "invalid_params", message: "max_duration_ms must be from 100 through 28800000")
        }
        return value.intValue
    }
    func perform(_ method: String, params: [String: Any]) throws -> [String: Any] {
        try queue.sync {
            guard Self.methods.contains(method), let id = params["audio_session_id"] as? String,
                  UUID(uuidString: id) != nil, let rawOwner = params["owner"] as? [String: String],
                  let number = params["generation"] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
                  let generation = UInt64(exactly: number.doubleValue), generation > 0 else {
                throw ActionError.failure(kind: "invalid_params", message: "audio session identity is required")
            }
            let fields = ["user_id", "tenant_id", "project_id", "device_id"]
            guard fields.allSatisfy({ !(rawOwner[$0] ?? "").isEmpty && (rawOwner[$0]?.utf8.count ?? 0) <= 1024 }),
                  Set(rawOwner.keys) == Set(fields) else {
                throw ActionError.failure(kind: "invalid_params", message: "audio session owner is required")
            }
            let root = try MeetingAudioStore.directory(params["artifact_root"])
            var value = records[id]
            if value == nil { value = try MeetingAudioStore.load(id: id, owner: rawOwner, root: root) }
            if let value = value {
                guard value.owner == rawOwner, value.root == root else {
                    throw ActionError.failure(kind: "audio_session_owner_mismatch", message: "audio session owner changed")
                }
                records[id] = value
                if method == "audio_session_resume" {
                    if value.state == "recording", generation == value.generation { return value.receipt }
                    guard ["paused", "interrupted"].contains(value.state), generation > value.generation,
                          value.elapsed < value.maximumMilliseconds else {
                        throw ActionError.failure(kind: "audio_session_generation_mismatch", message: "resume requires a new audio generation")
                    }
                    value.generation = generation; try begin(value)
                } else {
                    guard generation == value.generation else {
                        throw ActionError.failure(kind: "audio_session_generation_mismatch", message: "audio generation changed")
                    }
                    if method == "audio_session_pause" { finish(value, state: "paused", reason: "user_paused") }
                    if method == "audio_session_stop" { finish(value, state: "stopped", reason: "user_stopped") }
                }
                return value.receipt
            }
            guard method == "audio_session_start", records.values.filter({ $0.state == "recording" }).count < 8,
                  let source = params["source"] as? String, ["microphone", "system", "mixed"].contains(source),
                  let mode = params["mode"] as? String, ["dictation", "meeting", "voice"].contains(mode) else {
                throw ActionError.failure(kind: "audio_session_unavailable", message: "start an owned audio session first")
            }
            let created = Record(id: id, owner: rawOwner, root: root, source: source, mode: mode,
                generation: generation, maximumMilliseconds: try Self.duration(params["max_duration_ms"]))
            records[id] = created
            try begin(created)
            return created.receipt
        }
    }
    private func begin(_ value: Record) throws {
        value.failure = nil; value.reason = nil; value.state = "recording"
        value.activeSince = ProcessInfo.processInfo.systemUptime
        value.offsets[String(value.generation)] = value.capturedMilliseconds
        do {
            guard MeetingAudioStore.hasCapacity(value.root) else {
                throw ActionError.failure(kind: "audio_storage_full", message: "insufficient space for meeting audio")
            }
            try MeetingAudioStore.save(value)
            let hostStart = AVAudioTime.seconds(forHostTime: mach_absolute_time())
            for source in value.source == "mixed" ? ["microphone", "system"] : [value.source] {
                let writer = try MeetingAudioWriter(root: value.root, source: source, generation: value.generation,
                    offsetMilliseconds: value.capturedMilliseconds, hostStartSeconds: hostStart,
                    maximumMilliseconds: value.maximumMilliseconds - value.capturedMilliseconds,
                    onLiveAudio: { [id = value.id, owner = value.owner, generation = value.generation] packet in
                        var value = packet
                        value["audio_session_id"] = id; value["owner"] = owner
                        value["generation"] = generation; value["source"] = source
                        IpcServer.notifyAudioPCM(value)
                    }) { [weak self, weak value] segment in
                        guard let self = self, let value = value else { return }
                        value.append(segment)
                        self.queue.async { self.publish(value) }
                    }
                value.writers.append(writer)
                let lease = try coordinator.acquire(source: source,
                    consumer: "audio-session:\(value.id):\(value.generation):\(source)", sample: { [weak self, weak value] buffer, time in
                        do { try writer.write(buffer, hostTime: time) }
                        catch {
                            guard let self = self, let value = value else { return }
                            self.queue.async { self.finish(value, state: "interrupted", reason: "storage_failed", failure: "audio_write_failed") }
                        }
                    }, failure: { [weak self, weak value] reason, error in
                        guard let self = self, let value = value else { return }
                        self.queue.async { self.finish(value, state: "interrupted", reason: reason, failure: error) }
                    })
                value.leases.append(lease)
            }
            let timer = DispatchSource.makeTimerSource(queue: queue)
            timer.schedule(deadline: .now() + 1, repeating: 1)
            timer.setEventHandler { [weak self, weak value] in
                guard let self = self, let value = value, value.state == "recording" else { return }
                if value.elapsed >= value.maximumMilliseconds { self.finish(value, state: "stopped", reason: "duration_limit") }
                else if !MeetingAudioStore.hasCapacity(value.root) {
                    self.finish(value, state: "interrupted", reason: "disk_full", failure: "audio_storage_full")
                } else {
                    let progress = value.snapshot(includeSegments: false)
                    IpcServer.notifyAudioSession(progress); MeetingStatusItem.shared.update(progress)
                }
            }
            value.timer = timer; timer.resume(); publish(value)
        } catch {
            finish(value, state: "interrupted", reason: "start_failed", failure: "audio_start_failed")
            throw error
        }
    }
    private func finish(_ value: Record, state: String, reason: String, failure: String? = nil) {
        guard value.state == "recording" || (state == "stopped" && ["paused", "interrupted"].contains(value.state)) else { return }
        value.capturedMilliseconds = value.elapsed; value.activeSince = nil
        value.state = state; value.reason = reason; value.failure = failure
        value.timer?.cancel(); value.timer = nil
        value.leases.forEach { $0.release() }; value.leases.removeAll()
        for writer in value.writers {
            do { try writer.finish() } catch { value.failure = "audio_finalize_failed"; value.state = "interrupted" }
        }
        value.writers.removeAll(); publish(value)
    }
    private func publish(_ value: Record) {
        do { try MeetingAudioStore.save(value) }
        catch {
            if value.state == "recording" {
                finish(value, state: "interrupted", reason: "storage_failed", failure: "audio_session_save_failed")
                return
            }
            value.failure = "audio_session_save_failed"
        }
        IpcServer.notifyAudioSession(value.receipt)
        MeetingStatusItem.shared.update(value.receipt)
    }
    func stopFromMenu(id: String) { queue.async {
        if let value = self.records[id] { self.finish(value, state: "stopped", reason: "user_stopped") }
    } }
    func interruptAll(reason: String) { queue.sync {
        for value in records.values { finish(value, state: "interrupted", reason: reason) }
    } }
}

private extension Optional where Wrapped == Int {
    func defaulting(to value: Int) -> Int { self ?? value }
}
