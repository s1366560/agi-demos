import AVFoundation
import CoreMedia
import ScreenCaptureKit

/// One native capture per source, shared by independently authorized consumers.
final class AudioCaptureDevice: NSObject, SCStreamOutput, SCStreamDelegate {
    private let sample: AudioCaptureCoordinator.Sample
    private let failure: AudioCaptureCoordinator.Failure
    private var engine: AVAudioEngine?
    private var stream: SCStream?
    private var observer: NSObjectProtocol?
    private let sampleQueue = DispatchQueue(label: "memstack.audio.device.samples")
    private init(sample: @escaping AudioCaptureCoordinator.Sample,
                 failure: @escaping AudioCaptureCoordinator.Failure) {
        self.sample = sample; self.failure = failure
    }
    static func start(source: String, sample: @escaping AudioCaptureCoordinator.Sample,
                      failure: @escaping AudioCaptureCoordinator.Failure) throws -> (() -> Void) {
        let device = AudioCaptureDevice(sample: sample, failure: failure)
        do { try device.start(source) } catch { device.stop(); throw error }
        return { device.stop() }
    }
    private func start(_ source: String) throws {
        if source == "microphone" {
            guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
                throw ActionError.failure(kind: "permission_required", message: "Microphone permission is required")
            }
            let engine = AVAudioEngine(); self.engine = engine
            let input = engine.inputNode, format = input.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else {
                throw ActionError.failure(kind: "audio_device_unavailable", message: "microphone has no active format")
            }
            input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, when in
                self?.sample(buffer, when.isHostTimeValid ? AVAudioTime.seconds(forHostTime: when.hostTime) : nil)
            }
            observer = NotificationCenter.default.addObserver(forName: .AVAudioEngineConfigurationChange,
                object: engine, queue: nil) { [weak self] _ in self?.failure("device_lost", "audio_device_changed") }
            try engine.start()
            return
        }
        guard CGPreflightScreenCaptureAccess() else {
            throw ActionError.failure(kind: "permission_required", message: "Screen Recording permission is required")
        }
        let content: SCShareableContent = try Self.wait { done in
            SCShareableContent.getExcludingDesktopWindows(true, onScreenWindowsOnly: false) { done($0, $1) }
        }
        guard let display = content.displays.first else {
            throw ActionError.failure(kind: "audio_device_unavailable", message: "no display is available for system audio")
        }
        let configuration = SCStreamConfiguration()
        configuration.width = 2; configuration.height = 2
        configuration.capturesAudio = true; configuration.excludesCurrentProcessAudio = true
        configuration.sampleRate = 24_000; configuration.channelCount = 2
        let stream = SCStream(filter: SCContentFilter(display: display, excludingWindows: []),
            configuration: configuration, delegate: self)
        self.stream = stream
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: sampleQueue)
        let _: Bool = try Self.wait { done in stream.startCapture { done($0 == nil ? true : nil, $0) } }
    }
    private func stop() {
        if let observer = observer { NotificationCenter.default.removeObserver(observer); self.observer = nil }
        if let engine = engine { engine.stop(); engine.inputNode.removeTap(onBus: 0); self.engine = nil }
        if let stream = stream {
            self.stream = nil
            let completion = DispatchSemaphore(value: 0)
            stream.stopCapture { _ in completion.signal() }
            _ = completion.wait(timeout: .now() + 3)
        }
    }
    private static func wait<T>(_ work: (@escaping (T?, Error?) -> Void) -> Void) throws -> T {
        let completion = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var result: T?, error: Error?
        work { value, failure in lock.lock(); result = value; error = failure; lock.unlock(); completion.signal() }
        guard completion.wait(timeout: .now() + 10) == .success else {
            throw ActionError.failure(kind: "audio_start_timeout", message: "audio device did not respond")
        }
        lock.lock(); defer { lock.unlock() }
        if let error = error { throw error }
        guard let value = result else { throw ActionError.failure(kind: "audio_device_unavailable", message: "audio device returned no result") }
        return value
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) { failure("device_lost", "audio_capture_stopped") }
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sampleBuffer.isValid,
              let description = sampleBuffer.formatDescription,
              let basic = CMAudioFormatDescriptionGetStreamBasicDescription(description),
              let format = AVAudioFormat(streamDescription: basic),
              let buffer = AVAudioPCMBuffer(pcmFormat: format,
                  frameCapacity: AVAudioFrameCount(sampleBuffer.numSamples)) else { return }
        buffer.frameLength = buffer.frameCapacity
        if CMSampleBufferCopyPCMDataIntoAudioBufferList(sampleBuffer, at: 0,
            frameCount: Int32(sampleBuffer.numSamples), into: buffer.mutableAudioBufferList) == noErr {
            sample(buffer, CMTimeGetSeconds(sampleBuffer.presentationTimeStamp))
        }
    }
}
