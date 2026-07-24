// providers/providers.tsx
"use client";

import { type ReactNode } from "react";
import { GithubStarsProvider } from "./GithubStarsProvider";

export default function Providers({ children }: { children: ReactNode }) {
  return <GithubStarsProvider>{children}</GithubStarsProvider>;
}