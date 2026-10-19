import AppKit
import Darwin
import Foundation

/// Test executable only: named fixture pasteboards and OS locks, no UI input.
@main
enum RecoveryFixture {
    static func main() throws {
        if CommandLine.arguments == [CommandLine.arguments[0], "--input-watchdog"] { InputWatchdogWorker.run() }
        let arguments = Array(CommandLine.arguments.dropFirst())
        guard let operation = arguments.first else { exit(2) }
        if operation == "lease-probe" {
            let descriptor = try DesktopInputLease.openDescriptor()
            defer { close(descriptor) }
            guard DesktopInputLease.acquire(descriptor) else { print("device_busy"); exit(3) }
            DesktopInputLease.release(descriptor); print("available"); return
        }
        if operation == "lease-holder" {
            // Match the real helper's dispatch-source SIGTERM registration.
            // A SIGSTOP prevents its asynchronous cleanup from running.
            signal(SIGTERM, SIG_IGN)
            let session = try newSession()
            try SyntheticInput.shared.beginInputLease(session.id)
            ready(session.artifactDirectory.path)
            waitForEOF()
            Sessions.shared.end(session.id); return
        }
        guard arguments.count >= 2, arguments[1].hasPrefix("memstack-cua-test-") else { exit(2) }
        let board = NSPasteboard(name: NSPasteboard.Name(arguments[1]))
        switch operation {
        case "seed":
            board.clearContents(); board.setString("fixture-original", forType: .string)
            board.setData(Data("<b>fixture-original</b>".utf8), forType: .html)
        case "local-copy":
            board.clearContents(); board.setString("fixture-local-copy", forType: .string)
        case "check":
            guard arguments.count == 3, board.string(forType: .string) == arguments[2] else { exit(4) }
            if arguments[2] == "fixture-original" {
                guard board.data(forType: .html) == Data("<b>fixture-original</b>".utf8) else { exit(5) }
            }
            print("match")
        case "write":
            let session = try newSession()
            NativeClipboard.board = board
            _ = try NativeClipboard.write(text: "fixture-owned", format: "html", session: session)
            ready(session.artifactDirectory.path)
            waitForEOF()
            Sessions.shared.end(session.id)
        case "write-nested":
            let session = try newSession()
            NativeClipboard.board = board
            let first = try NativeClipboard.write(text: "fixture-first", format: "html", session: session)["handle"] as! String
            _ = try NativeClipboard.write(text: "fixture-owned", format: "html", session: session)
            ready(session.artifactDirectory.path)
            waitForEOF()
            _ = try NativeClipboard.release(handle: first, sessionID: session.id)
            Sessions.shared.end(session.id)
        case "drop": board.releaseGlobally()
        default: exit(2)
        }
    }
    static func newSession() throws -> NativeSession {
        let owner = Dictionary(uniqueKeysWithValues: Sessions.ownerFields.map { ($0, "recovery-fixture-" + $0) })
        return try Sessions.shared.begin("recovery-fixture-" + UUID().uuidString, owner: owner)
    }
    static func ready(_ directory: String) {
        FileHandle.standardOutput.write(Data((directory + "\n").utf8))
    }
    static func waitForEOF() {
        var byte: UInt8 = 0
        while read(STDIN_FILENO, &byte, 1) > 0 {}
    }
}
