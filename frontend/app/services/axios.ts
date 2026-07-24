// import axios, { AxiosError, AxiosResponse, InternalAxiosRequestConfig, AxiosHeaders } from "axios";
// import { API_BASE_URL, AUTH_COOKIE_KEY } from "../config/config";
// import { getCookie } from "../config/cookies";
// import { inc, dec } from "../config/loader";

// type LoaderConfig = InternalAxiosRequestConfig & {
//   showLoader?: boolean;
//   __useLoader?: boolean;
// };

// export const http = axios.create({
//   baseURL: API_BASE_URL || undefined,
//   timeout: 60000,
//   withCredentials: false,
// });

// http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
//   const showLoader = (config as LoaderConfig).showLoader !== false;
//   if (showLoader) (config as LoaderConfig).__useLoader = true;
//   if ((config as LoaderConfig).__useLoader) inc();
//   const token = getCookie(AUTH_COOKIE_KEY);
//   const headers = AxiosHeaders.from(config.headers);
//   if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
//   if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
//   config.headers = headers;
//   return config;
// });

// http.interceptors.response.use(
//   (res: AxiosResponse) => {
//     const cfg = res.config as LoaderConfig;
//     if (cfg?.__useLoader) dec();
//     return res;
//   },
//   (err: AxiosError) => {
//     const cfg = (err.config as LoaderConfig) || undefined;
//     if (cfg?.__useLoader) dec();
//     return Promise.reject(err);
//   },
// );
