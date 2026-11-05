import AppKit
import ApplicationServices

func performAction(app: ResolvedApp, action: [String: Any]) throws {
    guard let kind = action["kind"] as? String else {
        throw ActionError.failure(kind: "invalid_params", message: "action.kind is required")
    }
    switch kind {
    case "select_text", "key_down", "key_up", "move", "drag_step":
        try Actions.extended(kind, action: action, app: app)
    case "click":
        try Actions.click(
            app: app,
            elementIndex: action["element_index"] as? Int,
            x: action["x"] as? Double,
            y: action["y"] as? Double,
            button: (action["mouse_button"] as? String) ?? "left",
            clickCount: (action["click_count"] as? Int) ?? 1,
            keyChord: action["key"] as? String,
            duration: action["duration"] as? Double
        )
    case "drag":
        guard let fromX = action["from_x"] as? Double, let fromY = action["from_y"] as? Double,
              let toX = action["to_x"] as? Double, let toY = action["to_y"] as? Double else {
            throw ActionError.failure(kind: "invalid_params", message: "drag requires from_x/from_y/to_x/to_y")
        }
        try Actions.drag(app: app, fromX: fromX, fromY: fromY, toX: toX, toY: toY)
    case "type_text":
        guard let text = action["text"] as? String else {
            throw ActionError.failure(kind: "invalid_params", message: "type_text requires text")
        }
        try Actions.typeText(text)
    case "press_key":
        guard let key = action["key"] as? String else {
            throw ActionError.failure(kind: "invalid_params", message: "press_key requires key")
        }
        try Actions.pressKey(key, duration: action["duration"] as? Double)
    case "scroll":
        try Actions.scroll(
            elementIndex: action["element_index"] as? Int,
            x: action["x"] as? Double,
            y: action["y"] as? Double,
            app: app,
            direction: (action["direction"] as? String) ?? "down",
            pages: (action["pages"] as? Double) ?? 1
        )
    case "set_value":
        guard let index = action["element_index"] as? Int, let value = action["value"] as? String else {
            throw ActionError.failure(kind: "invalid_params", message: "set_value requires element_index and value")
        }
        try Actions.setValue(app: app, elementIndex: index, value: value)
    case "secondary_action":
        guard let index = action["element_index"] as? Int, let name = action["action"] as? String else {
            throw ActionError.failure(kind: "invalid_params", message: "secondary_action requires element_index and action")
        }
        try Actions.secondaryAction(app: app, elementIndex: index, action: name)
    case "paste":
        guard let text = action["text"] as? String else {
            throw ActionError.failure(kind: "invalid_params", message: "paste requires text")
        }
        try Actions.paste(app: app, text: text, format: (action["format"] as? String) ?? "text")
    default:
        throw ActionError.failure(kind: "invalid_params", message: "unknown action kind '\(kind)'")
    }
}

func dispatch(_ method: String, _ params: [String: Any]) -> Result<Any, JsonRpcError> {
    var presentationSession: NativeSession?
    do {
        if MeetingAudioSessions.methods.contains(method) {
            return .success(try MeetingAudioSessions.shared.perform(method, params: params))
        }
        if method == "capabilities" {
            var value = NativeIntegrations.status()
            value["input_support"] = BackgroundInputSPI.support
            value["keyboard_input"] = NativeKeyboard.capabilities
            value["screen_locked"] = NativeScreenState.isLocked(CGSessionCopyCurrentDictionary() as? [String: Any])
            return .success(value)
        }
        if method == "permissions_status" { return .success(NativePermissions.status()) }
        if ["locked_use_status", "locked_use_probe"].contains(method) {
            return .success(LockedUseCoordinator.shared.probe())
        }
        guard let id = params["session_id"] as? String else {
            throw ActionError.failure(kind: "invalid_params", message: "session_id is required")
        }
        let owner = try Sessions.owner(params)
        if method == "begin_session" {
            guard let rawMode = params["input_mode"] as? String, let mode = NativeInputMode(rawValue: rawMode) else {
                throw ActionError.failure(kind: "invalid_params", message: "input_mode is required")
            }
            let session = try Sessions.shared.begin(id, owner: owner, inputMode: mode)
            return .success(session.inputBinding.merging(["session_id": id,
                "artifact_root": session.artifactDirectory.path, "ok": true]) { _, new in new })
        }
        if ["audio_status", "audio_stop", "audio_ack"].contains(method) {
            let session = try Sessions.shared.requireAudio(id, owner: owner)
            try session.validateInputBinding(params)
            let recordingID = params["recording_id"] as? String
            if method == "audio_status" { return .success(try AudioCapture.shared.status(id, recordingID: recordingID)) }
            if method == "audio_stop" {
                let reason = params["end_reason"] as? String ?? "model_stopped"
                guard AudioCapture.endReasons.contains(reason) else {
                    throw ActionError.failure(kind: "invalid_params", message: "invalid recording end_reason")
                }
                return .success(try AudioCapture.shared.stop(session, recordingID: recordingID, reason: reason))
            }
            guard let recordingID = recordingID, !recordingID.isEmpty else {
                throw ActionError.failure(kind: "invalid_params", message: "recording_id is required")
            }
            return .success(try AudioCapture.shared.acknowledge(id, recordingID: recordingID))
        }
        let session = try Sessions.shared.require(id, owner: owner)
        try session.validateInputBinding(params)
        presentationSession = session
        let resourceMethod = ["audio_start", "audio_stop", "connector_call", "clipboard_read", "clipboard_write", "clipboard_release"].contains(method)
        if resourceMethod { NativePresentation.shared.update(session, phase: "acting") }
        defer { if resourceMethod { NativePresentation.shared.update(session, phase: "idle") } }
        let sequence = (params["_native_receive_sequence"] as? NSNumber)?.uint64Value ?? UInt64.max
        let endReason = params["end_reason"] as? String
        if let reason = endReason, !AudioCapture.endReasons.contains(reason) {
            throw ActionError.failure(kind: "invalid_params", message: "invalid recording end_reason")
        }
        switch method {
        case "end_session": Sessions.shared.end(id); return .success(["ok": true])
        case "stop_session":
            Sessions.shared.stop(id, sequence: sequence); Sessions.shared.cleanupStopped(session, reason: endReason ?? "session_ended"); return .success(["ok": true])
        case "cancel":
            session.cancel(sequence: sequence); HeldInput.shared.release(id)
            Sessions.shared.cleanupStopped(session, reason: endReason ?? "cancelled"); return .success(["ok": true])
        case "reset", "reset_session":
            session.cancel(sequence: sequence); HeldInput.shared.release(id)
            Sessions.shared.cleanupStopped(session, reason: endReason ?? "session_reset")
            try session.reset(sequence: sequence)
            NativePresentation.shared.update(session, phase: "idle", resumed: true)
            return .success(session.inputBinding.merging(["ok": true]) { _, new in new })
        case "pause_session":
            guard session.pause() else {
                throw ActionError.failure(kind: "user_stopped_session", message: "a stopped session cannot pause or resume")
            }
            HeldInput.shared.release(id); Sessions.shared.cleanupStopped(session, preserveWindows: true, reason: endReason ?? "user_paused")
            NativePresentation.shared.update(session, phase: "paused")
            NativeInputPresentation.shared.update(session, route: nil, phase: "paused")
            return .success(session.inputBinding.merging(["ok": true, "phase": "paused"]) { _, new in new })
        case "resume_session":
            try session.resume()
            NativePresentation.shared.update(session, phase: "idle", resumed: true)
            return .success(session.inputBinding.merging(["ok": true, "phase": "idle", "requires_observation": true]) { _, new in new })
        case "presentation_update":
            guard let phase = params["phase"] as? String,
                  ["awaiting_permission", "idle", "paused"].contains(phase) else {
                throw ActionError.failure(kind: "invalid_params", message: "invalid presentation phase")
            }
            NativePresentation.shared.update(session, phase: phase, canResume: params["can_resume"] as? Bool,
                resumeBlockedReason: params["resume_blocked_reason"] as? String)
            return .success(["ok": true])
        case "locked_use_disable":
            return .success(try LockedUseCoordinator.shared.disable(session, params: params))
        case "locked_use_enable":
            return .success(try LockedUseCoordinator.shared.enable(session, params: params))
        case "locked_use_renew":
            return .success(try LockedUseCoordinator.shared.renew(session, params: params))
        case "permission_request":
            guard let capability = params["capability"] as? String else {
                throw ActionError.failure(kind: "invalid_params", message: "capability is required")
            }
            return .success(try NativeIntegrations.requestAccess(capability, session: session))
        default: break
        }
        if ["get_app_state", "list_windows", "perform_action", "activate_app", "launch_app",
            "clipboard_read", "clipboard_write", "audio_start"].contains(method) {
            try LockedUseCoordinator.shared.ensureUnlocked(session)
            try NativeScreenState.requireUnlocked()
        }
        if session.consumeObservationRefresh() { session.snapshots.removeAll(); session.previousText.removeAll() }
        if ["locked_use_install", "locked_use_uninstall"].contains(method) {
            let cancellation = session.cancellation
            try cancellation.check()
            LockedUseCoordinator.shared.end()
            return .success(try LockedUseManagement.install(method == "locked_use_install",
                cancellation: cancellation, generation: session.inputGeneration))
        }
        try session.cancellation.check()
        if method == "clipboard_read" { return .success(try NativeClipboard.read(session: session)) }
        if method == "clipboard_write" {
            return .success(try NativeClipboard.write(text: params["text"] as? String ?? "",
                format: params["format"] as? String ?? "text", session: session))
        }
        if method == "clipboard_release" {
            return .success(try NativeClipboard.release(handle: params["handle"] as? String ?? "", sessionID: id))
        }
        if method == "connector_call" {
            guard let connector = params["connector"] as? String, let operation = params["operation"] as? String,
                  let arguments = params["arguments"] as? [String: Any],
                  ["calendar", "contacts", "messages"].contains(connector),
                  ["list", "create", "update", "delete", "services", "resolve_recipient", "send"].contains(operation) else {
                throw ActionError.failure(kind: "invalid_params", message: "invalid connector operation")
            }
            return .success(try NativeIntegrations.handle(connector + "_" + operation,
                params: arguments, session: session))
        }
        if method.hasPrefix("calendar_") || method.hasPrefix("contacts_") || method.hasPrefix("messages_") {
            return .success(try NativeIntegrations.handle(method, params: params, session: session))
        }
        if method == "audio_start" {
            return .success(try AudioCapture.shared.start(source: params["source"] as? String ?? "", session: session,
                maxDurationMilliseconds: AudioCapture.duration(params["max_duration_ms"])))
        }
        if method == "accessibility_status" { return .success(["trusted": AxEngine.accessibilityTrusted()]) }
        if method == "list_apps" { return .success(["apps": AppResolver.runningApps().compactMap { try? AppIdentity.payload($0) }]) }
        guard let identifier = params["app"] as? String, !identifier.isEmpty else {
            throw ActionError.failure(kind: "invalid_params", message: "app is required")
        }
        if method == "resolve_app" {
            if let running = try AppResolver.resolve(identifier) {
                try TargetPolicy.check(running)
                NativePresentation.shared.update(session, phase: "idle", target: try AppIcon.target(running))
                return .success(try AppIcon.identity(running, session: session))
            }
            let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: identifier)
                ?? NSWorkspace.shared.fullPath(forApplication: identifier).map { URL(fileURLWithPath: $0) }
            guard let url = url, let bundle = Bundle(url: url), let bundleID = bundle.bundleIdentifier else {
                throw ActionError.failure(kind: "app_not_found", message: "application is not installed")
            }
            let resolved = ResolvedApp(id: bundleID, displayName: url.deletingPathExtension().lastPathComponent,
                pid: 0, bundleId: bundleID)
            try TargetPolicy.check(resolved)
            return .success(try AppIcon.identity(resolved, session: session, bundleURL: url))
        }
        if method == "launch_app" {
            guard params["expected_identity_digest"] as? String != nil else {
                throw ActionError.failure(kind: "invalid_params", message: "expected_identity_digest is required")
            }
            guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: identifier),
                  let bundleID = Bundle(url: url)?.bundleIdentifier else {
                throw ActionError.failure(kind: "app_not_found", message: "an installed bundle identifier is required")
            }
            let installed = ResolvedApp(id: bundleID, displayName: identifier, pid: 0, bundleId: bundleID)
            try TargetPolicy.check(installed)
            if let expected = params["expected_identity_digest"] as? String,
               try AppIdentity.payload(installed, bundleURL: url)["identity_digest"] as? String != expected {
                throw ActionError.failure(kind: "target_identity_changed", message: "application code identity changed")
            }
            try SyntheticInput.shared.beginInputLease(session.id)
            try session.cancellation.check()
            NativePresentation.shared.update(session, phase: "acting", target: try AppIcon.target(installed))
            let launched: NSRunningApplication = try WindowCapture.wait(session: session) { done in
                let configuration = NSWorkspace.OpenConfiguration()
                configuration.activates = session.inputMode == .foreground
                NSWorkspace.shared.openApplication(at: url, configuration: configuration) { done($0, $1) }
            }
            guard let app = try AppResolver.resolve("pid:\(launched.processIdentifier)") else {
                throw ActionError.failure(kind: "app_not_found", message: "launched application is not available")
            }
            NativePresentation.shared.update(session, phase: "idle", target: try AppIcon.target(app))
            return .success(try AppIdentity.payload(app))
        }
        guard let app = try AppResolver.resolve(identifier) else {
            throw ActionError.failure(kind: "app_not_found", message: "application is not running")
        }
        try TargetPolicy.check(app)
        if let expected = params["expected_identity_digest"] as? String,
           try AppIdentity.payload(app)["identity_digest"] as? String != expected {
            throw ActionError.failure(kind: "target_identity_changed", message: "application code identity changed")
        }
        guard AxEngine.accessibilityTrusted() else {
            throw ActionError.failure(kind: "permission_required", message: "Accessibility permission is required")
        }
        if method == "list_windows" {
            return .success(["app": app.id, "windows": try AxEngine.windows(app: app, session: session).map { $0.payload }])
        }
        if method == "get_app_state" {
            let target = try AppIcon.target(app)
            NativePresentation.shared.update(session, phase: "observing", target: target)
            let result = try AxEngine.appState(app: app, session: session,
                windowID: params["window_id"] as? String, disableDiff: params["disable_diff"] as? Bool ?? false)
            if let image = result["screenshot"] as? [String: Any], let target = result["target"] as? [String: Any] {
                NativePresentation.shared.preview(session, screenshot: image, target: target)
            }
            NativePresentation.shared.update(session, phase: "idle", target: result["target"] as? [String: Any])
            return .success(result)
        }
        if method == "activate_app" {
            guard session.inputMode == .foreground else {
                throw ActionError.failure(kind: "background_input_requires_foreground_mode", message: "activation requires an explicitly authorized foreground session")
            }
            guard params["expected_identity_digest"] as? String != nil else {
                throw ActionError.failure(kind: "invalid_params", message: "expected_identity_digest is required")
            }
            let window = try AxEngine.selectWindow(app: app, session: session, id: params["window_id"] as? String)
            guard let running = NSRunningApplication(processIdentifier: app.pid) else {
                throw ActionError.failure(kind: "app_not_found", message: "application exited")
            }
            try SyntheticInput.shared.beginInputLease(session.id)
            try session.cancellation.check()
            NativePresentation.shared.update(session, phase: "acting", target: try AppIcon.target(app, window: window))
            if session.inputMode == .foreground {
                _ = running.activate(options: [])
                let result = AXUIElementPerformAction(window.element, kAXRaiseAction as CFString)
                guard result == .success else {
                    throw ActionError.failure(kind: "target_not_focused", message: "cannot raise the selected window")
                }
                try session.cancellation.wait(0.15)
                try TargetPolicy.requireFocused(app, window: window)
            }
            try SyntheticInput.shared.bind(session, app: app, window: window)
            try SyntheticInput.shared.prepareFocus()
            NativePresentation.shared.update(session, phase: "idle")
            return .success(["ok": true, "app": app.id, "window_id": window.id])
        }
        if method == "perform_action" {
            guard params["expected_identity_digest"] as? String != nil,
                  let requestID = params["request_id"] as? String, !requestID.isEmpty,
                  session.actionRequests.insert(requestID).inserted else {
                throw ActionError.failure(kind: "invalid_params", message: "a unique request_id and expected_identity_digest are required")
            }
            guard let token = params["snapshot_id"] as? String,
                  let snapshot = session.snapshots[app.id], snapshot.id == token, snapshot.app.pid == app.pid,
                  snapshot.inputGeneration == session.inputGeneration,
                  (params["window_id"] as? String).map({ $0 == snapshot.window.id }) ?? true,
                  let action = params["action"] as? [String: Any] else {
                throw ActionError.failure(kind: "stale_element", message: "refresh get_app_state before acting")
            }
            let current = try AxEngine.selectWindow(app: app, session: session, id: snapshot.window.id)
            guard current.frame == snapshot.window.frame else {
                throw ActionError.failure(kind: "stale_element", message: "window geometry changed; refresh get_app_state")
            }
            if session.inputMode == .foreground { try TargetPolicy.requireFocused(app, window: current) }
            try SyntheticInput.shared.bind(session, app: app, window: current)
            try SyntheticInput.shared.prepareFocus()
            Actions.session = session; Actions.snapshot = snapshot
            defer {
                Actions.session = nil; Actions.snapshot = nil
                session.snapshots.removeValue(forKey: app.id)
            }
            NativePresentation.shared.update(session, phase: "acting", target: try AppIcon.target(app, window: current))
            try performAction(app: app, action: action)
            try session.cancellation.wait(0.25)
            NativePresentation.shared.update(session, phase: "idle")
            return .success(["ok": true])
        }
        throw ActionError.failure(kind: "method_not_found", message: "unknown method")
    } catch let error as ActionError {
        switch error {
        case .failure(let kind, let message, let extra):
            if let session = presentationSession {
                NativePresentation.shared.update(session, phase: kind == "target_not_focused" ? "focus_required" : "error", error: kind)
            }
            return .failure(JsonRpcError(code: kind == "invalid_params" ? -32602 : -32000,
                kind: kind, message: message, data: extra))
        }
    } catch {
        return .failure(JsonRpcError(code: -32000, kind: "native_error", message: error.localizedDescription))
    }
}
