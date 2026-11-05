import AVFoundation
import Foundation
import Darwin

/// Recoverable PCM WAV. A crash can leave only a partial final frame, never an
/// unbounded in-memory recording. Checkpoints update the header and fsync data.
final class MeetingPCMFile {
    static let rate = 24_000
    static let channels = 2
    static let frameBytes = 4
    let url: URL
    private let handle: FileHandle
    private(set) var frames = 0
    private var closed = false
    private var checkpointFrames = 0
    init(url: URL) throws {
        self.url = url
        let fd = open(url.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard fd >= 0 else { throw Self.failure("audio_file_create_failed") }
        handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        do { try handle.write(contentsOf: Self.header(frames: 0)) }
        catch { try? handle.close(); throw error }
    }
    func append(_ buffer: AVAudioPCMBuffer, offset: Int, count: Int) throws {
        guard !closed, buffer.format.sampleRate == Double(Self.rate),
              buffer.format.channelCount == 2, let samples = buffer.floatChannelData,
              offset >= 0, count >= 0, offset + count <= buffer.frameLength,
              frames + count <= Self.rate * 31 else { throw Self.failure("audio_segment_invalid") }
        var data = Data(capacity: count * Self.frameBytes)
        for frame in offset..<(offset + count) {
            for channel in 0..<Self.channels {
                let sample = samples[channel][frame]
                guard sample.isFinite else { throw Self.failure("audio_sample_invalid") }
                var value = Int16(clamping: Int((max(-1, min(1, sample)) * 32767).rounded())).littleEndian
                withUnsafeBytes(of: &value) { data.append(contentsOf: $0) }
            }
        }
        try handle.write(contentsOf: data); frames += count
        if frames - checkpointFrames >= Self.rate { try checkpoint() }
    }
    func checkpoint() throws {
        guard !closed else { return }
        try handle.seek(toOffset: 0)
        try handle.write(contentsOf: Self.header(frames: frames))
        try handle.seekToEnd(); try handle.synchronize()
        checkpointFrames = frames
    }
    func close() throws {
        guard !closed else { return }
        try checkpoint(); try handle.close(); closed = true
    }
    deinit { try? close() }
    static func recover(url: URL) throws -> Int {
        let fd = open(url.path, O_RDWR | O_NOFOLLOW | O_CLOEXEC)
        guard fd >= 0 else { throw failure("audio_recovery_unavailable") }
        let file = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
        defer { try? file.close() }
        var info = stat()
        guard fstat(fd, &info) == 0, info.st_uid == geteuid(),
              info.st_mode & S_IFMT == S_IFREG, info.st_size >= 44,
              info.st_size <= 44 + rate * 31 * frameBytes,
              let bytes = try file.read(upToCount: 44), bytes.count == 44 else {
            throw failure("audio_recovery_invalid")
        }
        let canonical = header(frames: 0)
        guard bytes[0..<4] == canonical[0..<4], bytes[8..<40] == canonical[8..<40] else {
            throw failure("audio_recovery_invalid")
        }
        let frames = (Int(info.st_size) - 44) / frameBytes
        try file.truncate(atOffset: UInt64(44 + frames * frameBytes))
        try file.seek(toOffset: 0); try file.write(contentsOf: header(frames: frames))
        try file.synchronize()
        return frames
    }
    private static func header(frames: Int) -> Data {
        var data = Data("RIFF".utf8)
        func number<T: FixedWidthInteger>(_ value: T) {
            var little = value.littleEndian
            withUnsafeBytes(of: &little) { data.append(contentsOf: $0) }
        }
        number(UInt32(36 + frames * frameBytes)); data.append(Data("WAVEfmt ".utf8))
        number(UInt32(16)); number(UInt16(1)); number(UInt16(channels))
        number(UInt32(rate)); number(UInt32(rate * frameBytes))
        number(UInt16(frameBytes)); number(UInt16(16)); data.append(Data("data".utf8))
        number(UInt32(frames * frameBytes))
        return data
    }
    private static func failure(_ code: String) -> ActionError {
        .failure(kind: code, message: "Meeting audio storage failed")
    }
}
