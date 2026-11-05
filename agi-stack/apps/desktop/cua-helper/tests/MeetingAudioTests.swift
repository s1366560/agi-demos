import AVFoundation
import Foundation

enum MeetingAudioTests {
    static func samples(_ frames: Int) -> AVAudioPCMBuffer {
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 24_000,
            channels: 2, interleaved: false)!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames))!
        buffer.frameLength = buffer.frameCapacity
        for channel in 0..<2 { buffer.floatChannelData![channel].initialize(repeating: 0.25, count: frames) }
        return buffer
    }
    static func run() throws {
        var starts = 0, stops = 0, first = 0, second = 0
        var deliver: AudioCaptureCoordinator.Sample?
        let coordinator = AudioCaptureCoordinator { _, sample, _ in
            starts += 1; deliver = sample; return { stops += 1 }
        }
        let a = try coordinator.acquire(source: "microphone", consumer: "tool",
            sample: { _, _ in first += 1 }, failure: { _, _ in })
        let b = try coordinator.acquire(source: "microphone", consumer: "meeting",
            sample: { _, _ in second += 1 }, failure: { _, _ in })
        deliver?(samples(20), 1)
        precondition(starts == 1 && first == 1 && second == 1)
        a.release(); a.release(); deliver?(samples(20), 2)
        precondition(stops == 0 && first == 1 && second == 2)
        b.release(); precondition(stops == 1)

        let root = FileManager.default.temporaryDirectory.appendingPathComponent("meeting-tests-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false,
            attributes: [.posixPermissions: 0o700])
        defer { try? FileManager.default.removeItem(at: root) }
        var segments: [[String: Any]] = []
        let writer = try MeetingAudioWriter(root: root, source: "microphone", generation: 1,
            offsetMilliseconds: 0, segmentSeconds: 0.01) { segments.append($0) }
        try writer.write(samples(600), hostTime: nil)
        try writer.finish()
        precondition(segments.count == 3)
        precondition(segments.map { $0["sequence"] as! Int } == [0, 1, 2])
        precondition(segments.map { $0["start_ms"] as! Int } == [0, 10, 20])
        precondition(segments.map { $0["end_ms"] as! Int } == [10, 20, 25])
        for segment in segments {
            let url = URL(string: segment["url"] as! String)!
            let file = try AVAudioFile(forReading: url)
            precondition(file.processingFormat.sampleRate == 24_000 && file.processingFormat.channelCount == 2)
            let permissions = try FileManager.default.attributesOfItem(atPath: url.path)[.posixPermissions] as! NSNumber
            precondition(permissions.intValue == 0o600)
        }
        let recover = root.appendingPathComponent("recover.wav")
        var pcm: MeetingPCMFile? = try MeetingPCMFile(url: recover)
        try pcm?.append(samples(60), offset: 0, count: 60)
        try pcm?.checkpoint(); pcm = nil
        let tail = try FileHandle(forWritingTo: recover)
        try tail.seekToEnd(); try tail.write(contentsOf: Data([1, 2, 3])); try tail.close()
        let frames = try MeetingPCMFile.recover(url: recover)
        precondition(frames == 60)
        let recovered = try AVAudioFile(forReading: recover)
        precondition(recovered.length == 60)
        let maximum = try MeetingAudioSessions.duration(nil)
        precondition(maximum == 28_800_000)
        for invalid: Any in [true, 99, 28_800_001, 100.5, "100", Double.infinity] {
            do { _ = try MeetingAudioSessions.duration(invalid); preconditionFailure("invalid duration admitted") } catch {}
        }
        print("MEETING_AUDIO_SEGMENTS_AND_SHARED_CAPTURE_OK")
    }
}
