import AVFoundation
import Foundation

/// One source track. File rotation does not restart the capture device.
final class MeetingAudioWriter {
    private let lock = NSLock()
    private let root: URL
    private let source: String
    private let generation: UInt64
    private let segmentFrames: Int
    private let maximumFrames: Int
    private var offsetMilliseconds: Int
    private let hostStartSeconds: Double?
    private let onSegment: ([String: Any]) -> Void
    private let normalized = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 24_000,
        channels: 2, interleaved: false)!
    private var converter: AVAudioConverter?
    private var inputFormat: AVAudioFormat?
    private var current: MeetingPCMFile?
    private var sequence = 0
    private var totalFrames = 0
    private var started = false
    private var finished = false
    private var live: MeetingLiveAudio?
    private let onLiveAudio: (([String: Any]) -> Void)?
    init(root: URL, source: String, generation: UInt64, offsetMilliseconds: Int,
         hostStartSeconds: Double? = nil, segmentSeconds: Double = 30,
         maximumMilliseconds: Int = 28_800_000,
         onLiveAudio: (([String: Any]) -> Void)? = nil,
         onSegment: @escaping ([String: Any]) -> Void) throws {
        guard ["microphone", "system"].contains(source), generation > 0,
              segmentSeconds > 0, segmentSeconds <= 30 else {
            throw ActionError.failure(kind: "invalid_params", message: "invalid meeting source")
        }
        self.root = root; self.source = source; self.generation = generation
        self.offsetMilliseconds = offsetMilliseconds; self.hostStartSeconds = hostStartSeconds
        segmentFrames = max(1, Int(segmentSeconds * 24_000)); self.onSegment = onSegment
        maximumFrames = max(0, maximumMilliseconds * 24)
        self.onLiveAudio = onLiveAudio
    }
    func write(_ input: AVAudioPCMBuffer, hostTime: Double?) throws {
        lock.lock(); defer { lock.unlock() }
        guard !finished, input.frameLength > 0 else { return }
        if !started {
            if let time = hostTime, let start = hostStartSeconds, time.isFinite, time >= start {
                offsetMilliseconds += Int((time - start) * 1000)
            }
            started = true
            if let emit = onLiveAudio {
                live = try MeetingLiveAudio(inputFormat: normalized, offsetMilliseconds: offsetMilliseconds, emit: emit)
            }
        }
        let buffer = try convert(input)
        if totalFrames < maximumFrames { try live?.write(buffer) }
        var offset = 0
        while offset < buffer.frameLength && totalFrames < maximumFrames {
            if current == nil {
                current = try MeetingPCMFile(url: root.appendingPathComponent("\(generation)-\(source)-\(sequence).wav"))
            }
            guard let file = current else { return }
            let count = min(Int(buffer.frameLength) - offset, segmentFrames - file.frames, maximumFrames - totalFrames)
            try file.append(buffer, offset: offset, count: count)
            offset += count; totalFrames += count
            if file.frames == segmentFrames { try seal() }
        }
    }
    func finish() throws {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { return }
        finished = true; live?.finish(); live = nil; try seal()
    }
    private func seal() throws {
        guard let file = current else { return }
        try file.close()
        let end = offsetMilliseconds + totalFrames * 1000 / MeetingPCMFile.rate
        let start = offsetMilliseconds + (totalFrames - file.frames) * 1000 / MeetingPCMFile.rate
        let value: [String: Any] = ["segment_id": "\(generation):\(source):\(sequence)",
            "generation": generation, "sequence": sequence, "source": source,
            "start_ms": start, "end_ms": end, "sample_rate": MeetingPCMFile.rate,
            "channels": MeetingPCMFile.channels, "encoding": "pcm_s16le", "status": "sealed",
            "url": file.url.absoluteString, "size_bytes": 44 + file.frames * MeetingPCMFile.frameBytes]
        current = nil; sequence += 1; onSegment(value)
    }
    private func convert(_ input: AVAudioPCMBuffer) throws -> AVAudioPCMBuffer {
        if input.format == normalized { return input }
        guard input.format.sampleRate > 0, input.format.sampleRate <= 384_000,
              input.format.channelCount > 0, input.format.channelCount <= 32 else {
            throw ActionError.failure(kind: "audio_format_invalid", message: "unsupported audio format")
        }
        if inputFormat != input.format {
            guard inputFormat == nil else {
                throw ActionError.failure(kind: "audio_device_changed", message: "audio device format changed")
            }
            inputFormat = input.format; converter = AVAudioConverter(from: input.format, to: normalized)
            converter?.primeMethod = .none
        }
        let capacity = AVAudioFrameCount(ceil(Double(input.frameLength) * 24_000 / input.format.sampleRate) + 256)
        guard let converter = converter,
              let output = AVAudioPCMBuffer(pcmFormat: normalized, frameCapacity: capacity) else {
            throw ActionError.failure(kind: "audio_conversion_failed", message: "cannot create audio converter")
        }
        var supplied = false, failure: NSError?
        let status = converter.convert(to: output, error: &failure) { _, state in
            if supplied { state.pointee = .noDataNow; return nil }
            supplied = true; state.pointee = .haveData; return input
        }
        if let failure = failure { throw failure }
        guard status != .error else {
            throw ActionError.failure(kind: "audio_conversion_failed", message: "cannot convert audio samples")
        }
        return output
    }
}
