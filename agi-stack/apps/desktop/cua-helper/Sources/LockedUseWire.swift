import Darwin
import Foundation

enum LockedUseWireError: Error { case closed, timeout, invalidFrame }

/// Bounded pipe operations shared by the worker and its independent guardian.
enum LockedUseWire {
    static func read(_ fd: Int32, timeout: Double) throws -> [String: Any] {
        let deadline = ProcessInfo.processInfo.systemUptime + timeout
        func bytes(_ count: Int) throws -> Data {
            var data = Data()
            while data.count < count {
                let left = deadline - ProcessInfo.processInfo.systemUptime
                guard left > 0 else { throw LockedUseWireError.timeout }
                var descriptor = pollfd(fd: fd, events: Int16(POLLIN), revents: 0)
                let ready = poll(&descriptor, 1, Int32(min(100, left * 1000)))
                if ready < 0 && errno == EINTR { continue }
                guard ready >= 0 else { throw LockedUseWireError.closed }
                if ready == 0 { continue }
                var buffer = [UInt8](repeating: 0, count: count - data.count)
                let received = Darwin.read(fd, &buffer, buffer.count)
                if received < 0 && [EINTR, EAGAIN].contains(errno) { continue }
                guard received > 0 else { throw LockedUseWireError.closed }
                data.append(contentsOf: buffer.prefix(received))
            }
            return data
        }
        let header = try bytes(4)
        let length = header.withUnsafeBytes { UInt32(littleEndian: $0.loadUnaligned(as: UInt32.self)) }
        guard length > 0, length <= 4096,
              let value = try JSONSerialization.jsonObject(with: bytes(Int(length))) as? [String: Any] else {
            throw LockedUseWireError.invalidFrame
        }
        return value
    }
    static func write(_ value: [String: Any], fd: Int32, timeout: Double = 0.5) throws {
        let data = try JSONSerialization.data(withJSONObject: value)
        guard !data.isEmpty, data.count <= 4096 else { throw LockedUseWireError.invalidFrame }
        var size = UInt32(data.count).littleEndian
        var frame = Data(bytes: &size, count: 4); frame.append(data)
        let flags = fcntl(fd, F_GETFL)
        guard flags >= 0, fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0 else { throw LockedUseWireError.closed }
        let deadline = ProcessInfo.processInfo.systemUptime + timeout
        try frame.withUnsafeBytes { bytes in
            var offset = 0
            while offset < bytes.count {
                let left = deadline - ProcessInfo.processInfo.systemUptime
                guard left > 0 else { throw LockedUseWireError.timeout }
                var descriptor = pollfd(fd: fd, events: Int16(POLLOUT), revents: 0)
                let ready = poll(&descriptor, 1, Int32(min(100, left * 1000)))
                if ready < 0 && errno == EINTR { continue }
                guard ready >= 0 else { throw LockedUseWireError.closed }
                if ready == 0 { continue }
                let count = Darwin.write(fd, bytes.baseAddress!.advanced(by: offset), bytes.count - offset)
                if count < 0 && [EINTR, EAGAIN].contains(errno) { continue }
                guard count > 0 else { throw LockedUseWireError.closed }
                offset += count
            }
        }
    }
}
