const RETURN_KEY = "monitoring_login_return";

export function safeReturnPath(value: string | null): string {
  if (
    !value ||
    /[\\\r\n]/.test(value) ||
    !value.startsWith("/") ||
    value.startsWith("//")
  )
    return "/";
  const parsed = new URL(value, window.location.origin);
  if (
    parsed.origin !== window.location.origin ||
    !/^\/(charts|projects)(\/|$)/.test(parsed.pathname)
  )
    return "/";
  return parsed.pathname + parsed.search;
}
export function rememberLoginDestination() {
  const path = safeReturnPath(
    window.location.pathname + window.location.search,
  );
  if (path !== "/") sessionStorage.setItem(RETURN_KEY, path);
}
export function peekLoginDestination() {
  return safeReturnPath(sessionStorage.getItem(RETURN_KEY));
}
export function takeLoginDestination() {
  const path = peekLoginDestination();
  sessionStorage.removeItem(RETURN_KEY);
  return path;
}
