"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";
import { setCookie } from "../../../config/cookies";
import { AUTH_COOKIE_KEY } from "../../../config/config";
import { routes } from "../../../services/routes";
import { useStore } from "../../../hooks/useStore";
import { useLoginApi, useGoogleAuthApi } from "../api";
import { LoginFormValues } from "../types";

export function useLogin() {
  const router = useRouter();
  const [request] = useLoginApi();
  const [googleRequest] = useGoogleAuthApi();
  const setUserId = useStore((s) => s.setUserId);

  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleAuthSuccess = (res: any) => {
    const responseData = res?.data;
    const user = responseData?.user;
    console.log("user data:", user);
    const userId = user?.id;

    if (userId) {
      setUserId(userId);
      localStorage.setItem("userId", userId);
    }

    if (user) {
      const displayName =
        `${user.first_name || ""} ${user.last_name || ""}`.trim() ||
        user.name ||
        user.email?.split("@")[0] ||
        "there";

      toast.success(`Welcome, ${displayName}!`);

      localStorage.setItem("userName", `${user.first_name} ${user.last_name}`.trim() || user.email);
      localStorage.setItem("isAdmin", String(user.is_admin ?? false));
      localStorage.setItem("app_theme_preference", "light");
      router.push(routes.dashboard);
    }

    if (res?.data?.roleInfo?.permissions) {
      localStorage.setItem(
        "permission",
        JSON.stringify(res.data.roleInfo.permissions)
      );
    }

    const token = responseData?.tokens?.access_token ?? "";
    setCookie(AUTH_COOKIE_KEY, token);
  };

  async function login(values: LoginFormValues) {
    setError(null);
    setIsSubmitting(true);

    try {
      await request(
        { data: { email: values.email.trim(), password: values.password } },
        handleAuthSuccess
      );
    } catch (err: unknown) {
      let msg = "Login failed";
      if (typeof err === "object" && err && "data" in err) {
        const d = (err as { data?: unknown }).data;
        if (d && typeof d === "object" && "message" in d) {
          const m = (d as { message?: unknown }).message;
          if (typeof m === "string") msg = m;
        }
      }
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function loginWithGoogle(credential: string) {
    setError(null);
    setIsSubmitting(true);

    try {
      await googleRequest(
        { data: { credential } },
        handleAuthSuccess
      );
    } catch (err: unknown) {
      let msg = "Google authentication failed";
      if (typeof err === "object" && err && "data" in err) {
        const d = (err as { data?: unknown }).data;
        if (d && typeof d === "object" && "message" in d) {
          const m = (d as { message?: unknown }).message;
          if (typeof m === "string") msg = m;
        }
      }
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  }

  return { login, loginWithGoogle, error, isSubmitting };
}