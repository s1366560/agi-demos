import Carbon
import Foundation

struct NativeKeyboardSources {
    let layoutIdentifier: String?
    let inputSourceIdentifier: String?
    let inputSourceType: String?
}

/// Key names are physical ANSI key positions. Unicode insertion is a separate
/// event path; neither path silently uses AX values, clipboard, or IME commands.
enum NativeKeyboard {
    // HIToolbox aborts when a UI process calls TIS/TSM from another thread
    // while AppKit processes an input-source notification on the main thread.
    private static func onMain<T>(_ operation: () -> T) -> T {
        Thread.isMainThread ? operation() : DispatchQueue.main.sync(execute: operation)
    }

    private static func property(_ source: TISInputSource?, key: CFString) -> String? {
        guard let source, let raw = TISGetInputSourceProperty(source, key) else { return nil }
        return Unmanaged<CFString>.fromOpaque(raw).takeUnretainedValue() as String
    }

    static var layoutIdentifier: String? {
        onMain {
            property(TISCopyCurrentKeyboardLayoutInputSource()?.takeRetainedValue(),
                     key: kTISPropertyInputSourceID)
        }
    }

    static var inputSourceIdentifier: String? {
        onMain {
            property(TISCopyCurrentKeyboardInputSource()?.takeRetainedValue(),
                     key: kTISPropertyInputSourceID)
        }
    }

    static var capabilities: [String: Any] {
        capabilities(readSources: {
            let source = TISCopyCurrentKeyboardInputSource()?.takeRetainedValue()
            return NativeKeyboardSources(layoutIdentifier: layoutIdentifier,
                inputSourceIdentifier: property(source, key: kTISPropertyInputSourceID),
                inputSourceType: property(source, key: kTISPropertyInputSourceType))
        })
    }

    /// Keep the OS reader inside the main-thread boundary, including refreshes
    /// requested by IPC while AppKit delivers input-source notifications.
    static func capabilities(readSources: () -> NativeKeyboardSources) -> [String: Any] {
        onMain {
            let sources = readSources()
            return [
                "key_names": "ansi_us_physical_positions",
                "key_interpretation": "target_application_input_source",
                "keyboard_layout": sources.layoutIdentifier ?? "unavailable",
                "input_source": sources.inputSourceIdentifier ?? "unavailable",
                "input_source_type": sources.inputSourceType ?? "unavailable",
                "literal_text": "unicode_key_events", "ime_composition_supported": false,
                "secure_input": "blocked", "implicit_clipboard_fallback": false,
                "implicit_ax_fallback": false,
            ]
        }
    }
}
