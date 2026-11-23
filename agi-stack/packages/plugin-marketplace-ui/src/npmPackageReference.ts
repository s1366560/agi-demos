// Registry names only. Protocols, filesystem paths, aliases, dist-tags and version ranges
// are not accepted by the project package resolver.
const namePart = '[a-z0-9][a-z0-9._-]*';
const packageName = new RegExp('^(?:@' + namePart + '/)?' + namePart + '$', 'u');
const number = '(?:0|[1-9][0-9]*)';
const prereleasePart = '(?:' + number + '|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*)';
const version = new RegExp(
  '^' +
    number +
    '\\.' +
    number +
    '\\.' +
    number +
    '(?:-' +
    prereleasePart +
    '(?:\\.' +
    prereleasePart +
    ')*)?(?:\\+[0-9a-zA-Z-]+(?:\\.[0-9a-zA-Z-]+)*)?$',
  'u'
);

export function isNpmPackageReference(name: unknown, exactVersion: unknown): boolean {
  return (
    typeof name === 'string' &&
    name.length <= 214 &&
    name.trim() === name &&
    packageName.test(name) &&
    typeof exactVersion === 'string' &&
    exactVersion.length <= 128 &&
    exactVersion.trim() === exactVersion &&
    version.test(exactVersion)
  );
}
