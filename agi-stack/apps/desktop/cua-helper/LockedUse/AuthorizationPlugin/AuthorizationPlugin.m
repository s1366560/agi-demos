#import <Foundation/Foundation.h>
#import <Security/AuthorizationPlugin.h>
#import <Security/Security.h>
#include <bsm/libbsm.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include <pwd.h>

#define CONFIG_PATH "/Library/Application Support/MemStack/ComputerUse/locked-use.plist"
typedef struct { const AuthorizationCallbacks *callbacks; } Plugin;
typedef struct { Plugin *plugin; AuthorizationEngineRef engine; } Mechanism;

static BOOL trustedConfiguration(NSDictionary **output) {
    struct stat attributes;
    if (lstat(CONFIG_PATH, &attributes) != 0 || !S_ISREG(attributes.st_mode)
        || attributes.st_uid != 0 || (attributes.st_mode & 0022) != 0) return NO;
    NSDictionary *configuration = [NSDictionary dictionaryWithContentsOfFile:@CONFIG_PATH];
    if (![configuration[@"socket_path"] isKindOfClass:[NSString class]]
        || ![configuration[@"service_requirement"] isKindOfClass:[NSString class]]
        || ![configuration[@"owner_uid"] isKindOfClass:[NSNumber class]]) return NO;
    *output = configuration;
    return YES;
}

static BOOL peerMatches(int fd, NSDictionary *configuration) {
    audit_token_t token = {0}; socklen_t length = sizeof(token);
    if (getsockopt(fd, SOL_LOCAL, LOCAL_PEERTOKEN, &token, &length) != 0
        || length != sizeof(token)
        || audit_token_to_euid(token) != [configuration[@"owner_uid"] unsignedIntValue]) return NO;
    NSData *audit = [NSData dataWithBytes:&token length:sizeof(token)];
    NSDictionary *attributes = @{(__bridge NSString *)kSecGuestAttributeAudit: audit};
    SecCodeRef code = NULL; SecRequirementRef requirement = NULL;
    OSStatus status = SecCodeCopyGuestWithAttributes(NULL, (__bridge CFDictionaryRef)attributes,
                                                    kSecCSDefaultFlags, &code);
    if (status == errSecSuccess)
        status = SecRequirementCreateWithString((__bridge CFStringRef)configuration[@"service_requirement"],
                                                kSecCSDefaultFlags, &requirement);
    if (status == errSecSuccess) status = SecCodeCheckValidity(code, kSecCSDefaultFlags, requirement);
    if (code) CFRelease(code);
    if (requirement) CFRelease(requirement);
    return status == errSecSuccess;
}

static OSStatus destroyPlugin(AuthorizationPluginRef ref) { free((void *)ref); return errAuthorizationSuccess; }
static OSStatus createMechanism(AuthorizationPluginRef ref, AuthorizationEngineRef engine,
                               AuthorizationMechanismId identifier, AuthorizationMechanismRef *output) {
    if (!ref || !engine || !output || strcmp(identifier, "allow") != 0) return errAuthorizationInternal;
    Mechanism *value = calloc(1, sizeof(Mechanism));
    if (!value) return errAuthorizationInternal;
    value->plugin = (Plugin *)ref; value->engine = engine; *output = value;
    return errAuthorizationSuccess;
}
static OSStatus invokeMechanism(AuthorizationMechanismRef ref) {
    Mechanism *mechanism = (Mechanism *)ref;
    if (!mechanism) return errAuthorizationInternal;
    AuthorizationResult decision = kAuthorizationResultDeny;
    @autoreleasepool {
        NSDictionary *configuration;
        if (trustedConfiguration(&configuration)) {
            AuthorizationContextFlags flags;
            const AuthorizationValue *username = NULL;
            OSStatus status = mechanism->plugin->callbacks->GetContextValue(mechanism->engine,
                kAuthorizationEnvironmentUsername, &flags, &username);
            if (status == errAuthorizationSuccess && username && username->data && username->length > 0
                && username->length < 256) {
                char name[256] = {0}; memcpy(name, username->data, username->length);
                struct passwd *user = getpwnam(name);
                if (user && user->pw_uid == [configuration[@"owner_uid"] unsignedIntValue]) {
                    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
                    if (fd >= 0) {
                        struct sockaddr_un address = {0}; address.sun_family = AF_UNIX;
                        const char *path = [configuration[@"socket_path"] fileSystemRepresentation];
                        if (strlen(path) < sizeof(address.sun_path)) {
                            strlcpy(address.sun_path, path, sizeof(address.sun_path));
                            struct timeval timeout = {.tv_sec = 2};
                            setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
                            setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
                            if (connect(fd, (struct sockaddr *)&address, sizeof(address)) == 0
                                && peerMatches(fd, configuration)) {
                                char response[5] = {0};
                                ssize_t count = read(fd, response, sizeof(response));
                                if (count == sizeof(response) && memcmp(response, "ALLOW", 5) == 0)
                                    decision = kAuthorizationResultAllow;
                            }
                        }
                        close(fd);
                    }
                }
            }
        }
    }
    return mechanism->plugin->callbacks->SetResult(mechanism->engine, decision);
}
static OSStatus deactivateMechanism(AuthorizationMechanismRef ref) {
    Mechanism *value = (Mechanism *)ref;
    return value->plugin->callbacks->DidDeactivate(value->engine);
}
static OSStatus destroyMechanism(AuthorizationMechanismRef ref) { free((void *)ref); return errAuthorizationSuccess; }
static AuthorizationPluginInterface interface = {
    kAuthorizationPluginInterfaceVersion, destroyPlugin, createMechanism, invokeMechanism,
    deactivateMechanism, destroyMechanism
};
OSStatus AuthorizationPluginCreate(const AuthorizationCallbacks *callbacks, AuthorizationPluginRef *plugin,
                                    const AuthorizationPluginInterface **output) {
    if (!callbacks || !plugin || !output) return errAuthorizationInternal;
    Plugin *value = calloc(1, sizeof(Plugin));
    if (!value) return errAuthorizationInternal;
    value->callbacks = callbacks; *plugin = value; *output = &interface;
    return errAuthorizationSuccess;
}
