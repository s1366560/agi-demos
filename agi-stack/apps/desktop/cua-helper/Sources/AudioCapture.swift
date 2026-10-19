import AVFoundation
import ScreenCaptureKit
import Foundation

/// Captures have independent generations. Sealed files survive session cleanup
/// until the host acknowledges durable artifact storage.
final class AudioCapture {
    static let shared = AudioCapture()
    static let endReasons: Set<String> = ["user_stopped", "user_paused", "model_stopped", "session_ended", "session_reset", "revoked", "disabled", "lease_expired", "cancelled"]
    final class Recording {
        let id = UUID().uuidString
        let session: NativeSession
        let source: String
        let started = Date()
        var ended: Date?
        var state = "recording"
        var reason: String?
        var error: String?
        var tracks: [AudioRecording] = []
        var artifacts: [[String: Any]] = []
        var timer: DispatchSourceTimer?
        init(session: NativeSession, source: String) { self.session = session; self.source = source }
        var receipt: [String: Any] {
            var value: [String: Any] = ["recording_id": id, "source": source, "status": state,
                "artifact_root": session.artifactDirectory.path,
                "started_at": ISO8601DateFormatter().string(from: started),
                "elapsed_ms": Int(max(0, (ended ?? Date()).timeIntervalSince(started)) * 1000),
                "artifacts": artifacts]
            if let ended = ended { value["ended_at"] = ISO8601DateFormatter().string(from: ended) }
            if let reason = reason { value["end_reason"] = reason }
            if let error = error { value["error_code"] = error }
            if error != nil, !artifacts.isEmpty { value["partial"] = true }
            return value
        }
    }
    typealias TrackStarter = (AudioRecording, NativeSession) throws -> Void
    private let queue = DispatchQueue(label: "memstack.cua.recordings")
    private let sampleQueue = DispatchQueue(label: "memstack.cua.audio.samples")
    private var recordings: [String: [Recording]] = [:]
    private let starter: TrackStarter?
    private let maximumSeconds: Double
    init(maximumSeconds: Double = AudioMixing.maxSeconds, starter: TrackStarter? = nil) {
        self.maximumSeconds = maximumSeconds; self.starter = starter
    }
    func capabilities() -> [String: Any] {
        let microphone = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        let system = CGPreflightScreenCaptureAccess()
        return ["audio_microphone": ["state": microphone ? "available" : "permission_required"],
            "audio_system": ["state": system ? "available" : "permission_required"],
            "audio_mixed": ["state": microphone && system ? "available" : "permission_required"]]
    }
    func requestMicrophone(_ session: NativeSession) throws -> [String: Any] {
        let result: Bool = try WindowCapture.wait(session: session) { done in
            AVCaptureDevice.requestAccess(for: .audio) { done($0, nil) }
        }
        return ["granted": result]
    }
    func start(source: String, session: NativeSession) throws -> [String: Any] {
        try queue.sync {
            guard ["microphone", "system", "mixed"].contains(source) else {
                throw ActionError.failure(kind: "invalid_params", message: "source must be microphone, system or mixed")
            }
            guard !recordings.values.flatMap({ $0 }).contains(where: { $0.state == "recording" || $0.state == "stopping" }) else {
                throw ActionError.failure(kind: "audio_busy", message: "another recording owns the audio devices")
            }
            guard (recordings[session.id]?.count ?? 0) < 128 else {
                throw ActionError.failure(kind: "audio_receipt_limit", message: "acknowledge completed recordings first")
            }
            let recording = Recording(session: session, source: source)
            recordings[session.id, default: []].append(recording)
            do {
                for source in source == "mixed" ? ["microphone", "system"] : [source] {
                    let track = AudioRecording(url: session.artifactDirectory.appendingPathComponent("audio-\(UUID().uuidString).wav"), source: source)
                    recording.tracks.append(track)
                    track.onFailure = { [weak self, weak recording] reason, error in
                        guard let self = self, let recording = recording else { return }
                        self.queue.async { self.finalize(recording, reason: reason, error: error) }
                    }
                    if let starter = starter { try starter(track, session) }
                    else { try startTrack(track, session: session) }
                }
                try session.cancellation.check()
                let timer = DispatchSource.makeTimerSource(queue: queue)
                timer.schedule(deadline: .now() + maximumSeconds)
                timer.setEventHandler { [weak self, weak recording] in
                    if let recording = recording { self?.finalize(recording, reason: "duration_limit") }
                }
                recording.timer = timer; timer.resume()
                publish(recording)
                return response([recording])
            } catch {
                finalize(recording, reason: "start_failed", error: "audio_start_failed")
                throw error
            }
        }
    }
    private func startTrack(_ recording: AudioRecording, session: NativeSession) throws {
        if recording.source == "microphone" {
            guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
                throw ActionError.failure(kind: "permission_required", message: "Microphone permission is required")
            }
            let engine = AVAudioEngine()
            let input = engine.inputNode
            let format = input.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else {
                throw ActionError.failure(kind: "audio_device_unavailable", message: "microphone has no active format")
            }
            input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, when in
                recording.write(buffer, hostTime: when.isHostTimeValid ? AVAudioTime.seconds(forHostTime: when.hostTime) : nil)
            }
            recording.engine = engine
            recording.configurationObserver = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange,
                object: engine, queue: nil) { [weak recording] _ in recording?.onFailure?("device_lost", "audio_device_changed") }
            try engine.start()
        } else {
            guard CGPreflightScreenCaptureAccess() else {
                throw ActionError.failure(kind: "permission_required", message: "Screen Recording permission is required")
            }
            let content: SCShareableContent = try WindowCapture.wait(session: session) { done in
                SCShareableContent.getExcludingDesktopWindows(true, onScreenWindowsOnly: false) { done($0, $1) }
            }
            guard let display = content.displays.first else {
                throw ActionError.failure(kind: "audio_device_unavailable", message: "no display is available for system audio")
            }
            let configuration = SCStreamConfiguration()
            configuration.width = 2; configuration.height = 2
            configuration.capturesAudio = true; configuration.excludesCurrentProcessAudio = true
            let stream = SCStream(filter: SCContentFilter(display: display, excludingWindows: []), configuration: configuration, delegate: recording)
            recording.stream = stream
            try stream.addStreamOutput(recording, type: .audio, sampleHandlerQueue: sampleQueue)
            let _: Bool = try WindowCapture.wait(session: session) { done in stream.startCapture { done($0 == nil ? true : nil, $0) } }
        }
    }
    private func response(_ values: [Recording]) -> [String: Any] {
        var result: [String: Any] = ["recordings": values.map { $0.receipt },
            "recording": values.contains { $0.state == "recording" }, "artifacts": values.flatMap { $0.artifacts }]
        if values.contains(where: { $0.error != nil && !$0.artifacts.isEmpty }) { result["partial"] = true }
        if values.count == 1, let value = values.first { result["recording_id"] = value.id; result["source"] = value.source }
        return result
    }
    private func selected(_ sessionID: String, _ recordingID: String?) throws -> [Recording] {
        let values = recordings[sessionID] ?? []
        guard let recordingID = recordingID else { return values }
        guard let value = values.first(where: { $0.id == recordingID }) else {
            throw ActionError.failure(kind: "recording_not_found", message: "recording does not belong to this session")
        }
        return [value]
    }
    func status(_ sessionID: String) -> [String: Any] { queue.sync { response(recordings[sessionID] ?? []) } }
    func status(_ sessionID: String, recordingID: String?) throws -> [String: Any] {
        try queue.sync { response(try selected(sessionID, recordingID)) }
    }
    func stop(_ session: NativeSession, recordingID: String? = nil, reason: String = "user_stopped") throws -> [String: Any] {
        try queue.sync {
            let values = try selected(session.id, recordingID)
            for value in values { finalize(value, reason: reason) }
            return response(values)
        }
    }
    func end(_ id: String, reason: String = "session_ended") {
        queue.sync { for value in recordings[id] ?? [] { finalize(value, reason: reason) } }
    }
    func endSoon(_ id: String, reason: String) {
        guard Self.endReasons.contains(reason) else { return }
        queue.async { for value in self.recordings[id] ?? [] { self.finalize(value, reason: reason) } }
    }
    func retainedFiles(_ id: String) -> Set<URL> {
        queue.sync { Set((recordings[id] ?? []).filter { $0.state != "saved" }.flatMap {
            $0.tracks.map { $0.url } + $0.artifacts.compactMap { ($0["url"] as? String).flatMap(URL.init(string:)) }
        }) }
    }
    func acknowledge(_ sessionID: String, recordingID: String) throws -> [String: Any] {
        try queue.sync {
            let values = try selected(sessionID, recordingID)
            guard let value = values.first, value.state != "recording", value.state != "stopping" else {
                throw ActionError.failure(kind: "recording_active", message: "active recording cannot be acknowledged")
            }
            if value.state != "saved" {
                for file in Set(value.tracks.map { $0.url } + value.artifacts.compactMap { ($0["url"] as? String).flatMap(URL.init(string:)) }) {
                    if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
                }
                value.state = "saved"; value.artifacts = []; publish(value)
                if value.session.ended,
                   !(recordings[sessionID] ?? []).contains(where: { $0.state != "saved" && $0.session.artifactDirectory == value.session.artifactDirectory }) {
                    // rmdir only removes an empty owned directory, never follows files or links.
                    _ = rmdir(value.session.artifactDirectory.path)
                }
            }
            return response(values)
        }
    }
    private func finalize(_ value: Recording, reason: String, error: String? = nil) {
        guard value.state == "recording" else { return }
        value.state = "stopping"; value.timer?.cancel(); value.timer = nil
        value.reason = reason; value.error = error
        value.tracks.forEach { $0.stopResources() }
        value.ended = Date()
        let valid = value.tracks.filter { $0.track != nil }
        value.artifacts = valid.map { $0.payload }
        if value.source == "mixed", valid.count == 2, error == nil {
            do {
                var artifact = try AudioMixing.render(tracks: valid.compactMap { $0.track },
                    output: value.session.artifactDirectory.appendingPathComponent("mixed-\(value.id).wav"))
                artifact["source"] = "mixed"; value.artifacts = [artifact]
            } catch { value.error = "audio_mix_failed" }
        } else if value.source == "mixed", valid.count != 2, value.error == nil { value.error = "audio_source_empty" }
        if value.artifacts.isEmpty { value.error = value.error ?? "audio_empty" }
        if value.error != nil {
            value.artifacts = value.artifacts.map { var artifact = $0; artifact["partial"] = true; return artifact }
        }
        for artifact in value.artifacts {
            if let path = (artifact["url"] as? String).flatMap(URL.init(string:))?.path {
                try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path)
            }
        }
        value.state = value.artifacts.isEmpty ? "failed" : "pending_export"
        publish(value)
    }
    private func publish(_ value: Recording) {
        NativePresentation.shared.recordings(value.session, values: (recordings[value.session.id] ?? []).map { $0.receipt })
    }
}
