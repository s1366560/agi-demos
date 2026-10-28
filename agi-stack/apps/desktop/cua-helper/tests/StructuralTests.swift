import AppKit
import Foundation

@main
enum StructuralTests {
    static func main() throws {
        if CommandLine.arguments == [CommandLine.arguments[0], "--input-watchdog"] { InputWatchdogWorker.run() }
        if CommandLine.arguments.count == 4 && CommandLine.arguments[1] == "--install-transaction-child" {
            try LockedUseInstallerTests.child(CommandLine.arguments)
        }
        if CommandLine.arguments.count == 2 && CommandLine.arguments[1] == "--activation-helper-child" {
            try LockedUseActivationTests.child()
            return
        }
        try WindowIdentityTests.run()
        if CommandLine.arguments == [CommandLine.arguments[0], "--window-identity-tests"] {
            print("CUA_WINDOW_IDENTITY_TESTS_OK")
            return
        }
        keyboardSourceTests()
        if CommandLine.arguments == [CommandLine.arguments[0], "--keyboard-sources"] {
            print("CUA_KEYBOARD_SOURCE_TESTS_OK")
            return
        }
        try LockedUseTests.run()
        try LockedUseInstallerTests.run()
        try LockedUseActivationTests.run()
        try InputOutputTests.run()
        let payload = Data("{\"jsonrpc\":\"2.0\",\"id\":1}".utf8)
        let frame = encodeFrame(payload)
        let decoder = FrameDecoder()
        let partial = try decoder.append(frame.prefix(2))
        precondition(partial.isEmpty)
        let complete = try decoder.append(frame.dropFirst(2))
        precondition(complete.first == payload)
        precondition(NativeScreenMonitor.unavailableReason(nil) == "console_session_unavailable")
        precondition(NativeScreenMonitor.unavailableReason(["CGSSessionScreenIsLocked": true]) == "screen_locked")
        precondition(NativeScreenMonitor.unavailableReason([kCGSessionOnConsoleKey as String: false]) == "console_session_inactive")
        precondition(NativeScreenMonitor.unavailableReason([kCGSessionLoginDoneKey as String: false]) == "console_session_inactive")
        precondition(NativeScreenMonitor.unavailableReason([
            kCGSessionOnConsoleKey as String: true, kCGSessionLoginDoneKey as String: true]) == nil)
        var invalid = UInt32(maxFrameBytes + 1).littleEndian
        do {
            _ = try FrameDecoder().append(Data(bytes: &invalid, count: 4))
            preconditionFailure("oversized frame accepted")
        } catch {}
        let range = try Actions.selectionRange(value: "hello hello", text: "hello",
            prefix: "hello ", suffix: nil, cursor: "select")
        precondition(range == NSRange(location: 6, length: 5))
        let unicode = try Actions.selectionRange(value: "a\u{1F9ED}b", text: "\u{1F9ED}",
            prefix: nil, suffix: nil, cursor: "after")
        precondition(unicode == NSRange(location: 3, length: 0))
        do {
            _ = try Actions.selectionRange(value: "hello hello", text: "hello",
                prefix: nil, suffix: nil, cursor: "select")
            preconditionFailure("ambiguous selection accepted")
        } catch {}
        let owner = Dictionary(uniqueKeysWithValues: Sessions.ownerFields.map { ($0, "fixture-" + $0) })
        let targetedMouse = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown,
            mouseCursorPosition: CGPoint(x: 20, y: 30), mouseButton: .left)!
        BackgroundInputSPI.setTargetWindow(targetedMouse, 12345)
        precondition(NSEvent(cgEvent: targetedMouse)?.windowNumber == 12345,
            "a process-directed mouse event must retain its AppKit window binding")
        var session = try Sessions.shared.begin("structural-test", owner: owner)
        _ = NSApplication.shared
        NSApp.setActivationPolicy(.accessory)
        let hiddenWindow = NSPanel(contentRect: CGRect(x: -10000, y: -10000, width: 20, height: 20),
            styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        hiddenWindow.isReleasedWhenClosed = false
        // Register a real WindowServer window without activating the test app or
        // showing test content on any display. Unordered NSWindows have no live ID.
        hiddenWindow.orderBack(nil)
        hiddenWindow.displayIfNeeded()
        // AppKit flushes a new window to WindowServer on its run loop. Having
        // a window number does not yet mean that the geometry was registered.
        let registrationDeadline = Date(timeIntervalSinceNow: 1)
        while (CGWindowListCopyWindowInfo(.optionIncludingWindow,
            CGWindowID(hiddenWindow.windowNumber)) as? [[String: Any]])?.isEmpty != false,
              Date() < registrationDeadline {
            RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.01))
        }
        let hiddenNativeWindow = NativeWindow(id: "input-route-hidden", element: AXUIElementCreateApplication(getpid()),
            frame: hiddenWindow.frame, title: "Hidden route fixture", captureID: CGWindowID(hiddenWindow.windowNumber))
        let ownApp = ResolvedApp(id: "input-route-fixture", displayName: "Input route fixture", pid: getpid(), bundleId: nil)
        let route = try InputRoute(session: session, app: ownApp, window: hiddenNativeWindow)
        try route.validate()
        var reusedPID = try JSONSerialization.jsonObject(with: JSONEncoder().encode(route)) as! [String: Any]
        reusedPID["startMicroseconds"] = route.startMicroseconds + 1
        let staleRoute = try JSONDecoder().decode(InputRoute.self,
            from: JSONSerialization.data(withJSONObject: reusedPID))
        do {
            try staleRoute.validate()
            preconditionFailure("a reused process identifier must never receive recovery input")
        } catch ActionError.failure(let kind, _, _) { precondition(kind == "stale_input_target") }
        hiddenWindow.close()
        do {
            var other = owner; other["device_id"] = "other"
            _ = try Sessions.shared.require(session.id, owner: other)
            preconditionFailure("cross-device session accepted")
        } catch {}
        precondition(TargetPolicy.forbidden.allSatisfy { $0 == $0.lowercased() })
        precondition(SyntheticInput.ownedFlags(code: 0, flags: .maskShift,
            inherited: .maskShift).isEmpty)
        precondition(SyntheticInput.ownedFlags(code: 0, flags: [.maskShift, .maskCommand],
            inherited: .maskShift) == .maskCommand)
        precondition(SyntheticInput.ownedFlags(code: 0, flags: .maskCommand,
            inherited: .maskCommand, explicit: .maskCommand) == .maskCommand)
        precondition(FileManager.default.fileExists(atPath: session.artifactDirectory.path))
        NativePresentation.shared.update(session, phase: "observing", target: ["app_id": "fixture", "display_name": "Fixture",
            "process_id": 0, "identity_digest": "fixture-code"])
        session.pause()
        NativePresentation.shared.update(session, phase: "paused")
        NativePresentation.shared.update(session, phase: "acting")
        precondition(NativePresentation.shared.snapshot().first?["phase"] as? String == "paused")
        let window = NativeWindow(id: "owned-window", element: AXUIElementCreateApplication(getpid()),
            frame: CGRect(x: 0, y: 0, width: 100, height: 100), title: "Fixture", captureID: nil)
        let app = ResolvedApp(id: "fixture", displayName: "Fixture", pid: getpid(), bundleId: nil)
        session.windows[app.id] = [window]
        session.snapshots[app.id] = Snapshot(id: "before-pause", app: app, window: window, records: [:])
        let pauseParams: [String: Any] = session.inputBinding.merging(owner) { _, value in value }
            .merging(["session_id": session.id]) { _, value in value }
        if case .failure(let error) = dispatch("pause_session", pauseParams) {
            preconditionFailure("pause failed: \(error)")
        }
        precondition(session.snapshots.isEmpty)
        precondition(session.windows[app.id]?.first?.id == window.id)
        try session.resume()
        precondition(session.snapshots.isEmpty)
        precondition(session.windows[app.id]?.first?.id == window.id)
        precondition(AudioCapture.shared.status(session.id)["recording"] as? Bool == false)
        NativePresentation.shared.update(session, phase: "idle", resumed: true)
        Sessions.shared.stop(session.id)
        NativePresentation.shared.update(session, phase: "error", error: "late_action_error")
        precondition(NativePresentation.shared.snapshot().first?["phase"] as? String == "stopped")
        do {try session.resume();preconditionFailure("terminal session resumed")} catch {}
        do { try session.cancellation.check(); preconditionFailure("stop ignored") } catch {}
        do {try session.reset();preconditionFailure("terminal reset revived a stopped session")} catch {}
        Sessions.shared.end(session.id)
        session = try Sessions.shared.begin("structural-recovery", owner: owner)
        session.cancel(sequence: 30)
        do {try session.reset(sequence: 20);preconditionFailure("earlier reset erased a later cancellation")} catch {}
        do {try session.cancellation.check();preconditionFailure("late cancellation lost")} catch {}
        try session.reset(sequence: 40)
        try session.cancellation.check()
        session.pause()
        do {try session.reset(sequence: 50);preconditionFailure("reset revived paused session")} catch {}
        try session.resume()
        session.stop(sequence: 70)
        do {try session.reset(sequence: 60);preconditionFailure("later terminal stop lost")} catch {}
        Sessions.shared.end(session.id)
        session = try Sessions.shared.begin("structural-records", owner: owner)
        session.windows[app.id] = [window]
        for (error, kind) in [(AXError.cannotComplete,"accessibility_unavailable"),(.apiDisabled,"permission_required"),(.invalidUIElement,"stale_target")] {
            do {
                _ = try AxEngine.windows(app: app, session: session, reader: { _ in
                    try AxEngine.checkedWindowElements(error: error, value: nil)
                })
                preconditionFailure("failed AX read accepted")
            } catch ActionError.failure(let actual, _, let details) {
                precondition(actual == kind && details["ax_error"] as? Int32 == error.rawValue)
            }
            precondition(session.windows[app.id]?.first?.id == window.id)
        }
        session.pause()
        Sessions.shared.cleanupStopped(session, preserveWindows: true)
        try session.resume()
        let empty = try AxEngine.windows(app: app, session: session, reader: { _ in
            try AxEngine.checkedWindowElements(error: .success, value: [] as [AXUIElement] as CFArray)
        })
        precondition(empty.isEmpty && session.windows[app.id]?.isEmpty == true)
        precondition(NativeScreenState.isLocked(["CGSSessionScreenIsLocked": true]))
        do {try NativeScreenState.requireUnlocked(["CGSSessionScreenIsLocked": true]);preconditionFailure("locked desktop accepted")} catch ActionError.failure(let kind, _, _) {precondition(kind == "screen_locked")}
        try NativeScreenState.requireUnlocked(["CGSSessionScreenIsLocked": false])
        try NativeScreenState.requireUnlocked(nil)
        let file = session.artifactDirectory.appendingPathComponent("unsigned-fixture")
        try Data("first executable".utf8).write(to: file)
        let firstDigest = AppIdentity.contentDigest(file)
        try Data("replacement executable".utf8).write(to: file)
        precondition(AppIdentity.contentDigest(file) != firstDigest)
        try AudioMixingTests.run(root: session.artifactDirectory)
        try AudioCaptureTests.run()
        try ArtifactRetentionTests.run()
        let testBoard = NSPasteboard(name: NSPasteboard.Name("memstack-cua-test-" + UUID().uuidString))
        NativeClipboard.board = testBoard
        testBoard.clearContents(); testBoard.setString("original", forType: .string)
        testBoard.setData(Data("<b>original</b>".utf8), forType: .html)
        let originalHTML = testBoard.data(forType: .html)
        let first = try NativeClipboard.write(text: "first", format: "text", session: session)["handle"] as! String
        let second = try NativeClipboard.write(text: "second", format: "html", session: session)["handle"] as! String
        _ = try NativeClipboard.release(handle: first, sessionID: session.id)
        _ = try NativeClipboard.release(handle: second, sessionID: session.id)
        precondition(testBoard.string(forType: .string) == "original" && testBoard.data(forType: .html) == originalHTML)
        _ = try NativeClipboard.write(text: "owned", format: "text", session: session)
        testBoard.clearContents(); testBoard.setString("local replacement", forType: .string)
        NativeClipboard.end(session.id)
        precondition(testBoard.string(forType: .string) == "local replacement")
        testBoard.releaseGlobally(); NativeClipboard.board = .general
        do {
            _ = try NativeRecords.fields(["id": "record-id", "fields": ["arbitrary_script": "ignored"]],
                allowed: ["given_name"])
            preconditionFailure("unlisted record field accepted")
        } catch {}
        let path = session.artifactDirectory.path
        Sessions.shared.end(session.id)
        precondition(!FileManager.default.fileExists(atPath: path))
        try presentationTests(owner: owner)
        print("CUA_STRUCTURAL_TESTS_OK")
    }

    static func keyboardSourceTests() {
        // Exercise the IPC capability-building path with an OS reader that
        // enforces HIToolbox's real main-thread requirement. Replacing the
        // source between calls must refresh the result, including the distinct
        // IME identifier and base keyboard layout. No system source is changed.
        let sources = [
            NativeKeyboardSources(layoutIdentifier: "com.apple.keylayout.French",
                inputSourceIdentifier: "com.apple.keylayout.French",
                inputSourceType: "TISTypeKeyboardLayout"),
            NativeKeyboardSources(layoutIdentifier: "com.apple.keylayout.US",
                inputSourceIdentifier: "com.apple.inputmethod.SCIM.ITABC",
                inputSourceType: "TISTypeKeyboardInputMode"),
            NativeKeyboardSources(layoutIdentifier: nil, inputSourceIdentifier: nil,
                inputSourceType: nil),
        ]
        let direct = NativeKeyboard.capabilities(readSources: {
            precondition(Thread.isMainThread, "TIS reader left the main thread")
            return sources[0]
        })
        precondition(direct["keyboard_layout"] as? String == sources[0].layoutIdentifier)
        precondition(direct["key_names"] as? String == "ansi_us_physical_positions")
        precondition(direct["literal_text"] as? String == "unicode_key_events")
        precondition(direct["ime_composition_supported"] as? Bool == false)
        let finished = DispatchSemaphore(value: 0)
        let queue = DispatchQueue(label: "memstack.cua.keyboard-source-test")
        queue.async {
            precondition(!Thread.isMainThread, "regression requires an IPC-style worker")
            for source in sources {
                let metadata = NativeKeyboard.capabilities(readSources: {
                    precondition(Thread.isMainThread,
                        "worker called TIS concurrently with the AppKit main thread")
                    return source
                })
                precondition(metadata["keyboard_layout"] as? String
                    == (source.layoutIdentifier ?? "unavailable"))
                precondition(metadata["input_source"] as? String
                    == (source.inputSourceIdentifier ?? "unavailable"))
                precondition(metadata["input_source_type"] as? String
                    == (source.inputSourceType ?? "unavailable"))
                precondition(metadata["implicit_clipboard_fallback"] as? Bool == false)
                precondition(metadata["implicit_ax_fallback"] as? Bool == false)
            }
            // Include the real Carbon reader without selecting an input source
            // or creating NSApplication/windows, even when the screen is locked.
            let actual = NativeKeyboard.capabilities
            precondition(JSONSerialization.isValidJSONObject(actual))
            precondition(actual["input_source"] is String && actual["keyboard_layout"] is String)
            finished.signal()
        }
        let deadline = Date(timeIntervalSinceNow: 3)
        while finished.wait(timeout: .now()) != .success {
            precondition(Date() < deadline, "keyboard capability worker deadlocked on the main thread")
            RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.005))
        }
    }

    static func presentationTests(owner: [String: String]) throws {
        let session = try Sessions.shared.begin("structural-menu", owner: owner)
        defer { Sessions.shared.end(session.id) }
        let nativeWindow = NativeWindow(id: "window-one", element: AXUIElementCreateApplication(getpid()),
            frame: CGRect(x: 0, y: 0, width: 10, height: 10), title: "First window", captureID: nil)
        let app = ResolvedApp(id: "fixture", displayName: "Fixture", pid: getpid(), bundleId: nil)
        // AppIcon.target emits the native pid_t; serialization and host-owned
        // dictionaries can bridge it to NSNumber or Swift Int.
        let target: [String: Any] = ["app_id": app.id, "display_name": app.displayName,
            "process_id": app.pid, "identity_digest": "fixture-code",
            "window_id": nativeWindow.id, "window_title": nativeWindow.title]
        let jsonTarget = try JSONSerialization.jsonObject(with: JSONSerialization.data(withJSONObject: target)) as! [String: Any]
        var intTarget = target; intTarget["process_id"] = Int(getpid())
        precondition(PresentationTarget(target) == PresentationTarget(jsonTarget))
        precondition(PresentationTarget(target) == PresentationTarget(intTarget))
        for invalid: Any in [true, -1, Int64(Int32.max) + 1, 1.5, "42"] {
            precondition(PresentationTarget.processID(invalid) == nil)
        }
        let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 2, pixelsHigh: 2,
            bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
            colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        let file = session.artifactDirectory.appendingPathComponent("preview.png")
        try bitmap.representation(using: .png, properties: [:])!.write(to: file)
        let screenshot: [String: Any] = ["url": file.absoluteString]
        let presentation = NativePresentation.shared
        presentation.update(session, phase: "idle", target: target)
        presentation.preview(session, screenshot: screenshot, target: jsonTarget)
        precondition(presentation.preview(session.id) != nil)
        var appOnly = intTarget; appOnly.removeValue(forKey: "window_id"); appOnly.removeValue(forKey: "window_title")
        presentation.update(session, phase: "observing", target: appOnly)
        precondition(presentation.preview(session.id) != nil)
        let retained = presentation.snapshot().first { ($0["context"] as? [String: String])?["session_id"] == session.id }
        precondition((retained?["target"] as? [String: Any])?["window_id"] as? String == "window-one")
        presentation.update(session, phase: "paused", canResume: true)
        precondition(presentation.preview(session.id) != nil)
        presentation.update(session, phase: "idle", resumed: true)
        precondition(presentation.preview(session.id) != nil)
        for (field, replacement): (String, Any) in [("window_id", "window-two"), ("app_id", "other"),
            ("identity_digest", "replacement-code"), ("process_id", Int(getpid()) + 1)] {
            presentation.update(session, phase: "idle", target: target)
            presentation.preview(session, screenshot: screenshot, target: target)
            var changed = target; changed[field] = replacement
            presentation.update(session, phase: "idle", target: changed)
            precondition(presentation.preview(session.id) == nil)
            presentation.update(session, phase: "idle", target: target)
            precondition(presentation.preview(session.id) == nil, "a discarded preview must not reappear")
        }
        var otherWindow = target; otherWindow["window_id"] = "window-two"
        presentation.preview(session, screenshot: screenshot, target: otherWindow)
        precondition(presentation.preview(session.id) == nil)
        precondition(presentation.menuSnapshot().first { ($0.value["context"] as? [String: String])?["session_id"] == session.id }?.preview == nil)
        presentation.update(session, phase: "idle", target: otherWindow)
        precondition(presentation.preview(session.id) != nil)

        // Construct the actual AppKit rows without opening a menu or a window.
        _ = NSApplication.shared
        let rows = SessionMenuRows()
        let image = NSImage(contentsOf: file)!
        precondition(SessionStatusItem.applicationIcon(jsonTarget, resolve: { _ in (intTarget, image) }) === image)
        for (field, replacement): (String, Any) in [("app_id", "reused-pid-app"),
            ("identity_digest", "replaced-code"), ("process_id", Int(getpid()) + 1)] {
            var changed = intTarget; changed[field] = replacement
            precondition(SessionStatusItem.applicationIcon(target, resolve: { _ in (changed, image) }) == nil)
        }
        var iconLookups = 0
        precondition(rows.applicationIcon(target, load: { iconLookups += 1; return image }) === image)
        precondition(rows.applicationIcon(jsonTarget, load: { iconLookups += 1; return nil }) === image)
        precondition(rows.applicationIcon(otherWindow, load: { iconLookups += 1; return nil }) === image)
        precondition(iconLookups == 1, "phase/window updates must reuse the verified icon")
        var replacedApp = target; replacedApp["identity_digest"] = "replacement-code"
        precondition(rows.applicationIcon(replacedApp, load: { iconLookups += 1; return nil }) == nil)
        precondition(iconLookups == 2)
        var value: [String: Any] = ["target": target, "phase": "idle"]
        func updateRows() {
            rows.update(NativePresentation.MenuSnapshot(value: value, preview: (image, Date())),
                id: session.id, zh: true, icon: image, target: rows,
                action: NSSelectorFromString("testControl:"))
        }
        updateRows()
        let pause = rows.pause
        let header = rows.heading.view
        precondition(rows.icon.image === image && !rows.icon.isHidden)
        precondition(rows.title.stringValue == "Fixture · 就绪")
        precondition(rows.pause.title == "暂停电脑操作" && rows.pause.isEnabled)
        value["phase"] = "paused"; value["can_resume"] = false; updateRows()
        precondition(rows.pause === pause && rows.heading.view === header)
        precondition(!rows.pause.isEnabled && rows.stop.isEnabled)
        value["can_resume"] = true; updateRows()
        precondition(rows.pause === pause && rows.pause.title == "恢复电脑操作" && rows.pause.isEnabled)
        precondition((rows.pause.representedObject as? [String: String])?["method"] == "resume_session")
        value["phase"] = "idle"; updateRows()
        precondition(rows.pause === pause && rows.pause.title == "暂停电脑操作")
        precondition((rows.pause.representedObject as? [String: String])?["method"] == "pause_session")
        value["phase"] = "stopped"; updateRows()
        precondition(rows.pause.isHidden && !rows.pause.isEnabled && rows.stop.isHidden && !rows.stop.isEnabled)
        presentation.update(session, phase: "stopped", userInitiated: true, userAction: "stop")
        presentation.update(session, phase: "paused", userInitiated: true, userAction: "pause", canResume: true)
        presentation.update(session, phase: "idle", resumed: true)
        let stopped = presentation.menuSnapshot().first { ($0.value["context"] as? [String: String])?["session_id"] == session.id }!
        precondition(stopped.value["phase"] as? String == "stopped")
        precondition(stopped.value["can_resume"] as? Bool == false)
        precondition(stopped.value["user_action"] as? String == "stop")
    }
}
