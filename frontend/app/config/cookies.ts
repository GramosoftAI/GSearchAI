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
