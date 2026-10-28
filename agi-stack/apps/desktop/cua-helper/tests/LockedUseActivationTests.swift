import Darwin
import Foundation

enum LockedUseActivationTests {
    static func request(_ arguments: [String] = ["/fixture/installer", "uninstall"]) -> LockedUseActivationRequest {
        LockedUseActivationRequest(requestID: UUID().uuidString, generation: UUID().uuidString,
            arguments: arguments, ownerUID: getuid())
    }
    static func broker(_ request: LockedUseActivationRequest, cancellation: Cancellation = Cancellation(),
                       lifetime: Double = 300) throws -> LockedUseActivationBroker {
        try LockedUseActivationBroker(request: request, lifetime: lifetime,
            current: { try cancellation.check() }, verifyPeer: { descriptor in
                var user: uid_t = 0, group: gid_t = 0
                return getpeereid(descriptor, &user, &group) == 0 && user == getuid()
            })
    }
    static func client(_ broker: LockedUseActivationBroker,
                       _ request: LockedUseActivationRequest) throws -> LockedUseActivationClient {
        try LockedUseActivationClient(socketURL: broker.socketURL, request: request, verifyPeer: { _ in true })
    }
    static func rejects(_ operation: () throws -> Void) {
        do { try operation(); preconditionFailure("an expired or unrelated activation was accepted") }
        catch {}
    }
    static func run() throws {
        let binding = request()
        let suffix = ["--activation", "/tmp/fixture.sock", binding.requestID, binding.generation, String(getuid())]
        let (parsed, path) = try LockedUseActivationRequest.parseCommand(binding.arguments + suffix)
        precondition(parsed == binding && path.path == "/tmp/fixture.sock")
        for arguments in [binding.arguments, binding.arguments + suffix + ["extra"],
                          ["installer", "uninstall", "extra"] + suffix,
                          ["installer", "install", "/plugin", "/helper", "/socket", "0"] + suffix] {
            rejects { _ = try LockedUseActivationRequest.parseCommand(arguments) }
        }
        for expired in [false, true] {
            let cancellation = Cancellation()
            let authority = try broker(binding, cancellation: cancellation, lifetime: expired ? 0 : 300)
            defer { authority.stop() }
            if !expired { cancellation.stop() }
            rejects { _ = try client(authority, binding) }
        }
        let authority = try broker(binding)
        defer { authority.stop() }
        for wrong in [request(binding.arguments),
                      LockedUseActivationRequest(requestID: binding.requestID, generation: "different",
                        arguments: binding.arguments, ownerUID: binding.ownerUID),
                      LockedUseActivationRequest(requestID: binding.requestID, generation: binding.generation,
                        arguments: ["/other/installer", "uninstall"], ownerUID: binding.ownerUID),
                      LockedUseActivationRequest(requestID: binding.requestID, generation: binding.generation,
                        arguments: ["/fixture/installer", "install"], ownerUID: binding.ownerUID)] {
            rejects { _ = try client(authority, wrong) }
        }
        rejects {
            _ = try LockedUseActivationClient(socketURL: authority.socketURL, request: binding,
                verifyPeer: { _ in false })
        }
        var admitted: LockedUseActivationClient? = try client(authority, binding)
        try admitted!.check()
        admitted = nil
        rejects { _ = try client(authority, binding) }
        try cancellationRollsBack()
        try parentExitRejectsLateAuthorization()
        print("LOCKED_USE_LATE_AUTHORIZATION_OK")
    }

    static func cancellationRollsBack() throws {
        for point in ["prepared", "deactivated", "plugin_replaced", "configured", "activated"] {
            let root = try LockedUseInstallerTests.fixture()
            defer { try? FileManager.default.removeItem(at: root) }
            let binding = request(), cancellation = Cancellation()
            let authority = try broker(binding, cancellation: cancellation)
            defer { authority.stop() }
            let activation = try client(authority, binding)
            let transaction = LockedUseInstallerTests.transaction(root, authorize: { try activation.check() },
                checkpoint: { if $0 == point { cancellation.stop() } })
            rejects { try transaction.install(source: root.appendingPathComponent("source.bundle"),
                configuration: ["version": "new"]) }
            let configuration = try LockedUseInstallerTests.read(root.appendingPathComponent("support/locked-use.plist"))
            let executable = try String(contentsOf: root.appendingPathComponent("installed.bundle/executable"), encoding: .utf8)
            let rights = try LockedUseInstallerTests.read(root.appendingPathComponent("rights.plist"))
            precondition(configuration["version"] as? String == "old" && executable == "old")
            precondition((rights[LockedUseInstallerTests.screen] as! [String: Any])["rule"] as! [String]
                == [LockedUseInstallerTests.remote, "authenticate-session-owner"])
            precondition(!FileManager.default.fileExists(atPath: root.appendingPathComponent("support/install-transaction").path))
        }
    }

    static func child() throws {
        let binding = request(), authority = try broker(binding)
        defer { authority.stop() }
        var value = binding.payload; value["socket"] = authority.socketURL.path
        var line = try JSONSerialization.data(withJSONObject: value); line.append(10)
        FileHandle.standardOutput.write(line)
        var byte: UInt8 = 0
        _ = Darwin.read(STDIN_FILENO, &byte, 1)
    }

    static func parentExitRejectsLateAuthorization() throws {
        let helper = Process(), output = Pipe(), input = Pipe()
        helper.executableURL = Bundle.main.executableURL!
        helper.arguments = ["--activation-helper-child"]
        helper.standardOutput = output; helper.standardInput = input
        try helper.run()
        let data = output.fileHandleForReading.availableData
        let value = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        let socket = URL(fileURLWithPath: value["socket"] as! String)
        let binding = LockedUseActivationRequest(requestID: value["request_id"] as! String,
            generation: value["generation"] as! String, arguments: value["arguments"] as! [String],
            ownerUID: (value["owner_uid"] as! NSNumber).uint32Value)
        // Kill the actual helper process before the privileged side claims the
        // request, reproducing an authorization dialog accepted after timeout.
        kill(helper.processIdentifier, SIGKILL); helper.waitUntilExit()
        defer { try? FileManager.default.removeItem(at: socket.deletingLastPathComponent()) }
        let root = try LockedUseInstallerTests.fixture()
        defer { try? FileManager.default.removeItem(at: root) }
        rejects {
            let activation = try LockedUseActivationClient(socketURL: socket, request: binding,
                verifyPeer: { _ in true })
            try LockedUseInstallerTests.transaction(root, authorize: { try activation.check() })
                .uninstall()
        }
        let configuration = try LockedUseInstallerTests.read(root.appendingPathComponent("support/locked-use.plist"))
        precondition(configuration["version"] as? String == "old")
        precondition(!FileManager.default.fileExists(atPath: root.appendingPathComponent("support/installation.lock").path))
    }
}
