import AVFoundation
import Foundation

enum AudioCaptureTests {
    static func samples() -> AVAudioPCMBuffer {
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 48_000, channels: 1, interleaved: false)!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 480)!
        buffer.frameLength = 480
        buffer.floatChannelData![0].initialize(repeating: 0.1, count: 480)
        return buffer
    }
    static func receipts(_ value: [String: Any]) -> [[String: Any]] { value["recordings"] as! [[String: Any]] }
    static func run() throws {
        let owner = Dictionary(uniqueKeysWithValues: Sessions.ownerFields.map { ($0, "audio-test-" + $0) })
        let session = try NativeSession(id: "audio-generation-test", owner: owner)
        defer { try? FileManager.default.removeItem(at: session.artifactDirectory) }
        var tracks: [AudioRecording] = []
        let audio = AudioCapture { track, _ in tracks.append(track); track.write(samples()) }
        let first = try audio.start(source: "microphone", session: session)
        let firstID = first["recording_id"] as! String
        let stopped = try audio.stop(session, recordingID: firstID)
        precondition(tracks.allSatisfy { !$0.active })
        precondition(receipts(stopped)[0]["status"] as? String == "pending_export")
        let file = URL(string: (receipts(stopped)[0]["artifacts"] as! [[String: Any]])[0]["url"] as! String)!
        let savedFile = try AVAudioFile(forReading: file)
        precondition(savedFile.length == 480)
        let duplicate = try audio.stop(session, recordingID: firstID)
        precondition(NSDictionary(dictionary: receipts(stopped)[0]).isEqual(to: receipts(duplicate)[0]))
        let second = try audio.start(source: "system", session: session)
        let secondID = second["recording_id"] as! String
        precondition(secondID != firstID)
        _ = try audio.stop(session, recordingID: firstID)
        let secondStatus = try audio.status(session.id, recordingID: secondID)
        precondition(receipts(secondStatus)[0]["status"] as? String == "recording")
        do { _ = try audio.stop(session, recordingID: "foreign"); preconditionFailure("foreign recording accepted") } catch {}
        _ = try audio.acknowledge(session.id, recordingID: firstID)
        _ = try audio.acknowledge(session.id, recordingID: firstID)
        precondition(!FileManager.default.fileExists(atPath: file.path))
        audio.end(session.id, reason: "user_paused")
        let pausedStatus = try audio.status(session.id, recordingID: secondID)
        precondition(receipts(pausedStatus)[0]["end_reason"] as? String == "user_paused")
        precondition(!audio.retainedFiles(session.id).isEmpty)
        precondition(audio.status(session.id)["recording"] as? Bool == false)

        var mixedTracks: [AudioRecording] = []
        let mixed = AudioCapture { track, _ in mixedTracks.append(track); track.write(samples()) }
        let mixedStart = try mixed.start(source: "mixed", session: session)
        mixedTracks[0].onFailure?("device_lost", "audio_device_changed")
        let failed = receipts(mixed.status(session.id))[0]
        precondition(mixedTracks.allSatisfy { !$0.active })
        precondition(failed["status"] as? String == "pending_export" && failed["error_code"] as? String == "audio_device_changed")
        let partials = failed["artifacts"] as! [[String: Any]]
        precondition(partials.count == 2 && partials.allSatisfy { $0["partial"] as? Bool == true && $0["kind"] as? String == "audio" })
        _ = try mixed.acknowledge(session.id, recordingID: mixedStart["recording_id"] as! String)

        let bounded = AudioCapture { track, _ in track.maximumFrames = 120; track.write(samples()) }
        _ = try bounded.start(source: "microphone", session: session)
        let limited = receipts(bounded.status(session.id))[0]
        precondition(limited["status"] as? String == "pending_export" && limited["end_reason"] as? String == "byte_limit")
        let empty = AudioCapture { _, _ in }
        _ = try empty.start(source: "mixed", session: session)
        let emptyResult = receipts(try empty.stop(session))[0]
        precondition(emptyResult["status"] as? String == "failed")
        precondition((emptyResult["artifacts"] as! [[String: Any]]).isEmpty)
        let duration = AudioCapture(maximumSeconds: 0.01) { track, _ in track.write(samples()) }
        _ = try duration.start(source: "system", session: session)
        Thread.sleep(forTimeInterval: 0.03)
        precondition(receipts(duration.status(session.id))[0]["end_reason"] as? String == "duration_limit")
        print("AUDIO_CAPTURE_LIFECYCLE_OK")
    }
}
