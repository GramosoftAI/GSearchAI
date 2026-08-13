"use client";

import { useTheme } from "../provider/ThemeProvider";

export default function BrandGlyph({ height = 34, isWhite }: { height?: number; isWhite?: boolean }) {
  let isDarkTheme = false;
  try {
    const theme = useTheme();
    isDarkTheme = theme.isDark;
  } catch {
    isDarkTheme = typeof document !== "undefined" && (document.documentElement.classList.contains("dark") || document.documentElement.getAttribute("data-theme") === "dark");
  }

  const useWhiteLogo = isWhite ?? isDarkTheme;

  return (
    <img
      src={useWhiteLogo ? "/GSearchAI Logos White.svg" : "/Group 1597883327.svg"}
      alt="GsearchAI Logo"
      style={{ height, width: "auto", objectFit: "contain" }}
    />
  );
}
