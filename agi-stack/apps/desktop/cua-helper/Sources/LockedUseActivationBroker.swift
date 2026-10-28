import Darwin
import Foundation

/// One private socket and one accepted installer connection per admitted request.
final class LockedUseActivationBroker {
    let socketURL: URL
    private let directory: URL
    private let request: LockedUseActivationRequest
    private let current: () throws -> Void
    private let verifyPeer: (Int32) -> Bool
    private let deadline: Double
    private let lock = NSLock()
    private var listener: Int32 = -1
    private var peer: Int32 = -1
    private var consumed = false

    init(request: LockedUseActivationRequest, lifetime: Double = 300,
         current: @escaping () throws -> Void, verifyPeer: @escaping (Int32) -> Bool) throws {
        self.request = request; self.current = current; self.verifyPeer = verifyPeer
        deadline = ProcessInfo.processInfo.systemUptime + lifetime
        directory = URL(fileURLWithPath: "/tmp/agi-cua-activation-" + UUID().uuidString, isDirectory: true)
        socketURL = directory.appendingPathComponent("request.sock")
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false,
            attributes: [.posixPermissions: 0o700])
        var ready = false
        defer { if !ready { try? FileManager.default.removeItem(at: directory) } }
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw LockedUseActivationError.unavailable }
        var adopted = false
        defer { if !adopted { close(fd) } }
        LockedUseActivationSocket.configure(fd)
        var address = try LockedUseActivationSocket.address(socketURL)
        let status = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) }
        }
        guard status == 0, chmod(socketURL.path, 0o600) == 0, listen(fd, 4) == 0 else {
            throw LockedUseActivationError.unavailable
        }
        listener = fd; adopted = true; ready = true
        Thread { self.serve(fd) }.start()
    }
    deinit { stop() }

    func stop() {
        lock.lock(); let fd = listener; listener = -1; let active = peer; lock.unlock()
        if active >= 0 { shutdown(active, SHUT_RDWR) }
        // The accept thread owns close; keeping this descriptor allocated until
        // it exits prevents another thread from reusing it under accept().
        if fd >= 0 { shutdown(fd, SHUT_RDWR) }
        try? FileManager.default.removeItem(at: directory)
    }
    private func validate() throws {
        guard ProcessInfo.processInfo.systemUptime < deadline else { throw LockedUseActivationError.expired }
        try current()
    }
    private func serve(_ fd: Int32) {
        defer { close(fd) }
        while true {
            lock.lock(); let live = listener == fd; lock.unlock()
            guard live else { return }
            let client = accept(fd, nil, nil)
            guard client >= 0 else { if errno == EINTR { continue }; return }
            LockedUseActivationSocket.configure(client)
            lock.lock()
            let allowed = listener == fd && !consumed
            if allowed { peer = client }
            lock.unlock()
            if allowed && verifyPeer(client) { serveRequest(client) }
            lock.lock(); if peer == client { peer = -1 }; lock.unlock()
            close(client)
        }
    }
    private func serveRequest(_ fd: Int32) {
        do {
            var sequence = 0
            while true {
                let value = try LockedUseWire.read(fd, timeout: sequence == 0 ? 1 : 30)
                guard request.matches(value), value["sequence"] as? Int == sequence,
                      value["operation"] as? String == (sequence == 0 ? "claim" : "check") else {
                    throw LockedUseActivationError.invalidRequest
                }
                try validate()
                if sequence == 0 {
                    lock.lock(); let first = !consumed && listener >= 0
                    if first { consumed = true }; lock.unlock()
                    guard first else { throw LockedUseActivationError.expired }
                }
                try LockedUseWire.write(["ok": true, "request_id": request.requestID,
                    "generation": request.generation, "sequence": sequence], fd: fd)
                sequence += 1
            }
        } catch { try? LockedUseWire.write(["ok": false], fd: fd) }
    }
}
