import AVFoundation
import Foundation

/// Bounded offline mixing. Each converter holds only one input/output chunk;
/// original tracks remain private and only the mixed WAV is published.
enum AudioMixing {
    static let rate = 24_000.0
    static let channels: AVAudioChannelCount = 2
    static let maxSeconds = 300.0
    static let maxBytes = 64 * 1024 * 1024
    struct Track { let url: URL; let start: Double }

    final class Reader {
        let file: AVAudioFile
        let converter: AVAudioConverter
        let format: AVAudioFormat
        private var converted: AVAudioPCMBuffer?
        private var cursor: AVAudioFrameCount = 0
        private var ended = false
        init(url: URL, format: AVAudioFormat) throws {
            file = try AVAudioFile(forReading: url)
            guard let converter = AVAudioConverter(from: file.processingFormat, to: format),
                  file.length > 0 else {
                throw ActionError.failure(kind: "audio_conversion_failed", message: "track is empty or cannot be converted")
            }
            self.converter = converter; self.format = format
        }
        func add(to output: AVAudioPCMBuffer, outputOffset: Int, count: Int, gain: Float) throws {
            var destination = outputOffset
            let end = outputOffset + count
            while destination < end && !ended {
                if converted == nil || cursor == converted!.frameLength { try refill() }
                guard let source = converted, source.frameLength > cursor,
                      let sourceData = source.floatChannelData, let outputData = output.floatChannelData else { break }
                let available = min(end - destination, Int(source.frameLength - cursor))
                for channel in 0..<Int(AudioMixing.channels) {
                    for frame in 0..<available {
                        outputData[channel][destination + frame] += sourceData[channel][Int(cursor) + frame] * gain
                    }
                }
                cursor += AVAudioFrameCount(available); destination += available
            }
        }
        private func refill() throws {
            guard let output = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 4096) else {
                throw ActionError.failure(kind: "audio_conversion_failed", message: "cannot allocate conversion buffer")
            }
            var error: NSError?
            var readError: Error?
            let status = converter.convert(to: output, error: &error) { [self] requested, inputStatus in
                let remaining = file.length - file.framePosition
                guard remaining > 0 else { inputStatus.pointee = .endOfStream; return nil }
                let count = AVAudioFrameCount(min(remaining, AVAudioFramePosition(requested)))
                guard let input = AVAudioPCMBuffer(pcmFormat: file.processingFormat,
                    frameCapacity: max(1, count)) else {
                    inputStatus.pointee = .endOfStream; return nil
                }
                do {
                    try file.read(into: input, frameCount: count)
                    if input.frameLength == 0 { inputStatus.pointee = .endOfStream; return nil }
                    inputStatus.pointee = .haveData; return input
                } catch {
                    readError = error; inputStatus.pointee = .endOfStream; return nil
                }
            }
            if let error = readError ?? error { throw error }
            if status == .error { throw ActionError.failure(kind: "audio_conversion_failed", message: "native audio conversion failed") }
            converted = output; cursor = 0
            if output.frameLength == 0 { ended = true }
        }
    }
    static func render(tracks: [Track], output: URL) throws -> [String: Any] {
        guard !tracks.isEmpty, tracks.count <= 2, tracks.allSatisfy({ $0.start.isFinite }),
              let first = tracks.map({ $0.start }).min(),
              let processing = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: rate,
                channels: channels, interleaved: false),
              let storage = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: rate,
                channels: channels, interleaved: true) else {
            throw ActionError.failure(kind: "audio_conversion_failed", message: "invalid audio tracks")
        }
        let readers = try tracks.map { try Reader(url: $0.url, format: processing) }
        let offsets = tracks.map { Int64((($0.start - first) * rate).rounded()) }
        guard offsets.allSatisfy({ $0 >= 0 && $0 <= Int64(maxSeconds * rate) }) else {
            throw ActionError.failure(kind: "audio_alignment_failed", message: "audio sources have incompatible timestamps")
        }
        let lengths = readers.map { Int64((Double($0.file.length) / $0.file.processingFormat.sampleRate * rate).rounded(.up)) }
        let frames = min(Int64(maxSeconds * rate), zip(offsets, lengths).map { $0.0 + $0.1 }.max() ?? 0)
        guard frames > 0 else { throw ActionError.failure(kind: "audio_empty", message: "no audio frames were recorded") }
        do {
            let file = try AVAudioFile(forWriting: output, settings: storage.settings,
                commonFormat: .pcmFormatFloat32, interleaved: false)
            var position: Int64 = 0
            while position < frames {
                let count = Int(min(4096, frames - position))
                guard let buffer = AVAudioPCMBuffer(pcmFormat: processing, frameCapacity: AVAudioFrameCount(count)),
                      let data = buffer.floatChannelData else {
                    throw ActionError.failure(kind: "audio_conversion_failed", message: "cannot allocate mix buffer")
                }
                buffer.frameLength = AVAudioFrameCount(count)
                for channel in 0..<Int(channels) { data[channel].initialize(repeating: 0, count: count) }
                for index in readers.indices {
                    let begin = max(position, offsets[index]); let end = min(position + Int64(count), offsets[index] + lengths[index])
                    if end > begin {
                        try readers[index].add(to: buffer, outputOffset: Int(begin - position),
                            count: Int(end - begin), gain: 1 / Float(readers.count))
                    }
                }
                for channel in 0..<Int(channels) {
                    for frame in 0..<count { data[channel][frame] = max(-1, min(1, data[channel][frame])) }
                }
                try file.write(from: buffer); position += Int64(count)
            }
        } catch { try? FileManager.default.removeItem(at: output); throw error }
        let attributes = try FileManager.default.attributesOfItem(atPath: output.path)
        guard ((attributes[.size] as? NSNumber)?.intValue ?? (maxBytes + 1)) <= maxBytes else {
            try? FileManager.default.removeItem(at: output)
            throw ActionError.failure(kind: "audio_too_large", message: "mixed audio exceeds the artifact limit")
        }
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: output.path)
        return ["url": output.absoluteString, "mime_type": "audio/wav", "kind": "audio", "source": "mixed",
                "frames": frames, "sample_rate": rate, "channels": channels,
                "encoding": "pcm_s16le", "duration_seconds": Double(frames) / rate]
    }
}
