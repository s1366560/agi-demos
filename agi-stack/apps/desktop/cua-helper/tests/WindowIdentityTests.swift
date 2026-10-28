import ApplicationServices
import Foundation

enum WindowIdentityTests {
    private final class Fixture {
        let app = ResolvedApp(id: "window-identity-fixture", displayName: "Fixture", pid: 101, bundleId: nil)
        let first = AXUIElementCreateApplication(10001)
        let second = AXUIElementCreateApplication(10002)
        let session: NativeSession
        var birth = NativeProcessIdentity(pid: 101, startSeconds: 10, startMicroseconds: 20)
        var ax: [(AXUIElement, pid_t, CGWindowID)] = []
        var native: [CGWindowID: NativeWindowServerRecord] = [:]
        var processAvailable = true
        let frame = CGRect(x: 20, y: 30, width: 300, height: 200)
        init() throws {
            session = try NativeSession(id: UUID().uuidString, owner: [:])
            ax = [(first, app.pid, 41)]
            native[41] = NativeWindowServerRecord(windowID: 41, ownerPID: app.pid, frame: frame)
        }
        deinit { try? FileManager.default.removeItem(at: session.artifactDirectory) }
        var reader: WindowIdentityReader {
            WindowIdentityReader(process: { [self] pid in
                processAvailable && pid == birth.pid ? birth : nil
            }, element: { [self] element in
                guard let record = ax.first(where: { CFEqual($0.0, element) }) else { return nil }
                return (record.1, record.2)
            }, window: { [self] in native[$0] }, title: { _ in "Same title" })
        }
        func windows(_ elements: [AXUIElement]) throws -> [NativeWindow] {
            try AxEngine.windows(app: app, session: session, reader: { _ in elements }, identityReader: reader)
        }
    }

    static func run() throws {
        try enumerationAndSpaceTests()
        try staleIdentityTests()
        try failedReadTests()
        try frameAndGenerationTests()
        try routeIdentityTests()
    }

    private static func enumerationAndSpaceTests() throws {
        let fixture = try Fixture()
        let first = try fixture.windows([fixture.first])[0]
        precondition(first.identity?.process == fixture.birth && first.captureID == 41)
        fixture.ax = [(fixture.second, fixture.app.pid, 41)]
        let replaced = try fixture.windows([fixture.second])
        precondition(replaced.count == 1 && replaced[0].id == first.id,
            "a new AX wrapper for the same native window must preserve the opaque ID")
        precondition(CFEqual(replaced[0].element, fixture.second))
        let absent = try fixture.windows([])
        precondition(absent.count == 1 && absent[0].id == first.id,
            "an omitted window remains addressable only while its retained native identity is verified")
        let duplicates = try fixture.windows([fixture.second, fixture.second])
        precondition(duplicates.count == 1)
        fixture.ax = [(fixture.second, fixture.app.pid, 42)]
        fixture.native[42] = NativeWindowServerRecord(windowID: 42,
            ownerPID: fixture.app.pid, frame: fixture.frame)
        let changed = try fixture.windows([fixture.second])
        precondition(changed.count == 1 && changed[0].id != first.id && changed[0].captureID == 42,
            "matching title and geometry must never reuse another native window's identity")
    }

    private static func staleIdentityTests() throws {
        let mutations: [(Fixture) -> Void] = [
            { $0.native.removeValue(forKey: 41) },
            { $0.native[41] = NativeWindowServerRecord(windowID: 41, ownerPID: 999, frame: $0.frame) },
            { $0.native[41] = NativeWindowServerRecord(windowID: 42, ownerPID: $0.app.pid, frame: $0.frame) },
            { $0.ax = [($0.first, 999, 41)] },
            { $0.ax = [] },
            { $0.ax = [($0.first, $0.app.pid, 42)] },
            { $0.birth = NativeProcessIdentity(pid: 101, startSeconds: 10, startMicroseconds: 21) },
            { $0.native[41] = NativeWindowServerRecord(windowID: 41, ownerPID: $0.app.pid, frame: .zero) },
            { $0.native[41] = NativeWindowServerRecord(windowID: 41, ownerPID: $0.app.pid,
                frame: CGRect(x: CGFloat.infinity, y: 30, width: 300, height: 200)) },
        ]
        for mutate in mutations {
            let fixture = try Fixture()
            _ = try fixture.windows([fixture.first])
            mutate(fixture)
            let result = try fixture.windows([])
            precondition(result.isEmpty && fixture.session.windows[fixture.app.id]?.isEmpty == true,
                "an unverified cached native identity must be removed")
        }
        let fixture = try Fixture()
        let first = try fixture.windows([fixture.first])[0]
        fixture.birth = NativeProcessIdentity(pid: 101, startSeconds: 10, startMicroseconds: 21)
        let reusedPID = try fixture.windows([fixture.first])[0]
        precondition(reusedPID.id != first.id && reusedPID.identity?.process == fixture.birth)
    }

    private static func failedReadTests() throws {
        let fixture = try Fixture()
        let first = try fixture.windows([fixture.first])[0]
        let generation = fixture.session.inputGeneration
        do {
            _ = try AxEngine.windows(app: fixture.app, session: fixture.session, reader: { _ in
                try AxEngine.checkedWindowElements(error: .cannotComplete, value: nil)
            }, identityReader: fixture.reader)
            preconditionFailure("an AX enumeration error must be preserved")
        } catch ActionError.failure(let kind, _, let details) {
            precondition(kind == "accessibility_unavailable" && details["ax_error"] as? Int32 == AXError.cannotComplete.rawValue)
        }
        precondition(fixture.session.windows[fixture.app.id]?.first?.id == first.id)
        fixture.processAvailable = false
        do {
            _ = try fixture.windows([])
            preconditionFailure("an absent process must fail observation")
        } catch ActionError.failure(let kind, _, _) { precondition(kind == "stale_target") }
        precondition(fixture.session.windows[fixture.app.id]?.first?.id == first.id)
        precondition(fixture.session.inputGeneration == generation)
        fixture.processAvailable = true
        var reader = fixture.reader
        var reads = 0
        reader.process = { pid in
            reads += 1
            return NativeProcessIdentity(pid: pid, startSeconds: 10, startMicroseconds: reads > 2 ? 21 : 20)
        }
        do {
            _ = try AxEngine.windows(app: fixture.app, session: fixture.session,
                reader: { _ in [fixture.first] }, identityReader: reader)
            preconditionFailure("a process replacement during enumeration must fail")
        } catch ActionError.failure(let kind, _, _) { precondition(kind == "stale_target") }
        precondition(fixture.session.windows[fixture.app.id]?.first?.id == first.id)
        precondition(fixture.session.inputGeneration == generation)
    }

    private static func frameAndGenerationTests() throws {
        let fixture = try Fixture()
        let first = try fixture.windows([fixture.first])[0]
        try fixture.session.observeInputTarget(fixture.app, window: first)
        let generation = fixture.session.inputGeneration
        let movedFrame = fixture.frame.offsetBy(dx: 10, dy: 20)
        fixture.native[41] = NativeWindowServerRecord(windowID: 41, ownerPID: fixture.app.pid, frame: movedFrame)
        let moved = try fixture.windows([])[0]
        precondition(moved.id == first.id && moved.frame == movedFrame)
        precondition(fixture.session.inputGeneration == generation,
            "enumeration alone must not publish a new input generation")
        try fixture.session.observeInputTarget(fixture.app, window: moved)
        precondition(fixture.session.inputGeneration != generation)
    }

    private static func routeIdentityTests() throws {
        let fixture = try Fixture()
        let process = NativeProcessIdentity.read(getpid())!
        let stale = NativeProcessIdentity(pid: process.pid, startSeconds: process.startSeconds,
            startMicroseconds: process.startMicroseconds + 1)
        let window = NativeWindow(id: "stale-route", element: fixture.first, frame: fixture.frame,
            title: "Fixture", captureID: 41, identity: NativeWindowIdentity(process: stale, windowID: 41))
        let app = ResolvedApp(id: "own-process", displayName: "Fixture", pid: getpid(), bundleId: nil)
        do {
            _ = try InputRoute(session: fixture.session, app: app, window: window)
            preconditionFailure("an old observed process birth must not be rebound to a reused PID")
        } catch ActionError.failure(let kind, _, _) { precondition(kind == "stale_input_target") }
    }
}
