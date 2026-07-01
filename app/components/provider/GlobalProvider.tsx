// components/provider/GlobalProvider.tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { App, ConfigProvider, theme as antdTheme } from "antd";
import { useState, type ReactNode } from "react";
import Providers from "./providers";
import { SessionProvider } from "next-auth/react"
import { GlobalLoader } from "./GlobalLoader";
import ThemeProvider, { useTheme } from "./ThemeProvider";

function ThemedConfigProvider({ children }: { children: ReactNode }) {
  const { isDark } = useTheme();

  return (
    <ConfigProvider
      theme={{
        algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: "#0fb5a1",
          colorTextBase: isDark ? "#ffffff" : "#14161f",
          colorTextSecondary: isDark ? "#cbd5e1" : "#414856",
          colorBgBase: isDark ? "#0d0f17" : "#ffffff",
          colorBgContainer: isDark ? "#14161f" : "#ffffff",
          colorBorder: isDark ? "#2e3347" : "#e5e9ef",
          fontFamily: "var(--font-plus-jakarta-sans), -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        },
      }}
    >
      <App>
        <GlobalLoader />
        <SessionProvider>
        <Providers>{children}</Providers>
        </SessionProvider>
      </App>
    </ConfigProvider>
  );
}

export default function GlobalProvider({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ThemedConfigProvider>{children}</ThemedConfigProvider>
      </ThemeProvider>
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
