import AVFoundation
import Foundation

/// Bounded 100 ms ASR packets. Durable source tracks remain authoritative when
/// live delivery loses packets or a speech provider reconnects.
final class MeetingLiveAudio {
    private let converter: AVAudioConverter
    private let format: AVAudioFormat
    private let emit: ([String: Any]) -> Void
    private let offsetMilliseconds: Int
    private var bytes = Data()
    private var frames = 0
    private var sequence = 0
    init(inputFormat: AVAudioFormat, offsetMilliseconds: Int,
         emit: @escaping ([String: Any]) -> Void) throws {
        guard let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000,
            channels: 1, interleaved: false), let converter = AVAudioConverter(from: inputFormat, to: format) else {
            throw ActionError.failure(kind: "audio_conversion_failed", message: "cannot configure live audio")
        }
        self.format = format; self.converter = converter; self.emit = emit
        self.offsetMilliseconds = offsetMilliseconds; converter.primeMethod = .none
    }
    func write(_ input: AVAudioPCMBuffer) throws {
        let capacity = AVAudioFrameCount(ceil(Double(input.frameLength) * 16_000 / input.format.sampleRate) + 128)
        guard let output = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else { return }
        var supplied = false, failure: NSError?
        let result = converter.convert(to: output, error: &failure) { _, state in
            if supplied { state.pointee = .noDataNow; return nil }
            supplied = true; state.pointee = .haveData; return input
        }
        if let failure = failure { throw failure }
        guard result != .error, let samples = output.floatChannelData else {
            throw ActionError.failure(kind: "audio_conversion_failed", message: "live audio conversion failed")
        }
        for frame in 0..<Int(output.frameLength) {
            let sample = samples[0][frame]
            guard sample.isFinite else { continue }
            var value = Int16(clamping: Int((max(-1, min(1, sample)) * 32767).rounded())).littleEndian
            withUnsafeBytes(of: &value) { bytes.append(contentsOf: $0) }
        }
        while bytes.count >= 3200 { packet(3200) }
    }
    func finish() { if !bytes.isEmpty { packet(bytes.count) } }
    private func packet(_ count: Int) {
        let data = Data(bytes.prefix(count)); bytes.removeFirst(count)
        emit(["sequence": sequence, "start_ms": offsetMilliseconds + frames * 1000 / 16_000,
            "sample_rate": 16_000, "channels": 1, "encoding": "pcm_s16le", "data": data.base64EncodedString()])
        sequence += 1; frames += count / 2
    }
}
