import Foundation

enum ArtifactRetentionTests {
    static func run() throws {
        let owner = Dictionary(uniqueKeysWithValues: Sessions.ownerFields.map { ($0, "retention-test-" + $0) })
        let session = try NativeSession(id: "retention-test-\(UUID().uuidString)", owner: owner)
        let directory = session.artifactDirectory
        defer { try? FileManager.default.removeItem(at: directory) }
        let audio = AudioCapture { track, _ in track.write(AudioCaptureTests.samples()) }
        _ = try audio.start(source: "system", session: session)
        audio.end(session.id, reason: "user_paused")
        _ = try audio.start(source: "mixed", session: session)
        audio.end(session.id, reason: "user_paused")
        let receipts = AudioCaptureTests.receipts(audio.status(session.id))
        precondition(receipts.count == 2 && receipts.allSatisfy { $0["status"] as? String == "pending_export" })
        let artifacts = receipts.flatMap { $0["artifacts"] as! [[String: Any]] }
        precondition(artifacts.count == 2 && artifacts[1]["source"] as? String == "mixed")
        let track = URL(string: artifacts[0]["url"] as! String)!
        let mixed = URL(string: artifacts[1]["url"] as! String)!
        let trackBytes = try Data(contentsOf: track)
        let mixedBytes = try Data(contentsOf: mixed)
        let retained = audio.retainedFiles(session.id)
        let transient = directory.appendingPathComponent("screenshot.png")
        let bytes = Data([1, 2, 3, 4])
        try bytes.write(to: transient)

        // FileManager enumerates /var-backed temporary directories through
        // /private/var on macOS; the two URLs identify the same owned files.
        let enumerated = try FileManager.default.contentsOfDirectory(at: directory,
            includingPropertiesForKeys: nil)
        precondition(enumerated.count == retained.count + 1)
        Sessions.removeTransientArtifacts(in: directory, retaining: retained)
        let retainedTrack = try Data(contentsOf: track)
        let retainedMix = try Data(contentsOf: mixed)
        precondition(retainedTrack == trackBytes && retainedMix == mixedBytes)
        precondition(retained.allSatisfy { FileManager.default.fileExists(atPath: $0.path) })
        precondition(!FileManager.default.fileExists(atPath: transient.path))

        // Exercise both representations explicitly, including platforms where
        // the system temporary-directory spelling happens to be canonical.
        let alias = directory.appendingPathComponent("directory-alias", isDirectory: true)
        try FileManager.default.createSymbolicLink(at: alias,
            withDestinationURL: directory)
        try bytes.write(to: transient)
        Sessions.removeTransientArtifacts(in: directory, retaining: Set(retained.map {
            alias.appendingPathComponent($0.lastPathComponent)
        }))
        let aliasedTrack = try Data(contentsOf: track)
        let aliasedMix = try Data(contentsOf: mixed)
        precondition(aliasedTrack == trackBytes && aliasedMix == mixedBytes)
        precondition(retained.allSatisfy { FileManager.default.fileExists(atPath: $0.path) })
        precondition(!FileManager.default.fileExists(atPath: transient.path))
        print("CUA_ARTIFACT_RETENTION_OK")
    }
}
