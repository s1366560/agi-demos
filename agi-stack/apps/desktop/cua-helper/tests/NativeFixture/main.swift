import AppKit
import Carbon
import Darwin
import WebKit

final class FixtureWebEvents: NSObject, WKScriptMessageHandler {
    let index: Int
    init(index: Int) { self.index = index }
    func userContentController(_ userContentController: WKUserContentController,
                               didReceive message: WKScriptMessage) {
        guard var row = message.body as? [String: Any],
              let path = ProcessInfo.processInfo.environment["CUA_FIXTURE_DOM_LOG"],
              let file = FileHandle(forWritingAtPath: path) else { return }
        row["window_index"] = index
        if let data = try? JSONSerialization.data(withJSONObject: row) {
            file.seekToEndOfFile(); file.write(data); file.write(Data([10]))
        }
        try? file.close()
    }
}

final class FixtureApplication: NSApplication {
    var receivedShiftHeld = false
    var receivedLeftHeld = false
    var shiftLabels: [NSTextField] = []
    var mouseLabels: [NSTextField] = []
    var instructionLabels: [NSTextField] = []
    private var previousComposition: Data?

    func observeInstructions() {
        guard let path = ProcessInfo.processInfo.environment["CUA_FIXTURE_INSTRUCTION_FILE"],
              let message = try? String(contentsOfFile: path, encoding: .utf8) else { return }
        instructionLabels.forEach { label in
            label.stringValue = message; label.isHidden = message.isEmpty
        }
    }

    func observeComposition(_ event: NSEvent? = nil) {
        guard let path = ProcessInfo.processInfo.environment["CUA_FIXTURE_COMPOSITION_LOG"],
              let window = event?.window ?? keyWindow,
              let editor = window.firstResponder as? NSTextView else { return }
        let source = TISCopyCurrentKeyboardInputSource().takeRetainedValue()
        let sourceID = TISGetInputSourceProperty(source, kTISPropertyInputSourceID).map {
            Unmanaged<CFString>.fromOpaque($0).takeUnretainedValue() as String
        } ?? "unknown"
        let marked = editor.markedRange(), selection = editor.selectedRange()
        var value: [String: Any] = [
            "window": window.windowNumber,
            "input_source_id": sourceID, "has_marked_text": editor.hasMarkedText(),
            "context_input_source_id": editor.inputContext?.selectedKeyboardInputSource ?? "unavailable",
            "marked_location": marked.location, "marked_length": marked.length,
            "selected_location": selection.location, "selected_length": selection.length,
            "text": editor.string,
        ]
        guard let state = try? JSONSerialization.data(withJSONObject: value, options: .sortedKeys),
              event != nil || state != previousComposition else { return }
        previousComposition = state
        value["type"] = event?.type.rawValue ?? 0
        value["observed_by"] = event == nil ? "timer" : "event"
        value["source_pid"] = event?.cgEvent?.getIntegerValueField(.eventSourceUnixProcessID) ?? -1
        value["source_tag"] = event?.cgEvent?.getIntegerValueField(.eventSourceUserData) ?? 0
        if let data = try? JSONSerialization.data(withJSONObject: value),
           let file = FileHandle(forWritingAtPath: path) {
            file.seekToEndOfFile(); file.write(data); file.write(Data([10])); try? file.close()
        }
    }
    override func sendEvent(_ event: NSEvent) {
        if event.type == .flagsChanged {
            receivedShiftHeld = event.modifierFlags.contains(.shift)
        } else if event.type == .leftMouseDown { receivedLeftHeld = true }
        else if event.type == .leftMouseUp { receivedLeftHeld = false }
        shiftLabels.forEach { $0.stringValue = "Shift held: \(receivedShiftHeld)" }
        mouseLabels.forEach { $0.stringValue = "Left button held: \(receivedLeftHeld)" }
        let characters = [.keyDown, .keyUp].contains(event.type) ? event.characters ?? "" : ""
        if let path = ProcessInfo.processInfo.environment["CUA_FIXTURE_EVENT_LOG"],
           [.leftMouseDown, .leftMouseUp, .keyDown, .keyUp, .flagsChanged].contains(event.type),
           let data = ("type=\(event.type.rawValue) location=\(event.locationInWindow) flags=\(event.modifierFlags.rawValue) characters=\(characters)\n").data(using: .utf8),
           let file = FileHandle(forWritingAtPath: path) {
            file.seekToEndOfFile(); file.write(data); try? file.close()
        }
        if let path = ProcessInfo.processInfo.environment["CUA_FIXTURE_JSON_LOG"],
           [.leftMouseDown, .leftMouseUp, .leftMouseDragged, .rightMouseDown, .rightMouseUp,
            .otherMouseDown, .otherMouseUp, .mouseMoved, .scrollWheel,
            .keyDown, .keyUp, .flagsChanged].contains(event.type) {
            var value: [String: Any] = [
                "type": event.type.rawValue, "window": event.windowNumber,
                "flags": event.modifierFlags.rawValue, "characters": characters,
                "x": event.locationInWindow.x, "y": event.locationInWindow.y,
                "frontmost_pid": NSWorkspace.shared.frontmostApplication?.processIdentifier ?? -1,
                "source_pid": event.cgEvent?.getIntegerValueField(.eventSourceUnixProcessID) ?? -1,
                "source_tag": event.cgEvent?.getIntegerValueField(.eventSourceUserData) ?? 0,
                "source_state_id": event.cgEvent?.getIntegerValueField(.eventSourceStateID) ?? -2,
                "pressed_mouse_buttons": NSEvent.pressedMouseButtons,
            ]
            if [.keyDown, .keyUp, .flagsChanged].contains(event.type) { value["key_code"] = event.keyCode }
            if [.leftMouseDown, .leftMouseUp, .rightMouseDown, .rightMouseUp,
                .otherMouseDown, .otherMouseUp].contains(event.type) { value["click_count"] = event.clickCount }
            if let data = try? JSONSerialization.data(withJSONObject: value),
               let file = FileHandle(forWritingAtPath: path) {
                file.seekToEndOfFile(); file.write(data); file.write(Data([10])); try? file.close()
            }
        }
        super.sendEvent(event)
        if [.keyDown, .keyUp, .flagsChanged].contains(event.type) { observeComposition(event) }
    }
}
struct SeededRandom: RandomNumberGenerator {
    var state: UInt64
    mutating func next() -> UInt64 {
        state = state &* 6364136223846793005 &+ 1442695040888963407
        return state
    }
}
struct PaintedShape {
    let color: String
    let shape: String
    let center: NSPoint
    var extent: CGFloat = 16
    var path: NSBezierPath {
        let rect = NSRect(x: center.x - extent, y: center.y - extent,
            width: extent * 2, height: extent * 2)
        if shape == "circle" { return NSBezierPath(ovalIn: rect) }
        if shape == "square" { return NSBezierPath(rect: rect) }
        let path = NSBezierPath()
        path.move(to: NSPoint(x: center.x, y: center.y + extent + 1))
        path.line(to: NSPoint(x: center.x - extent - 2, y: center.y - extent + 1))
        path.line(to: NSPoint(x: center.x + extent + 2, y: center.y - extent + 1)); path.close()
        return path
    }
    var nativeColor: NSColor {
        switch color {
        case "red": return NSColor(calibratedRed: 0.88, green: 0.12, blue: 0.16, alpha: 1)
        case "blue": return NSColor(calibratedRed: 0.12, green: 0.32, blue: 0.92, alpha: 1)
        default: return NSColor(calibratedRed: 0.08, green: 0.64, blue: 0.22, alpha: 1)
        }
    }
}
final class PaintedCanvas: NSView {
    let shapes: [PaintedShape]
    let status: NSTextField
    private var dragStart: NSPoint?
    init(frame: NSRect, seed: UInt64, status: NSTextField) {
        self.status = status
        var random = SeededRandom(state: seed)
        var choices = [String]()
        let visualLarge = CommandLine.arguments.contains("--visual-large")
        if visualLarge {
            choices = ["blue:circle", "red:triangle", "green:square"]
        } else {
            for color in ["red", "blue", "green"] {
                for shape in ["circle", "square", "triangle"] { choices.append(color + ":" + shape) }
            }
        }
        choices.shuffle(using: &random)
        shapes = choices.enumerated().map { offset, choice in
            let fields = choice.split(separator: ":")
            return PaintedShape(color: String(fields[0]), shape: String(fields[1]),
                center: NSPoint(x: visualLarge ? 70 + offset * 150 : 29 + offset * 50, y: 60),
                extent: visualLarge ? 48 : 16)
        }
        super.init(frame: frame)
        setAccessibilityElement(false); setAccessibilityChildren([])
    }
    required init?(coder: NSCoder) { fatalError("fixture is constructed directly") }
    override func draw(_ dirtyRect: NSRect) {
        NSColor.white.setFill(); NSBezierPath(rect: bounds).fill()
        for shape in shapes {
            shape.nativeColor.setFill(); shape.path.fill()
            NSColor.black.setStroke(); shape.path.lineWidth = 1; shape.path.stroke()
        }
    }
    override func mouseDown(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        dragStart = point
        if let selected = shapes.first(where: { $0.path.contains(point) }) {
            status.stringValue = "clicked:" + selected.color + ":" + selected.shape
        }
    }
    override func mouseDragged(with event: NSEvent) {
        guard let start = dragStart else { return }
        let point = convert(event.locationInWindow, from: nil)
        status.stringValue = "drag moved:\(Int(point.x - start.x)),\(Int(point.y - start.y))"
    }
    override func mouseUp(with event: NSEvent) {
        defer { dragStart = nil }
        guard let start = dragStart else { return }
        let point = convert(event.locationInWindow, from: nil)
        if point != start {
            status.stringValue = "drag complete:\(Int(point.x - start.x)),\(Int(point.y - start.y))"
        }
    }
}
let application = FixtureApplication.shared
application.setActivationPolicy(.regular)
let mainMenu = NSMenu()
let editItem = NSMenuItem()
let editMenu = NSMenu(title: "Edit")
editMenu.addItem(NSMenuItem(title: "Select All", action: #selector(NSText.selectAll(_:)),
    keyEquivalent: "a"))
editItem.submenu = editMenu; mainMenu.addItem(editItem); application.mainMenu = mainMenu
let background = CommandLine.arguments.contains("--background")
let seed = UInt64(ProcessInfo.processInfo.environment["CUA_FIXTURE_SEED"] ?? "") ?? UInt64.random(in: 1...UInt64.max)
let screenIndex = Int(ProcessInfo.processInfo.environment["CUA_FIXTURE_SCREEN_INDEX"] ?? "0") ?? 0
let screenOrigin = NSScreen.screens.indices.contains(screenIndex) ? NSScreen.screens[screenIndex].frame.origin : .zero
var fixtureWindows: [NSWindow] = []
var layouts: [[String: Any]] = []
for index in 1...2 {
    let window = NSWindow(contentRect: NSRect(x: screenOrigin.x + CGFloat(160 + index * 40),
        y: screenOrigin.y + CGFloat(160 + index * 40), width: 560, height: 400),
        styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
    let title = ProcessInfo.processInfo.environment["CUA_FIXTURE_TITLE"] ?? "Computer Use Fixture"
    window.title = "\(title) \(index)"
    let text = NSTextField(string: "Fixture \(index) text")
    text.isEditable = true; text.isSelectable = true; text.isBezeled = true; text.drawsBackground = true
    text.identifier = NSUserInterfaceItemIdentifier("fixture-text-\(index)")
    text.frame = NSRect(x: 30, y: 300, width: 460, height: 28)
    if ProcessInfo.processInfo.environment["CUA_FIXTURE_CONTENT"] == "webkit" {
        let configuration = WKWebViewConfiguration()
        configuration.userContentController.add(FixtureWebEvents(index: index), name: "fixture")
        configuration.userContentController.addUserScript(WKUserScript(source: """
            let dragStart = null;
            let dragMoved = false;
            for (const name of ['mousedown', 'mouseup', 'mousemove', 'click', 'contextmenu']) {
                document.addEventListener(name, event => {
                    // Keep the pointer/drag target free of native menu tracking.
                    // The rest of the page retains its real default context menu.
                    if (name === 'contextmenu' && event.target.id === 'drag') event.preventDefault();
                    window.webkit.messageHandlers.fixture.postMessage({
                        event: name, detail: event.detail, button: event.button,
                        buttons: event.buttons, x: event.clientX, y: event.clientY,
                        trusted: event.isTrusted
                    });
                    if (name === 'mousedown' && event.target.id === 'drag') {
                        dragStart = [event.clientX, event.clientY]; dragMoved = false;
                    }
                    if (name === 'mousemove' && dragStart && (event.buttons & 1)) dragMoved = true;
                    if (name === 'mouseup' && dragStart) {
                        if (dragMoved) document.querySelector('#drag-status').textContent =
                            `drag complete:${event.clientX - dragStart[0]},${event.clientY - dragStart[1]}`;
                        dragStart = null;
                    }
                }, true);
            }
            """, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        let web = WKWebView(frame: NSRect(x: 30, y: 140, width: 460, height: 200),
            configuration: configuration)
        web.loadHTMLString("""
            <!doctype html><meta charset="utf-8">
            <style>body{margin:0}input{box-sizing:border-box;width:450px;height:30px;font:16px sans-serif}
            #drag{margin-top:20px;height:120px;background:#eef4ff;user-select:none}
            #drag-status{margin:0}</style>
            <input aria-label="Fixture web input" value="Fixture \(index) text">
            <div id="drag">Drag target</div><p id="drag-status">drag idle</p>
            """, baseURL: nil)
        window.contentView?.addSubview(web)
    } else {
        window.contentView?.addSubview(text)
    }
    let held = NSTextField(labelWithString: "Shift held: false")
    held.frame = NSRect(x: 30, y: 340, width: 460, height: 24)
    window.contentView?.addSubview(held)
    let mouseHeld = NSTextField(labelWithString: "Left button held: false")
    mouseHeld.frame = NSRect(x: 30, y: 365, width: 460, height: 24)
    window.contentView?.addSubview(mouseHeld)
    (application as! FixtureApplication).shiftLabels.append(held)
    (application as! FixtureApplication).mouseLabels.append(mouseHeld)
    let status = NSTextField(labelWithString: "No shape clicked")
    status.frame = NSRect(x: 30, y: 270, width: 460, height: 24)
    if ProcessInfo.processInfo.environment["CUA_FIXTURE_CONTENT"] != "webkit" {
        window.contentView?.addSubview(status)
    }
    let canvas = PaintedCanvas(frame: NSRect(x: 30, y: 140, width: 460, height: 120),
        seed: seed &+ UInt64(index), status: status)
    if ProcessInfo.processInfo.environment["CUA_FIXTURE_CONTENT"] != "webkit" {
        window.contentView?.addSubview(canvas)
    }
    let instruction = NSTextField(wrappingLabelWithString: "")
    instruction.frame = NSRect(x: 30, y: 245, width: 490, height: 50)
    instruction.font = NSFont.systemFont(ofSize: 17, weight: .semibold)
    instruction.textColor = .systemBlue; instruction.isHidden = true
    window.contentView?.addSubview(instruction)
    (application as! FixtureApplication).instructionLabels.append(instruction)
    layouts.append(["window": window.title, "seed": seed,
        "shapes": canvas.shapes.map { shape -> [String: Any] in
            ["color": shape.color, "shape": shape.shape,
             "x": canvas.frame.minX + shape.center.x,
             "y": window.frame.height - canvas.frame.minY - shape.center.y]
        }])
    let scroll = NSScrollView(frame: NSRect(x: 30, y: 20, width: 460, height: 110))
    scroll.hasVerticalScroller = true
    let editor = NSTextView(frame: NSRect(x: 0, y: 0, width: 440, height: 1400))
    editor.string = (1...60).map { "Fixture line \($0)" }.joined(separator: "\n")
    editor.identifier = NSUserInterfaceItemIdentifier("fixture-editor-\(index)")
    scroll.documentView = editor; window.contentView?.addSubview(scroll)
    if background { window.orderFront(nil) } else { window.makeKeyAndOrderFront(nil) }
    // Start keyboard focus in a different control so input tests must really
    // click the target text field; initial focus must not conceal a bad click.
    if background { window.initialFirstResponder = editor; window.makeFirstResponder(editor) }
    window.acceptsMouseMovedEvents = true
    fixtureWindows.append(window)
}
if let path = ProcessInfo.processInfo.environment["CUA_FIXTURE_LAYOUT_FILE"],
   let data = try? JSONSerialization.data(withJSONObject: layouts) { try? data.write(to: URL(fileURLWithPath: path)) }
if !background {
    DispatchQueue.main.async { application.activate(ignoringOtherApps: true) }
}
signal(SIGUSR2, SIG_IGN)
let moveRequest = DispatchSource.makeSignalSource(signal: SIGUSR2, queue: .main)
moveRequest.setEventHandler {
    for window in fixtureWindows {
        window.setFrameOrigin(NSPoint(x: window.frame.minX + 650, y: window.frame.minY + 25))
        if ProcessInfo.processInfo.environment["CUA_FIXTURE_EXPOSE_MOVED_WINDOW"] == "1" {
            window.orderFront(nil)
        }
    }
    if let path = ProcessInfo.processInfo.environment["CUA_FIXTURE_MOVE_ACK"] {
        try? Data("moved\n".utf8).write(to: URL(fileURLWithPath: path))
    }
}
moveRequest.resume()
let compositionTimer = Timer.scheduledTimer(withTimeInterval: 0.02, repeats: true) { _ in
    MainActor.assumeIsolated {
        (application as! FixtureApplication).observeComposition()
        (application as! FixtureApplication).observeInstructions()
    }
}
RunLoop.main.add(compositionTimer, forMode: .common)
application.run()
