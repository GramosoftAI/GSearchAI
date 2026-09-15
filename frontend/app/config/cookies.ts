export function setCookie(name: string, value: string, maxAgeSeconds = 7200, path = "/") {
  const encoded = encodeURIComponent(value);
  document.cookie = [`${name}=${encoded}`, `path=${path}`, `max-age=${maxAgeSeconds}`, `samesite=lax`].join("; ");
}

export function getCookie(name: string) {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp("(^|; )" + name + "=([^;]*)"));
  return match ? decodeURIComponent(match[2]) : null;
}

export function deleteCookie(name: string, path = "/") {
  document.cookie = [`${name}=`, `path=${path}`, `max-age=0`, `samesite=lax`].join("; ");
}

export function isTokenExpired(token: string | null): boolean {
  if (!token) return true;
  try {
    const parts = token.split(".");
    if (parts.length !== 3) return false;
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
        .join("")
    );
    const payload = JSON.parse(jsonPayload);
    if (payload && typeof payload.exp === "number") {
      const currentTime = Math.floor(Date.now() / 1000);
      return payload.exp <= currentTime;
    }
  } catch (e) {
    // If parsing fails, fall back to checking if cookie exists
  }
  return false;
}
