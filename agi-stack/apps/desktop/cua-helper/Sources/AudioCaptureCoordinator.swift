import AVFoundation
import Foundation

/// Device ownership is reference counted; each authority owns only its consumer.
/// Samples are borrowed during the callback and must never be mutated by a sink.
final class AudioCaptureCoordinator {
    typealias Sample = (AVAudioPCMBuffer, Double?) -> Void
    typealias Failure = (String, String?) -> Void
    typealias Starter = (String, @escaping Sample, @escaping Failure) throws -> (() -> Void)
    static let shared = AudioCaptureCoordinator(starter: AudioCaptureDevice.start)
    final class Lease {
        private let lock = NSLock()
        private var releaseAction: (() -> Void)?
        init(_ release: @escaping () -> Void) { releaseAction = release }
        func release() {
            lock.lock(); let action = releaseAction; releaseAction = nil; lock.unlock()
            action?()
        }
        deinit { release() }
    }
    private struct Consumer { let sample: Sample; let failure: Failure }
    private final class Source {
        let generation = UUID()
        var consumers: [String: Consumer] = [:]
        var stop: (() -> Void)?
    }
    private let lifecycle = NSRecursiveLock()
    private let lock = NSLock()
    private var sources: [String: Source] = [:]
    private let starter: Starter
    init(starter: @escaping Starter) { self.starter = starter }
    func acquire(source: String, consumer: String, sample: @escaping Sample,
                 failure: @escaping Failure) throws -> Lease {
        guard ["microphone", "system"].contains(source), !consumer.isEmpty else {
            throw ActionError.failure(kind: "invalid_params", message: "invalid audio consumer")
        }
        lifecycle.lock(); defer { lifecycle.unlock() }
        lock.lock()
        let entry = sources[source] ?? Source()
        guard entry.consumers[consumer] == nil else {
            lock.unlock()
            throw ActionError.failure(kind: "audio_consumer_exists", message: "audio consumer already exists")
        }
        let needsStart = sources[source] == nil
        entry.consumers[consumer] = Consumer(sample: sample, failure: failure)
        sources[source] = entry
        lock.unlock()
        if needsStart {
            do {
                entry.stop = try starter(source, { [weak self, weak entry] buffer, time in
                    guard let self = self, let entry = entry else { return }
                    for sink in self.sinks(source, generation: entry.generation) { sink.sample(buffer, time) }
                }, { [weak self, weak entry] reason, error in
                    guard let self = self, let entry = entry else { return }
                    for sink in self.sinks(source, generation: entry.generation) { sink.failure(reason, error) }
                })
            } catch {
                lock.lock(); sources.removeValue(forKey: source); lock.unlock()
                throw error
            }
        }
        return Lease { [weak self] in self?.release(source, consumer: consumer, generation: entry.generation) }
    }
    private func sinks(_ source: String, generation: UUID) -> [Consumer] {
        lock.lock(); defer { lock.unlock() }
        guard let entry = sources[source], entry.generation == generation else { return [] }
        return Array(entry.consumers.values)
    }
    private func release(_ source: String, consumer: String, generation: UUID) {
        lifecycle.lock(); defer { lifecycle.unlock() }
        lock.lock()
        guard let entry = sources[source], entry.generation == generation else { lock.unlock(); return }
        entry.consumers.removeValue(forKey: consumer)
        guard entry.consumers.isEmpty else { lock.unlock(); return }
        sources.removeValue(forKey: source); lock.unlock()
        entry.stop?(); entry.stop = nil
    }
}
