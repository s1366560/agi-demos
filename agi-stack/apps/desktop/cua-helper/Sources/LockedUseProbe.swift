import Foundation

/// Availability observations never create, revoke, or replace a live binding.
struct LockedUseProbe {
    struct Availability {
        let state: String
        var reason: String? = nil
        var fields: [String: Any] {
            var value: [String: Any] = ["state": state]
            if let reason = reason { value["reason"] = reason }
            return value
        }
    }
    let installed: () -> Bool
    let supportedOS: () -> Bool
    let accessibility: () -> Bool
    let inputMonitoring: () -> Bool
    let configuration: () -> Availability
    let runtimeStatus: () -> [String: Any]

    func read() -> [String: Any] {
        let installed = installed(), supportedOS = supportedOS()
        let accessibility = accessibility(), inputMonitoring = inputMonitoring()
        let availability: Availability
        if !supportedOS {
            availability = Availability(state: "unsupported", reason: "macos_14_4_required")
        } else if !accessibility || !inputMonitoring {
            availability = Availability(state: "permission_required",
                reason: "accessibility_and_input_monitoring_required")
        } else {
            availability = configuration()
        }
        // Configuration checks can take time. Read the coordinator's locked
        // runtime snapshot last so a concurrent revocation is not hidden.
        let runtime = runtimeStatus()
        var result: [String: Any] = ["installed": installed, "supported_os": supportedOS,
            "accessibility": accessibility, "input_monitoring": inputMonitoring,
            "availability": availability.fields]
        result.merge(runtime) { _, value in value }
        // Preserve setup errors for an idle device, while keeping active and
        // attributed terminal states separate from current availability.
        if runtime["enabled"] as? Bool == false, runtime["state"] as? String == "available",
           runtime["revoked_binding"] == nil {
            result.merge(availability.fields) { _, value in value }
        }
        return result
    }

    static func permissionRecord(_ probe: [String: Any]) -> [String: Any] {
        let availability = probe["availability"] as? [String: Any] ?? [:]
        let state = availability["state"] as? String
        var result: [String: Any] = ["state": state == "available" ? "granted"
            : state == "unsupported" ? "unavailable" : "denied"]
        if let reason = availability["reason"] as? String { result["detail"] = reason }
        return result
    }
}
