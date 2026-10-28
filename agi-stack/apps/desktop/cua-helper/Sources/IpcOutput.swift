import Foundation

/// RPC replies have priority over coalesced input telemetry. No native input or
/// cancellation thread ever waits for the host to drain stdout.
final class IpcOutput {
    private let condition = NSCondition()
    private var replies: [Data] = []
    private var notifications: [String: Data] = [:]
    private var queuedBytes = 0
    private var failed = false
    private let onFailure: () -> Void
    private let failureQueue = DispatchQueue(label: "memstack.cua.output.failure", qos: .userInitiated)
    private let descriptor: Int32
    init(descriptor: Int32 = STDOUT_FILENO, onFailure: @escaping () -> Void) {
        self.descriptor = descriptor
        self.onFailure = onFailure
        let flags = fcntl(descriptor, F_GETFL)
        if flags >= 0 { _ = fcntl(descriptor, F_SETFL, flags | O_NONBLOCK) }
        let thread = Thread { [weak self] in self?.run() }
        thread.name = "memstack.cua.output"; thread.start()
    }
    func enqueue(_ object: [String: Any], notificationKey: String? = nil) {
        var payload = encodeJson(object)
        if payload.count > maxFrameBytes {
            guard notificationKey == nil else { return }
            payload = encodeJson(JsonRpcError(code: -32000, kind: "response_too_large",
                message: "native result exceeds frame budget").payload(id: object["id"] ?? NSNull()))
        }
        let frame = encodeFrame(payload)
        condition.lock()
        guard !failed else { condition.unlock(); return }
        if let key = notificationKey {
            if let previous = notifications[key] { queuedBytes -= previous.count }
            if notifications.count >= 128 && notifications[key] == nil { condition.unlock(); return }
            notifications[key] = frame
        } else { replies.append(frame) }
        queuedBytes += frame.count
        if queuedBytes > 32 * 1024 * 1024 || replies.count > 256 {
            failed = true; condition.broadcast(); condition.unlock(); notifyFailure(); return
        }
        condition.signal(); condition.unlock()
    }
    func close() {
        condition.lock(); failed = true; replies.removeAll(); notifications.removeAll()
        queuedBytes = 0; condition.broadcast(); condition.unlock()
    }
    private func run() {
        while true {
            condition.lock()
            while !failed && replies.isEmpty && notifications.isEmpty { condition.wait() }
            if failed { condition.unlock(); return }
            let frame: Data
            if !replies.isEmpty { frame = replies.removeFirst() }
            else { frame = notifications.removeValue(forKey: notifications.keys.sorted()[0])! }
            queuedBytes -= frame.count; condition.unlock()
            do { try writeFrame(frame) }
            catch {
                condition.lock(); let notify = !failed
                failed = true; replies.removeAll(); notifications.removeAll(); condition.unlock()
                if notify { notifyFailure() }; return
            }
        }
    }
    private func notifyFailure() {
        // Producers can hold the synthetic-input lock. Cleanup takes that lock
        // too, so it must never run reentrantly on an enqueue caller's thread.
        failureQueue.async(execute: onFailure)
    }
    private func writeFrame(_ frame: Data) throws {
        let deadline = ProcessInfo.processInfo.systemUptime + 2
        try frame.withUnsafeBytes { bytes in
            var offset = 0
            while offset < bytes.count {
                condition.lock(); let closed = failed; condition.unlock()
                guard !closed else { throw IpcError.protocolError("output closed") }
                guard ProcessInfo.processInfo.systemUptime < deadline else {
                    throw IpcError.protocolError("host output stalled")
                }
                var output = pollfd(fd: descriptor, events: Int16(POLLOUT), revents: 0)
                let ready = poll(&output, 1, 50)
                if ready < 0 && errno == EINTR { continue }
                guard ready >= 0 else { throw IpcError.protocolError("host output poll failed") }
                if ready == 0 { continue }
                let count = write(descriptor, bytes.baseAddress!.advanced(by: offset), bytes.count - offset)
                if count < 0 && [EINTR, EAGAIN].contains(errno) { continue }
                guard count > 0 else { throw IpcError.protocolError("host output closed") }
                offset += count
            }
        }
    }
}
