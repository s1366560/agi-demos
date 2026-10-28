import AVFoundation
import Foundation

enum AudioMixingTests {
    static func run(root: URL) throws {
        func make(_ name: String, rate: Double, value: Float) throws -> URL {
            let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: rate, channels: 1, interleaved: false)!
            let count = AVAudioFrameCount(rate / 10)
            let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: count)!
            buffer.frameLength = count
            buffer.floatChannelData![0].initialize(repeating: value, count: Int(count))
            let url = root.appendingPathComponent(name + ".wav")
            let file = try AVAudioFile(forWriting: url, settings: format.settings)
            try file.write(from: buffer)
            return url
        }
        let microphone = try make("mic-fixture", rate: 24_000, value: 0.4)
        let system = try make("system-fixture", rate: 48_000, value: 0.2)
        let output = root.appendingPathComponent("mixed-fixture.wav")
        let artifact = try AudioMixing.render(tracks: [.init(url: microphone, start: 100),
            .init(url: system, start: 100.05)], output: output)
        let file = try AVAudioFile(forReading: output)
        precondition(file.processingFormat.sampleRate == 24_000 && file.processingFormat.channelCount == 2)
        precondition(file.length == 3600 && artifact["source"] as? String == "mixed")
        let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(file.length))!
        try file.read(into: buffer)
        let samples = buffer.floatChannelData![0]
        precondition(abs(samples[600] - 0.2) < 0.01, "first source before offset")
        precondition(abs(samples[1800] - 0.3) < 0.01, "both sources mixed after offset")
        precondition(abs(samples[3000] - 0.1) < 0.01, "second source after first ends")
        let singleURL = root.appendingPathComponent("single-fixture.wav")
        _ = try AudioMixing.render(tracks: [.init(url: system, start: 1)], output: singleURL)
        let single = try AVAudioFile(forReading: singleURL)
        let singleBuffer = AVAudioPCMBuffer(pcmFormat: single.processingFormat, frameCapacity: 2400)!
        try single.read(into: singleBuffer)
        precondition(abs(singleBuffer.floatChannelData![0][1200] - 0.2) < 0.01, "single-source export preserves gain")
        do {
            _ = try AudioMixing.render(tracks: [.init(url: microphone, start: 0),
                .init(url: system, start: 400)], output: root.appendingPathComponent("invalid.wav"))
            preconditionFailure("unbounded timestamp offset accepted")
        } catch {}
    }
}
