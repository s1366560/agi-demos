import AppKit
import ApplicationServices
import Foundation

final class Cancellation {
    private let lock = NSLock()
    private var cancelled = false
    func stop() { lock.lock(); cancelled = true; lock.unlock() }
    func check() throws {
        lock.lock(); let value = cancelled; lock.unlock()
        if value {
            throw ActionError.failure(kind: "user_stopped_session", message: "computer use was stopped")
        }
    }
    func wait(_ seconds: Double) throws {
        let deadline = Date().addingTimeInterval(seconds)
        repeat {
            try check()
            Thread.sleep(forTimeInterval: min(0.02, max(0, deadline.timeIntervalSinceNow)))
        } while Date() < deadline
    }
}

struct NativeWindow {
    let id: String
    let element: AXUIElement
    let frame: CGRect
    let title: String
    let captureID: CGWindowID?
    let identity: NativeWindowIdentity?
    init(id: String, element: AXUIElement, frame: CGRect, title: String,
         captureID: CGWindowID?, identity: NativeWindowIdentity? = nil) {
        self.id = id; self.element = element; self.frame = frame; self.title = title
        self.captureID = captureID; self.identity = identity
    }
    var payload: [String: Any] {
        ["window_id": id, "title": title,
         "bounds": ["x": frame.minX, "y": frame.minY, "width": frame.width, "height": frame.height]]
    }
}
struct Snapshot {
    let id: String
    let app: ResolvedApp
    let window: NativeWindow
    let records: [Int: ElementRecord]
    var inputGeneration: String = ""
}
final class NativeSession {
    let id: String
    let owner: [String: String]
    let inputMode: NativeInputMode
    private var generation = UUID().uuidString
    private var inputTarget: (pid_t, String, InputRectangle)?
    private let cancellationLock = NSLock()
    private var currentCancellation = Cancellation()
    private var lastStopSequence: UInt64 = 0
    private var paused = false
    private var terminal = false
    private var observationRefreshRequired = false
    func requestObservationRefresh() {
        cancellationLock.lock(); observationRefreshRequired = true; cancellationLock.unlock()
    }
    func consumeObservationRefresh() -> Bool {
        cancellationLock.lock(); defer { cancellationLock.unlock() }
        let required = observationRefreshRequired; observationRefreshRequired = false; return required
    }
    var ended = false // serial dispatcher owned; audio receipts may outlive this session
    var cancellation: Cancellation {
        cancellationLock.lock(); defer { cancellationLock.unlock() }
        return currentCancellation
    }
    var inputGeneration: String {
        cancellationLock.lock(); defer { cancellationLock.unlock() }; return generation
    }
    var inputStopPhase: String? {
        cancellationLock.lock(); defer { cancellationLock.unlock() }
        return terminal ? "stopped" : paused ? "paused" : nil
    }
    var inputBinding: [String: Any] {
        ["input_mode": inputMode.rawValue, "input_generation": inputGeneration]
    }
    func validateInputBinding(_ params: [String: Any]) throws {
        guard params["input_mode"] as? String == inputMode.rawValue,
              params["input_generation"] as? String == inputGeneration else {
            throw ActionError.failure(kind: "stale_input_generation", message: "refresh the native session input binding")
        }
    }
    func observeInputTarget(_ app: ResolvedApp, window: NativeWindow) throws {
        cancellationLock.lock()
        let previous = inputTarget
        let bounds = InputRectangle(window.frame)
        let changed = previous.map { $0.0 != app.pid || $0.1 != window.id || $0.2 != bounds } ?? false
        cancellationLock.unlock()
        if changed {
            SyntheticInput.shared.releaseSession(id, phase: "released", reason: "target_changed")
            HeldInput.shared.release(id)
            SyntheticInput.shared.endInputLease(id)
        }
        try cancellation.check()
        cancellationLock.lock()
        if changed { generation = UUID().uuidString }
        inputTarget = (app.pid, window.id, bounds)
        cancellationLock.unlock()
        if changed { snapshots.removeAll(); previousText.removeAll() }
    }
    var windows: [String: [NativeWindow]] = [:]
    var snapshots: [String: Snapshot] = [:]
    var previousText: [String: String] = [:]
    var actionRequests = Set<String>()
    var appIcons: [String: [String: Any]] = [:]
    let artifactDirectory: URL
    init(id: String, owner: [String: String], inputMode: NativeInputMode = .background) throws {
        self.id = id
        self.owner = owner
        self.inputMode = inputMode
        artifactDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("memstack-cua-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: artifactDirectory, withIntermediateDirectories: false,
            attributes: [.posixPermissions: 0o700])
    }
    func stop(sequence: UInt64 = 0) {
        cancellationLock.lock(); defer { cancellationLock.unlock() }
        terminal = true; paused = false
        lastStopSequence = max(lastStopSequence, sequence); currentCancellation.stop()
    }
    func cancel(sequence: UInt64 = 0) {
        cancellationLock.lock(); defer { cancellationLock.unlock() }
        lastStopSequence = max(lastStopSequence, sequence); currentCancellation.stop()
    }
    @discardableResult func pause() -> Bool {
        cancellationLock.lock(); defer { cancellationLock.unlock() }
        guard !terminal else { return false }; paused = true; currentCancellation.stop(); return true
    }
    func resume() throws {
        cancellationLock.lock()
        guard paused && !terminal else {
            cancellationLock.unlock()
            throw ActionError.failure(kind: "session_not_paused", message: "only a paused live session can resume")
        }
        paused = false; currentCancellation = Cancellation(); generation = UUID().uuidString
        inputTarget = nil; cancellationLock.unlock()
        // Window handles identify a live AX window, not permission to reuse an
        // observation. selectWindow re-enumerates and verifies the AX identity.
        snapshots.removeAll(); previousText.removeAll()
    }
    func reset(sequence: UInt64 = UInt64.max) throws {
        cancellationLock.lock()
        guard !terminal, !paused else {
            cancellationLock.unlock()
            throw ActionError.failure(kind: terminal ? "user_stopped_session" : "user_paused_session",
                message: "reset cannot revive a stopped or paused session")
        }
        guard lastStopSequence <= sequence else {
            cancellationLock.unlock()
            throw ActionError.failure(kind: "cancelled", message: "a newer cancellation superseded reset")
        }
        currentCancellation = Cancellation()
        generation = UUID().uuidString
        inputTarget = nil
        cancellationLock.unlock()
        snapshots.removeAll(); windows.removeAll(); previousText.removeAll(); actionRequests.removeAll()
    }
}
final class Sessions {
    static let shared = Sessions()
    static let ownerFields = ["user_id", "tenant_id", "project_id", "conversation_id", "run_id", "device_id"]
    private let lock = NSLock()
    private var sessions: [String: NativeSession] = [:]
    private var closed: [String: NativeSession] = [:]
    static func owner(_ params: [String: Any]) throws -> [String: String] {
        var values: [String: String] = [:]
        for field in ownerFields {
            guard let value = params[field] as? String, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  value.utf8.count <= 1024 else {
                throw ActionError.failure(kind: "invalid_params", message: "nonempty session owner fields are required")
            }
            values[field] = value
        }
        return values
    }
    func begin(_ id: String, owner: [String: String], inputMode: NativeInputMode = .background) throws -> NativeSession {
        guard !id.isEmpty, id.utf8.count <= 256 else {
            throw ActionError.failure(kind: "invalid_params", message: "invalid session_id")
        }
        lock.lock()
        if let previous = closed[id], previous.owner != owner {
            lock.unlock()
            throw ActionError.failure(kind: "session_owner_mismatch", message: "closed session context changed")
        }
        if let session = sessions[id] {
            guard session.owner == owner, session.inputMode == inputMode else {
                lock.unlock()
                throw ActionError.failure(kind: "session_owner_mismatch", message: "session context changed")
            }
            lock.unlock()
            return session
        }
        guard sessions.count < 64 else {
            lock.unlock()
            throw ActionError.failure(kind: "session_limit", message: "too many live sessions")
        }
        let session: NativeSession
        do {
            if inputMode == .background { try BackgroundInputSPI.requireAvailable() }
            session = try NativeSession(id: id, owner: owner, inputMode: inputMode)
        }
        catch { lock.unlock(); throw error }
        sessions[id] = session
        lock.unlock()
        SyntheticInput.shared.registerDirectory(session.artifactDirectory)
        NativePresentation.shared.begin(session)
        return session
    }
    func require(_ id: String, owner: [String: String]? = nil) throws -> NativeSession {
        lock.lock(); defer { lock.unlock() }
        guard let session = sessions[id] else {
            throw ActionError.failure(kind: "session_not_found", message: "begin_session is required")
        }
        if let owner = owner, owner != session.owner {
            throw ActionError.failure(kind: "session_owner_mismatch", message: "session context changed")
        }
        return session
    }
    func requireAudio(_ id: String, owner: [String: String]) throws -> NativeSession {
        lock.lock(); defer { lock.unlock() }
        guard let session = sessions[id] ?? closed[id], session.owner == owner else {
            throw ActionError.failure(kind: "session_owner_mismatch", message: "owned audio session is required")
        }
        return session
    }
    func stopAuthorized(_ id: String, params: [String: Any]) {
        guard let owner = try? Self.owner(params), let session = try? require(id, owner: owner),
              (try? session.validateInputBinding(params)) != nil else { return }
        let sequence = (params["_native_receive_sequence"] as? NSNumber)?.uint64Value ?? 0
        LockedUseCoordinator.shared.end(sessionID: id)
        if params["_native_cancellation_only"] as? Bool == true { session.cancel(sequence: sequence) }
        else { session.stop(sequence: sequence); NativePresentation.shared.update(session, phase: "stopped") }
        SyntheticInput.shared.releaseSession(id, phase: params["_native_cancellation_only"] as? Bool == true ? "released" : "stopped")
        HeldInput.shared.release(id)
        AudioCapture.shared.endSoon(id, reason: params["end_reason"] as? String ?? (params["_native_cancellation_only"] as? Bool == true ? "cancelled" : "session_ended"))
    }
    func stop(_ id: String, sequence: UInt64 = 0) {
        LockedUseCoordinator.shared.end(sessionID: id)
        lock.lock(); let session = sessions[id]; lock.unlock()
        session?.stop(sequence: sequence); SyntheticInput.shared.releaseSession(id, phase: "stopped"); HeldInput.shared.release(id)
        if let session = session { NativePresentation.shared.update(session, phase: "stopped") }
    }
    @discardableResult func stopAll(reason: String = "session_ended") -> [NativeSession] {
        LockedUseCoordinator.shared.revokeImmediately(reason: reason)
        lock.lock(); let values = sessions.values.filter { $0.inputStopPhase != "stopped" }; lock.unlock()
        values.forEach { $0.stop(); SyntheticInput.shared.releaseSession($0.id, phase: "stopped", reason: reason); AudioCapture.shared.endSoon($0.id, reason: reason) }; HeldInput.shared.releaseAll()
        values.forEach { NativePresentation.shared.update($0, phase: "stopped") }
        return values
    }
    func cleanupAllStopped() {
        lock.lock(); let values = Array(sessions.values); lock.unlock()
        values.forEach { cleanupStopped($0) }
    }
    /// Runs on the serial dispatcher after the reader has set cancellation.
    func cleanupStopped(_ session: NativeSession, preserveWindows: Bool = false, reason: String? = nil) {
        NativeInputPresentation.shared.update(session, route: nil,
            phase: preserveWindows ? "paused" : "stopped", reason: reason)
        NativeClipboard.end(session.id)
        session.appIcons.removeAll()
        session.snapshots.removeAll(); session.previousText.removeAll()
        if !preserveWindows { session.windows.removeAll() }
        LockedUseCoordinator.shared.end(sessionID: session.id)
        AudioCapture.shared.end(session.id, reason: reason ?? (preserveWindows ? "user_paused" : "session_ended"))
        SyntheticInput.shared.endInputLease(session.id)
        Self.removeTransientArtifacts(in: session.artifactDirectory,
            retaining: AudioCapture.shared.retainedFiles(session.id))
    }
    static func removeTransientArtifacts(in directory: URL, retaining files: Set<URL>) {
        // Directory enumeration resolves /var to /private/var on macOS. Match
        // file identity through the same canonical spelling before cleanup.
        let retained = Set(files.map { $0.resolvingSymlinksInPath().standardizedFileURL })
        for file in (try? FileManager.default.contentsOfDirectory(at: directory,
            includingPropertiesForKeys: nil)) ?? [] where !retained.contains(file.resolvingSymlinksInPath().standardizedFileURL) {
            try? FileManager.default.removeItem(at: file)
        }
    }
    func end(_ id: String) {
        lock.lock(); let session = sessions.removeValue(forKey: id); lock.unlock()
        session?.stop(); SyntheticInput.shared.releaseSession(id, phase: "stopped"); HeldInput.shared.release(id)
        if let session = session {
            session.ended = true
            cleanupStopped(session)
            if AudioCapture.shared.retainedFiles(id).isEmpty {
                try? FileManager.default.removeItem(at: session.artifactDirectory)
            }
            // Clipboard/input recovery has completed. Sealed recording files are
            // now host-owned pending exports and must survive helper shutdown.
            SyntheticInput.shared.forgetDirectory(session.artifactDirectory)
            lock.lock(); closed[id] = session; lock.unlock()
            NativePresentation.shared.end(id)
            NativeInputPresentation.shared.forget(id)
        }
    }
    func endAll() {
        lock.lock(); let ids = Array(sessions.keys); lock.unlock()
        ids.forEach(end)
    }
}
enum TargetPolicy {
    static let forbidden = Set(["com.apple.keychainaccess", "com.apple.passwords",
                                "com.apple.systempreferences"])
    static func check(_ app: ResolvedApp) throws {
        guard !forbidden.contains((app.bundleId ?? app.id).lowercased()) else {
            throw ActionError.failure(kind: "cua_target_forbidden", message: "this application is forbidden")
        }
    }
    static func requireFocused(_ app: ResolvedApp, window: NativeWindow) throws {
        guard NSWorkspace.shared.frontmostApplication?.processIdentifier == app.pid else {
            throw ActionError.failure(kind: "target_not_focused", message: "activate the target application first")
        }
        let axApp = AXUIElementCreateApplication(app.pid)
        guard let focused = AxEngine.copyElement(axApp, kAXFocusedWindowAttribute as String),
              CFEqual(focused, window.element) else {
            throw ActionError.failure(kind: "target_not_focused", message: "activate the observed window first")
        }
    }
}
