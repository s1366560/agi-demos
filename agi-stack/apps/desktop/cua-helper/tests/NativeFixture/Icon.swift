// Code-drawn fixture identity: a white monitor/play glyph on a blue rounded square.
// No application, windows, event loop, captured content or external image assets are used.
import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

func raster(_ size: Int) throws -> CGImage {
    guard let context = CGContext(data: nil, width: size, height: size, bitsPerComponent: 8,
        bytesPerRow: size * 4, space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { throw CocoaError(.coderInvalidValue) }
    context.scaleBy(x: CGFloat(size) / 512, y: CGFloat(size) / 512)
    context.setFillColor(CGColor(red: 0.09, green: 0.30, blue: 0.90, alpha: 1))
    context.addPath(CGPath(roundedRect: CGRect(x: 24, y: 24, width: 464, height: 464),
        cornerWidth: 96, cornerHeight: 96, transform: nil)); context.fillPath()
    context.setStrokeColor(CGColor(gray: 1, alpha: 1)); context.setLineWidth(22)
    context.addPath(CGPath(roundedRect: CGRect(x: 108, y: 164, width: 296, height: 210),
        cornerWidth: 22, cornerHeight: 22, transform: nil)); context.strokePath()
    context.setFillColor(CGColor(gray: 1, alpha: 1))
    context.move(to: CGPoint(x: 228, y: 216)); context.addLine(to: CGPoint(x: 228, y: 324))
    context.addLine(to: CGPoint(x: 316, y: 270)); context.closePath(); context.fillPath()
    context.fill(CGRect(x: 245, y: 116, width: 22, height: 38))
    context.fill(CGRect(x: 194, y: 102, width: 124, height: 22))
    guard let image = context.makeImage() else { throw CocoaError(.coderInvalidValue) }; return image
}
func verify(_ bundle: String) throws {
    let icon = NSWorkspace.shared.icon(forFile: bundle)
    guard let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 64, pixelsHigh: 64,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0),
        let context = NSGraphicsContext(bitmapImageRep: bitmap) else { throw CocoaError(.coderInvalidValue) }
    NSGraphicsContext.saveGraphicsState(); NSGraphicsContext.current = context
    icon.draw(in: NSRect(x: 0, y: 0, width: 64, height: 64), from: .zero, operation: .copy, fraction: 1)
    context.flushGraphics(); NSGraphicsContext.restoreGraphicsState()
    var blue = 0; var white = 0
    for y in 0..<64 { for x in 0..<64 {
        guard let color = bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB), color.alphaComponent > 0.9 else { continue }
        if color.blueComponent > 0.7 && color.redComponent < 0.2 && color.greenComponent < 0.4 { blue += 1 }
        if min(color.redComponent, color.greenComponent, color.blueComponent) > 0.9 { white += 1 }
    } }
    // The code-drawn background covers over one quarter of the icon, and the glyph over 1/64.
    guard blue > 64 * 64 / 4, white > 64 * 64 / 64 else { throw CocoaError(.coderInvalidValue,
        userInfo: [NSLocalizedDescriptionKey: "native fixture icon differs from its code-drawn palette: blue=\(blue), white=\(white)"] ) }
    print("native_bundle_icon_verified")
}
do {
if CommandLine.arguments.count == 3 && CommandLine.arguments[1] == "--verify-bundle" {
    try verify(CommandLine.arguments[2])
} else {
    guard CommandLine.arguments.count == 2 else { throw CocoaError(.coderInvalidValue) }
    let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
    for points in [16, 32, 128, 256, 512] { for scale in [1, 2] {
        let suffix = scale == 1 ? "" : "@2x"
        let url = directory.appendingPathComponent("icon_\(points)x\(points)\(suffix).png")
        guard let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil) else { throw CocoaError(.coderInvalidValue) }
        CGImageDestinationAddImage(destination, try raster(points * scale), nil)
        guard CGImageDestinationFinalize(destination) else { throw CocoaError(.fileWriteUnknown) }
    } }
}

} catch {
    FileHandle.standardError.write(Data("fixture_icon_error: \(error.localizedDescription)\n".utf8))
    exit(1)
}
