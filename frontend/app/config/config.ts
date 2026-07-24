export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/+$/, "") || "";

export const AUTH_COOKIE_KEY =
  process.env.NEXT_PUBLIC_AUTH_COOKIE_KEY || process.env.AUTH_COOKIE_KEY || "AUTH_TOKEN";
