import AppKit
import CoreGraphics
import ScreenCaptureKit

enum WindowCapture {
    static func capture(app: ResolvedApp, window: NativeWindow, session: NativeSession) throws -> [String: Any]? {
        try NativeScreenState.requireUnlocked()
        guard CGPreflightScreenCaptureAccess() else { return nil }
        guard #available(macOS 14.0, *), let windowID = window.captureID else { return nil }
        let shareable = try wait(session: session) { done in
            SCShareableContent.getExcludingDesktopWindows(true, onScreenWindowsOnly: false) { content, error in
                done(content, error)
            }
        }
        guard let selected = shareable.windows.first(where: { $0.windowID == windowID
            && $0.owningApplication?.processID == app.pid }) else {
            throw ActionError.failure(kind: "window_not_found", message: "the capture window no longer exists")
        }
        let configuration = SCStreamConfiguration()
        let ratio = min(1, 1280 / max(1, window.frame.width * 2))
        configuration.width = max(1, Int(window.frame.width * 2 * ratio))
        configuration.height = max(1, Int(window.frame.height * 2 * ratio))
        configuration.showsCursor = false
        configuration.ignoreShadowsSingleWindow = true
        let filter = SCContentFilter(desktopIndependentWindow: selected)
        let image: CGImage = try wait(session: session) { done in
            SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration) { image, error in
                done(image, error)
            }
        }
        let bitmap = NSBitmapImageRep(cgImage: image)
        guard let data = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.8]) else {
            throw ActionError.failure(kind: "capture_failed", message: "cannot encode screenshot")
        }
        let file = session.artifactDirectory.appendingPathComponent("screenshot-\(UUID().uuidString).jpg")
        try data.write(to: file, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        return ["url": file.absoluteString, "width": image.width, "height": image.height, "mime_type": "image/jpeg"]
    }

    static func wait<T>(session: NativeSession, operation: (@escaping (T?, Error?) -> Void) -> Void) throws -> T {
        let semaphore = DispatchSemaphore(value: 0)
        let lock = NSLock()
        var result: T?
        var failure: Error?
        operation { value, error in
            lock.lock(); result = value; failure = error; lock.unlock()
            semaphore.signal()
        }
        let deadline = Date().addingTimeInterval(10)
        while semaphore.wait(timeout: .now() + 0.02) != .success {
            try session.cancellation.check()
            guard Date() < deadline else {
                throw ActionError.failure(kind: "timeout", message: "native operation timed out")
            }
        }
        lock.lock(); let value = result; let error = failure; lock.unlock()
        if let error = error {
            throw ActionError.failure(kind: "native_error", message: error.localizedDescription)
        }
        guard let value = value else {
            throw ActionError.failure(kind: "native_error", message: "native operation returned no result")
        }
        return value
    }
}
