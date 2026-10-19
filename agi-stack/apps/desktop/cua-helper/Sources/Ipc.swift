import CryptoKit
import Foundation

let ipcProtocolVersion = "MemstackComputerUseIPC-2"
let maxFrameBytes = 8_388_608
enum IpcError: Error { case protocolError(String) }

struct JsonRpcError: Error {
    let code: Int
    let kind: String
    let message: String
    var data: [String: Any] = [:]
    func payload(id: Any) -> [String: Any] {
        var details = data
        details["kind"] = kind
        return ["jsonrpc": "2.0", "id": id,
                "error": ["code": code, "message": message, "data": details]]
    }
}
func resultPayload(id: Any, _ result: Any) -> [String: Any] {
    ["jsonrpc": "2.0", "id": id, "result": result]
}
func encodeFrame(_ json: Data) -> Data {
    var header = UInt32(json.count).littleEndian
    var frame = Data(bytes: &header, count: 4)
    frame.append(json)
    return frame
}
func encodeJson(_ value: [String: Any]) -> Data {
    (try? JSONSerialization.data(withJSONObject: value))
        ?? Data("{\"jsonrpc\":\"2.0\",\"id\":null,\"error\":{\"code\":-32603,\"message\":\"encoding failed\"}}".utf8)
}
final class FrameDecoder {
    private var buffer = Data()
    func append(_ chunk: Data) throws -> [Data] {
        buffer.append(chunk)
        var frames: [Data] = []
        while buffer.count >= 4 {
            let length = UInt32(littleEndian: buffer.withUnsafeBytes {
                $0.loadUnaligned(fromByteOffset: 0, as: UInt32.self)
            })
            guard length > 0, length <= maxFrameBytes else {
                buffer.removeAll()
                throw IpcError.protocolError("invalid frame length")
            }
            let total = 4 + Int(length)
            if buffer.count < total { break }
            frames.append(buffer.subdata(in: 4..<total))
            buffer.removeSubrange(0..<total)
        }
        return frames
    }
}

/// Only inherited pipes carry credentials. The reader stays live while native
/// work runs serially; stop flags are set before the stop response is queued.
final class IpcServer {
    private static weak var active: IpcServer?
    typealias Dispatcher = (String, [String: Any]) -> Result<Any, JsonRpcError>
    private let dispatch: Dispatcher
    private let executionQueue = DispatchQueue(label: "memstack.cua.execution")
    private let audioControlQueue = DispatchQueue(label: "memstack.cua.audio.control")
    private let outputLock = NSLock()
    private var initialized = false
    private var notificationsEnabled = false
    private let notificationLock = NSLock()
    private func enableNotifications(_ enabled: Bool) {
        notificationLock.lock(); notificationsEnabled = enabled; notificationLock.unlock()
    }
    private var sendsNotifications: Bool {
        notificationLock.lock(); defer { notificationLock.unlock() }; return notificationsEnabled
    }
    private var sequence: UInt64 = 0
    private var terminationSignal: DispatchSourceSignal?
    init(dispatcher: @escaping Dispatcher) { dispatch = dispatcher; Self.active = self }
    static func notifyStatus(_ value: [String: Any]) {
        guard let active = active, active.sendsNotifications else { return }
        active.respond(["jsonrpc": "2.0", "method": "native_status", "params": value])
    }
    static func controlSession(id: String, method: String, recordingID: String? = nil) {
        guard ["pause_session", "resume_session", "stop_session", "audio_stop"].contains(method),
              let active = active, let session = try? Sessions.shared.require(id) else { return }
        if method == "audio_stop" {
            guard let recordingID = recordingID, !recordingID.isEmpty else { return }
            active.audioControlQueue.async { _ = try? AudioCapture.shared.stop(session, recordingID: recordingID) }
            return
        }
        if method == "resume_session" {
            // The menu can request resumption but cannot grant host authority.
            NativePresentation.shared.update(session, phase: "paused", userInitiated: true, userAction: "resume")
            return
        }
        if method == "pause_session" {
            session.pause(); HeldInput.shared.release(id)
            AudioCapture.shared.endSoon(id, reason: "user_paused")
            NativePresentation.shared.update(session, phase: "paused", userInitiated: true, userAction: "pause")
        } else if method == "stop_session" {
            Sessions.shared.stop(id)
            AudioCapture.shared.endSoon(id, reason: "user_stopped")
            NativePresentation.shared.update(session, phase: "stopped", userInitiated: true, userAction: "stop")
        }
        var params: [String: Any] = session.owner
        params["session_id"] = id
        let bound = params
        active.executionQueue.async {
            if case .success = active.dispatch(method, bound), method == "resume_session" {
                NativePresentation.shared.update(session, phase: "idle", resumed: true, userInitiated: true)
            }
        }
    }
    static func stopEverything(quit: Bool = false) {
        if quit { active?.enableNotifications(false) }
        Sessions.shared.stopAll()
        guard let active = active else { if quit { exit(0) }; return }
        active.executionQueue.async {
            if quit { Sessions.shared.endAll(); exit(0) }
            Sessions.shared.cleanupAllStopped()
        }
    }
    static func proof(secret: String, nonce: String) -> String {
        HMAC<SHA256>.authenticationCode(
            for: Data(nonce.utf8), using: SymmetricKey(data: Data(secret.utf8)))
            .map { String(format: "%02x", $0) }.joined()
    }
    func start() {
        signal(SIGPIPE, SIG_IGN)
        signal(SIGTERM, SIG_IGN)
        let signalSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
        signalSource.setEventHandler { Self.stopEverything(quit: true) }
        signalSource.resume(); terminationSignal = signalSource
        let worker = Thread { [weak self] in self?.readLoop() }
        worker.name = "memstack.cua.reader"
        worker.start()
    }
    private func readLoop() {
        let decoder = FrameDecoder()
        while true {
            var chunk = [UInt8](repeating: 0, count: 65_536)
            let count = read(STDIN_FILENO, &chunk, chunk.count)
            if count < 0 && errno == EINTR { continue }
            if count <= 0 { break }
            do {
                for frame in try decoder.append(Data(chunk.prefix(count))) { receive(frame) }
            } catch { break }
        }
        enableNotifications(false)
        Sessions.shared.stopAll()
        executionQueue.async { Sessions.shared.endAll(); exit(0) }
    }
    private func receive(_ frame: Data) {
        guard let object = (try? JSONSerialization.jsonObject(with: frame)) as? [String: Any],
              object["jsonrpc"] as? String == "2.0",
              let method = object["method"] as? String, let id = object["id"],
              let params = object["params"] as? [String: Any] else {
            respond(JsonRpcError(code: -32600, kind: "invalid_request",
                message: "expected a JSON-RPC request").payload(id: NSNull()))
            return
        }
        if method == "initialize" {
            guard !initialized, (id as? Int) == 0,
                  params["client_api_version"] as? String == ipcProtocolVersion,
                  let nonce = params["nonce"] as? String, nonce.utf8.count >= 16,
                  let secret = params["secret"] as? String, secret.utf8.count >= 32 else {
                respond(JsonRpcError(code: -32001, kind: "incompatible_client_version",
                    message: "invalid initialization").payload(id: id)); return
            }
            initialized = true
            enableNotifications(params["native_status_notifications"] as? Bool == true)
            respond(resultPayload(id: id, ["server_api_version": ipcProtocolVersion,
                "nonce": nonce, "proof": Self.proof(secret: secret, nonce: nonce)]))
            return
        }
        guard initialized else {
            respond(JsonRpcError(code: -32001, kind: "authentication_required",
                message: "initialize the inherited channel first").payload(id: id)); return
        }
        sequence &+= 1
        var boundParams = params
        boundParams["_native_receive_sequence"] = NSNumber(value: sequence)
        boundParams["_native_cancellation_only"] = method == "cancel" || method == "reset" || method == "reset_session"
        if ["stop_session", "end_session", "cancel", "reset", "reset_session"].contains(method),
           let sessionID = params["session_id"] as? String { Sessions.shared.stopAuthorized(sessionID, params: boundParams) }
        if method == "pause_session", let sessionID = params["session_id"] as? String,
           let owner = try? Sessions.owner(params), let session = try? Sessions.shared.require(sessionID, owner: owner) {
            session.pause(); HeldInput.shared.release(sessionID)
            AudioCapture.shared.endSoon(sessionID, reason: params["end_reason"] as? String ?? "user_paused")
            NativePresentation.shared.update(session, phase: "paused")
        }
        let queuedParams = boundParams
        let queue = ["audio_status", "audio_stop", "audio_ack"].contains(method) ? audioControlQueue : executionQueue
        queue.async { [self] in
            switch dispatch(method, queuedParams) {
            case .success(let result): respond(resultPayload(id: id, result))
            case .failure(let error): respond(error.payload(id: id))
            }
        }
    }
    private func respond(_ object: [String: Any]) {
        var payload = encodeJson(object)
        if payload.count > maxFrameBytes {
            payload = encodeJson(JsonRpcError(code: -32000, kind: "response_too_large",
                message: "native result exceeds frame budget").payload(id: object["id"] ?? NSNull()))
        }
        let frame = encodeFrame(payload)
        outputLock.lock(); defer { outputLock.unlock() }
        frame.withUnsafeBytes { raw in
            var offset = 0
            while offset < raw.count {
                let written = write(STDOUT_FILENO, raw.baseAddress!.advanced(by: offset), raw.count - offset)
                if written < 0 && errno == EINTR { continue }
                if written <= 0 {
                    enableNotifications(false)
                    Self.stopEverything(quit: true); return
                }
                offset += written
            }
        }
    }
}
