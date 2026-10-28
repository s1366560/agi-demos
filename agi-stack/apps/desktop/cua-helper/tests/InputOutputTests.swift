import Foundation

/// Exercises the real bounded pipe writer while a large frame is in flight.
/// The host deliberately stops reading, then queues lifecycle and RPC traffic
/// behind thousands of replaceable input updates.
enum InputOutputTests {
    private enum Failure: Error { case invalid(String) }
    private final class FailureFlag {
        private let lock = NSLock()
        private var value = false
        func set() { lock.lock(); value = true; lock.unlock() }
        var isSet: Bool { lock.lock(); defer { lock.unlock() }; return value }
    }
    static func run() throws {
        try focusRecipients()
        try focusGuardRecovery()
        try overflowCleanupDoesNotReenterProducer()
        let pipe = Pipe()
        let failure = FailureFlag()
        let writer = IpcOutput(descriptor: pipe.fileHandleForWriting.fileDescriptor) { failure.set() }
        defer {
            writer.close()
            try? pipe.fileHandleForReading.close(); try? pipe.fileHandleForWriting.close()
        }
        writer.enqueue(["jsonrpc": "2.0", "method": "native_input_telemetry",
            "params": ["sequence": 0, "padding": String(repeating: "x", count: 262_144)]],
            notificationKey: "input:fixture")
        // Reading only the header establishes that the first frame is selected
        // and much larger than the kernel pipe capacity. Its remaining bytes
        // keep the writer blocked until all queued priorities are installed.
        let size = try length(pipe.fileHandleForReading.fileDescriptor)
        guard size > 262_144 else { throw Failure.invalid("missing initial frame") }
        for sequence in 1...2_000 {
            writer.enqueue(["jsonrpc": "2.0", "method": "native_input_telemetry",
                "params": ["sequence": sequence]], notificationKey: "input:fixture")
        }
        writer.enqueue(["jsonrpc": "2.0", "method": "native_status", "params": ["phase": "paused"]])
        writer.enqueue(resultPayload(id: 42, ["ok": true]))
        writer.enqueue(["jsonrpc": "2.0", "method": "native_status", "params": ["phase": "stopped"]])
        _ = try readBytes(size, fd: pipe.fileHandleForReading.fileDescriptor)
        let pause = try object(pipe.fileHandleForReading.fileDescriptor)
        let reply = try object(pipe.fileHandleForReading.fileDescriptor)
        let stop = try object(pipe.fileHandleForReading.fileDescriptor)
        let latest = try object(pipe.fileHandleForReading.fileDescriptor)
        guard (pause["params"] as? [String: Any])?["phase"] as? String == "paused",
              reply["id"] as? Int == 42,
              (stop["params"] as? [String: Any])?["phase"] as? String == "stopped",
              latest["method"] as? String == "native_input_telemetry",
              (latest["params"] as? [String: Any])?["sequence"] as? Int == 2_000,
              !failure.isSet else { throw Failure.invalid("priority or coalescing failed") }
        var ready = pollfd(fd: pipe.fileHandleForReading.fileDescriptor, events: Int16(POLLIN), revents: 0)
        guard poll(&ready, 1, 50) == 0 else { throw Failure.invalid("superseded input telemetry was emitted") }
    }
    private static func overflowCleanupDoesNotReenterProducer() throws {
        let pipe = Pipe()
        let producerLock = NSLock()
        let producerThread = pthread_self()
        let reentered = FailureFlag()
        let completed = DispatchSemaphore(value: 0)
        let writer = IpcOutput(descriptor: pipe.fileHandleForWriting.fileDescriptor) {
            // Report the old synchronous path without hanging this test by
            // actually taking the producer's already-held nonrecursive lock.
            if pthread_equal(pthread_self(), producerThread) != 0 {
                reentered.set()
            } else {
                producerLock.lock()
                producerLock.unlock()
            }
            completed.signal()
        }
        defer {
            writer.close()
            try? pipe.fileHandleForWriting.close(); try? pipe.fileHandleForReading.close()
        }
        writer.enqueue(["jsonrpc": "2.0", "method": "native_input_telemetry",
            "params": ["padding": String(repeating: "x", count: 262_144)]],
            notificationKey: "input:overflow")
        // The unread body pins the writer on this frame, so all 257 replies
        // remain queued and the producer deterministically trips the limit.
        guard try length(pipe.fileHandleForReading.fileDescriptor) > 262_144 else {
            throw Failure.invalid("missing overflow barrier frame")
        }
        producerLock.lock()
        for id in 1...257 { writer.enqueue(resultPayload(id: id, ["ok": true])) }
        producerLock.unlock()
        guard completed.wait(timeout: .now() + 1) == .success else {
            throw Failure.invalid("overflow cleanup did not complete after producer unlock")
        }
        guard !reentered.isSet else {
            throw Failure.invalid("overflow cleanup reentered the input producer thread")
        }
        writer.enqueue(resultPayload(id: 258, ["ok": true]))
        writer.close()
        guard completed.wait(timeout: .now() + 0.2) == .timedOut else {
            throw Failure.invalid("overflow cleanup ran more than once")
        }
    }
    private static func focusRecipients() throws {
        var state = BackgroundFocusState()
        guard state.keyboardRecipient(process: 200) == nil, !state.returned(receiver: 300) else {
            throw Failure.invalid("empty focus state redirected input")
        }
        state.lost(process: 200, owner: 100, receiver: 300)
        guard state.keyboardRecipient(process: 200) == 300,
              state.keyboardRecipient(process: 100) == nil,
              state.keyboardRecipient(process: 300) == nil,
              !state.returned(receiver: 200), state.returned(receiver: 300),
              !state.returned(receiver: 300), state.keyboardRecipient(process: 200) == 300 else {
            throw Failure.invalid("focus event recipients were reversed or return was repeated")
        }
        state.lost(process: 201, owner: 101, receiver: 301)
        guard state.keyboardRecipient(process: 200) == nil,
              state.keyboardRecipient(process: 201) == 301, state.returned(receiver: 301) else {
            throw Failure.invalid("replacement focus state kept the previous recipient")
        }
        state.clear()
        guard state.pending == nil, state.keyboardRecipient(process: 201) == nil else {
            throw Failure.invalid("stopped focus state retained a redirect")
        }
        state.lost(process: 200, owner: 100, receiver: 300)
        guard !state.foregroundChanged(to: 400, target: 100), state.pending == nil,
              state.keyboardRecipient(process: 200) == nil else {
            throw Failure.invalid("another foreground app retained an obsolete keyboard recipient")
        }
        state.lost(process: 200, owner: 100, receiver: 300)
        guard state.foregroundChanged(to: 100, target: 100), state.pending == nil else {
            throw Failure.invalid("target activation did not require input suspension")
        }
        state.lost(process: 200, owner: 100, receiver: 200)
        guard state.pending == nil, state.keyboardRecipient(process: 200) == nil else {
            throw Failure.invalid("focus state allowed a keyboard event to be reposted to itself")
        }
    }
    private static func focusGuardRecovery() throws {
        guard BackgroundInputSPI.available else { return }
        BackgroundInputSPI.recordFocusGuardFailure()
        defer { BackgroundInputSPI.recordFocusGuardReady() }
        let support = BackgroundInputSPI.support["background"] as? [String: Any]
        guard support?["supported"] as? Bool == false,
              support?["reason"] as? String == "background_focus_guard_unavailable" else {
            throw Failure.invalid("failed focus isolation was advertised as available")
        }
        // Native permission restoration can be retried in the same process;
        // only successful construction of a new guard restores availability.
        try BackgroundInputSPI.requireAvailable()
        guard !BackgroundInputSPI.available else {
            throw Failure.invalid("checking SPI availability concealed the failed focus guard")
        }
        BackgroundInputSPI.recordFocusGuardReady()
        guard BackgroundInputSPI.available else { throw Failure.invalid("a recovered focus guard remained unavailable") }
    }
    private static func object(_ fd: Int32) throws -> [String: Any] {
        guard let value = try JSONSerialization.jsonObject(with: readBytes(length(fd), fd: fd)) as? [String: Any] else {
            throw Failure.invalid("invalid frame JSON")
        }
        return value
    }
    private static func length(_ fd: Int32) throws -> Int {
        let data = try readBytes(4, fd: fd)
        let value = data.withUnsafeBytes { Int(UInt32(littleEndian: $0.loadUnaligned(as: UInt32.self))) }
        guard value > 0, value <= maxFrameBytes else { throw Failure.invalid("invalid frame size") }
        return value
    }
    private static func readBytes(_ count: Int, fd: Int32) throws -> Data {
        var output = Data()
        let deadline = ProcessInfo.processInfo.systemUptime + 2
        while output.count < count {
            guard ProcessInfo.processInfo.systemUptime < deadline else { throw Failure.invalid("read timeout") }
            var descriptor = pollfd(fd: fd, events: Int16(POLLIN), revents: 0)
            let ready = poll(&descriptor, 1, 50)
            if ready < 0 && errno == EINTR { continue }
            guard ready >= 0 else { throw Failure.invalid("read poll failed") }
            if ready == 0 { continue }
            var bytes = [UInt8](repeating: 0, count: min(count - output.count, 16_384))
            let received = read(fd, &bytes, bytes.count)
            if received < 0 && errno == EINTR { continue }
            guard received > 0 else { throw Failure.invalid("pipe closed") }
            output.append(contentsOf: bytes.prefix(received))
        }
        return output
    }
}
