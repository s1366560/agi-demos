import Darwin
import Foundation

enum InstallError: Error { case failure(String) }

func protectedPath(_ path: URL) throws {
    var current = URL(fileURLWithPath: "/", isDirectory: true)
    for component in path.pathComponents.dropFirst() {
        current.appendPathComponent(component)
        var info = stat()
        if lstat(current.path, &info) == 0 {
            guard (info.st_mode & S_IFMT) == S_IFDIR, info.st_uid == 0,
                  (info.st_mode & 0o022) == 0 else {
                throw InstallError.failure("installation directory is not protected")
            }
        } else if errno != ENOENT {
            throw InstallError.failure("cannot inspect installation directory")
        }
    }
}
