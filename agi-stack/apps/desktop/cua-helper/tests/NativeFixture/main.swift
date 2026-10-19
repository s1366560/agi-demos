import AppKit

final class FixtureApplication: NSApplication {
    var receivedShiftHeld = false
    var receivedLeftHeld = false
    var shiftLabels: [NSTextField] = []
    var mouseLabels: [NSTextField] = []
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
        super.sendEvent(event)
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
        if let selected = shapes.first(where: { $0.path.contains(point) }) {
            status.stringValue = "clicked:" + selected.color + ":" + selected.shape
        }
    }
}
let application = FixtureApplication.shared
application.setActivationPolicy(.regular)
let background = CommandLine.arguments.contains("--background")
let seed = UInt64(ProcessInfo.processInfo.environment["CUA_FIXTURE_SEED"] ?? "") ?? UInt64.random(in: 1...UInt64.max)
var fixtureWindows: [NSWindow] = []
var layouts: [[String: Any]] = []
for index in 1...2 {
    let window = NSWindow(contentRect: NSRect(x: 160 + index * 40, y: 160 + index * 40, width: 560, height: 400),
        styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
    window.title = "Computer Use Fixture \(index)"
    let text = NSTextField(string: "Fixture \(index) text")
    text.isEditable = true; text.isSelectable = true; text.isBezeled = true; text.drawsBackground = true
    text.identifier = NSUserInterfaceItemIdentifier("fixture-text-\(index)")
    text.frame = NSRect(x: 30, y: 300, width: 460, height: 28)
    window.contentView?.addSubview(text)
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
    window.contentView?.addSubview(status)
    let canvas = PaintedCanvas(frame: NSRect(x: 30, y: 140, width: 460, height: 120),
        seed: seed &+ UInt64(index), status: status)
    window.contentView?.addSubview(canvas)
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
    fixtureWindows.append(window)
}
if let path = ProcessInfo.processInfo.environment["CUA_FIXTURE_LAYOUT_FILE"],
   let data = try? JSONSerialization.data(withJSONObject: layouts) { try? data.write(to: URL(fileURLWithPath: path)) }
if !background { application.activate(ignoringOtherApps: false) }
application.run()
