// The outer router owns identity, installation selection and authentication parameters.
const hostParameters = new Set([
  "tenant",
  "tenantId",
  "tenant_id",
  "project",
  "projectId",
  "project_id",
  "packageScope",
  "businessPackage",
  "optionalPlugin",
  "marketPlugin",
  "marketPage",
  "workbench",
  "token",
  "access_token",
  "refresh_token",
  "code",
  "state",
]);

/** Split before matching: URL would normalize dot segments before the route authorization check. */
export function splitPageLocation(path: string) {
  const fragment = path.indexOf("#");
  const hash = fragment < 0 ? "" : path.slice(fragment);
  const address = fragment < 0 ? path : path.slice(0, fragment);
  const query = address.indexOf("?");
  return {
    pathname: query < 0 ? address : address.slice(0, query),
    search: query < 0 ? "" : address.slice(query),
    hash,
  };
}

export function pageSearch(
  search: string,
  refuseHostParameters = false,
  declared?: readonly string[],
) {
  const result = new URLSearchParams();
  for (const [key, value] of new URLSearchParams(search)) {
    if (hostParameters.has(key)) {
      if (refuseHostParameters) throw new Error("page_navigation_denied");
    } else if (!declared || declared.includes(key)) result.append(key, value);
  }
  const encoded = result.toString();
  return encoded ? "?" + encoded : "";
}

export function scopedPageLocation(
  path: string,
  bindings: Record<string, string>,
) {
  const { pathname, search, hash } = splitPageLocation(path);
  const query = new URLSearchParams(pageSearch(search));
  for (const [key, value] of Object.entries(bindings)) query.set(key, value);
  return { pathname, search: query.toString(), hash };
}
