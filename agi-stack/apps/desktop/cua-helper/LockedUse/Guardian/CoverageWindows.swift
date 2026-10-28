import AppKit
import CoreGraphics
import Foundation

/// Own-window observations; never enumerate or infer state from another app's windows.
final class GuardianCoverageWindows {
    private struct BoundWindow {
        let displayID: UInt32
        let window: NSWindow
    }
    private var windows: [BoundWindow] = []
    private var expected: [LockedUseDisplayCoverage] = []
    private let level = Int(CGShieldingWindowLevel()) + 1
    var isEmpty: Bool { windows.isEmpty }

    private func topology(_ screens: [NSScreen]) -> [LockedUseDisplayCoverage]? {
        let displays = screens.compactMap { screen -> LockedUseDisplayCoverage? in
            guard let id = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else {
                return nil
            }
            return LockedUseDisplayCoverage(id: id.uint32Value, appKitFrame: screen.frame,
                quartzFrame: CGDisplayBounds(id.uint32Value), scale: screen.backingScaleFactor)
        }
        guard displays.count == screens.count, LockedUseCoverage.validTopology(displays) else { return nil }
        return displays
    }
    func present() -> Bool {
        guard windows.isEmpty else { return false }
        let screens = NSScreen.screens
        guard let displays = topology(screens) else { return false }
        expected = displays
        for (screen, display) in zip(screens, displays) {
            // init's origin is relative to its screen. setFrame uses global AppKit coordinates.
            let window = NSWindow(contentRect: NSRect(origin: .zero, size: screen.frame.size),
                styleMask: [.borderless], backing: .buffered, defer: false, screen: screen)
            window.animationBehavior = .none
            window.setFrame(display.appKitFrame, display: true, animate: false)
            window.level = NSWindow.Level(rawValue: level)
            window.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
            window.backgroundColor = .black; window.isOpaque = true; window.alphaValue = 1
            window.hasShadow = false; window.isReleasedWhenClosed = false; window.ignoresMouseEvents = true
            let message = NSTextField(labelWithString: NSLocalizedString(
                "Computer Use is active. Press any key or click to return to the lock screen.", comment: "locked use"))
            message.textColor = .white
            message.frame = NSRect(x: 40, y: 40, width: max(1, min(screen.frame.width - 80, 800)), height: 60)
            window.contentView?.addSubview(message)
            windows.append(BoundWindow(displayID: display.id, window: window))
            window.orderFrontRegardless()
        }
        return true
    }
    private func serverState(_ number: Int32) -> LockedUseWindowServerCoverage? {
        guard number > 0,
              let rows = CGWindowListCopyWindowInfo(.optionIncludingWindow, CGWindowID(number)) as? [[String: Any]],
              let row = rows.first(where: { ($0[kCGWindowNumber as String] as? NSNumber)?.int32Value == number }),
              let owner = row[kCGWindowOwnerPID as String] as? NSNumber, owner.int32Value == getpid(),
              let bounds = row[kCGWindowBounds as String] as? [String: Any],
              let frame = CGRect(dictionaryRepresentation: bounds as CFDictionary),
              let onScreen = row[kCGWindowIsOnscreen as String] as? Bool,
              let alpha = row[kCGWindowAlpha as String] as? NSNumber,
              let layer = row[kCGWindowLayer as String] as? NSNumber else { return nil }
        return LockedUseWindowServerCoverage(number: number, ownerPID: owner.int32Value,
            frame: frame, onScreen: onScreen, alpha: alpha.doubleValue, layer: layer.intValue)
    }
    func report() -> LockedUseCoverageReport {
        let current = topology(NSScreen.screens)
        let observed = windows.map { bound in
            let window = bound.window
            let number = Int32(exactly: window.windowNumber) ?? 0
            return LockedUseWindowCoverage(displayID: bound.displayID, number: number,
                appKitFrame: window.frame, visible: window.isVisible, opaque: window.isOpaque,
                alpha: Double(window.alphaValue), level: window.level.rawValue, server: serverState(number))
        }
        return LockedUseCoverage.check(expected: expected, current: current, windows: observed,
            ownerPID: getpid(), requiredLevel: level)
    }
    func close() {
        windows.forEach { $0.window.orderOut(nil) }
        windows.removeAll(); expected.removeAll()
    }
}
