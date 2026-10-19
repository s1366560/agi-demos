import AVFoundation
import CoreMedia
import ScreenCaptureKit
import Darwin

final class AudioRecording: NSObject, SCStreamOutput, SCStreamDelegate {
    let url: URL
    let source: String
    private let lock = NSLock()
    private var file: AVAudioFile?
    private var frames: AVAudioFramePosition = 0
    private var failure: String?
    private var finished = false
    private var firstHostTime: Double?
    var configurationObserver: NSObjectProtocol?
    var onFailure: ((String, String?) -> Void)?
    var maximumFrames: Int64? // injectable bounded writer budget
    var engine: AVAudioEngine?
    var stream: SCStream?
    init(url: URL, source: String) { self.url = url; self.source = source }
    func write(_ buffer: AVAudioPCMBuffer, hostTime: Double? = nil) {
        lock.lock(); defer { lock.unlock() }
        guard !finished else { return }
        let now = AVAudioTime.seconds(forHostTime: mach_absolute_time())
        if firstHostTime == nil {
            // Both backends normally provide host-clock sample times. Fall back
            // to the same monotonic clock when a driver supplies a relative PTS.
            firstHostTime = hostTime.flatMap { $0.isFinite && abs($0 - now) < 10 ? $0 : nil }
                ?? now - Double(buffer.frameLength) / buffer.format.sampleRate
        }
        let sampleBytes = max(1, 2 * Int(buffer.format.channelCount))
        let budgetFrames = min(Int64(buffer.format.sampleRate * AudioMixing.maxSeconds),
            Int64((AudioMixing.maxBytes - 4096) / sampleBytes))
        let remaining = max(0, min(budgetFrames, maximumFrames ?? budgetFrames) - frames)
        guard remaining > 0 else { signal("byte_limit", error: nil); return }
        if Int64(buffer.frameLength) > remaining {
            buffer.frameLength = AVAudioFrameCount(remaining)
        }
        do {
            if file == nil {
                guard let storage = AVAudioFormat(commonFormat: .pcmFormatInt16,
                    sampleRate: buffer.format.sampleRate, channels: buffer.format.channelCount, interleaved: true) else {
                    throw ActionError.failure(kind: "audio_conversion_failed", message: "cannot configure bounded WAV recording")
                }
                file = try AVAudioFile(forWriting: url, settings: storage.settings,
                    commonFormat: buffer.format.commonFormat, interleaved: buffer.format.isInterleaved)
            }
            try file?.write(from: buffer)
            frames += AVAudioFramePosition(buffer.frameLength)
            if Int64(buffer.frameLength) == remaining { signal("byte_limit", error: nil) }
        } catch { signal("capture_error", error: "audio_write_failed") }
    }
    private func signal(_ reason: String, error: String?) {
        // Called under the sample lock. The owner schedules finalization off the audio callback.
        failure = error; onFailure?(reason, error)
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        onFailure?("device_lost", "audio_capture_stopped")
    }
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sampleBuffer.isValid,
              let description = sampleBuffer.formatDescription,
              let basic = CMAudioFormatDescriptionGetStreamBasicDescription(description),
              let format = AVAudioFormat(streamDescription: basic),
              let buffer = AVAudioPCMBuffer(pcmFormat: format,
                  frameCapacity: AVAudioFrameCount(sampleBuffer.numSamples)) else { return }
        buffer.frameLength = buffer.frameCapacity
        let result = CMSampleBufferCopyPCMDataIntoAudioBufferList(sampleBuffer, at: 0,
            frameCount: Int32(sampleBuffer.numSamples), into: buffer.mutableAudioBufferList)
        if result == noErr { write(buffer, hostTime: CMTimeGetSeconds(sampleBuffer.presentationTimeStamp)) }
    }
    var payload: [String: Any] {
        lock.lock(); defer { lock.unlock() }
        return ["source": source, "url": url.absoluteString, "frames": frames,
                "host_start_seconds": firstHostTime ?? NSNull(),
                "error": failure ?? NSNull(), "mime_type": "audio/wav", "kind": "audio"]
    }
    var active: Bool { lock.lock(); defer { lock.unlock() }; return !finished }
    var track: AudioMixing.Track? {
        lock.lock(); defer { lock.unlock() }
        guard frames > 0, let start = firstHostTime else { return nil }
        return AudioMixing.Track(url: url, start: start)
    }
    func stopResources() {
        lock.lock()
        guard !finished else { lock.unlock(); return }
        finished = true; file = nil
        let engine = self.engine; self.engine = nil
        let stream = self.stream; self.stream = nil
        let observer = configurationObserver; configurationObserver = nil
        lock.unlock()
        if let observer = observer { NotificationCenter.default.removeObserver(observer) }
        if let engine = engine { engine.stop(); engine.inputNode.removeTap(onBus: 0) }
        if let stream = stream {
            let completion = DispatchSemaphore(value: 0)
            stream.stopCapture { _ in completion.signal() }
            _ = completion.wait(timeout: .now() + 3)
        }
    }
}
