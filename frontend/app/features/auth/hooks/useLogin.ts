"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { setCookie } from "../../../config/cookies";
import { AUTH_COOKIE_KEY } from "../../../config/config";
import { routes } from "../../../services/routes";
import { useStore } from "../../../hooks/useStore";
import { useLoginApi } from "../api";
import { LoginFormValues } from "../types";

export function useLogin() {
  const router = useRouter();
  const [request] = useLoginApi();
  const setUserId = useStore((s) => s.setUserId);

  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function login(values: LoginFormValues) {
    setError(null);
    setIsSubmitting(true);

    try {
      await request(
        { data: { email: values.email.trim(), password: values.password } },
        (res: any) => {
          const responseData = res?.data;
          const user = responseData?.user;
          console.log("user data:", user);
          const userId = user?.id;

          if (userId) {
            setUserId(userId);
            localStorage.setItem("userId", userId);
          }

          if (user) {
            localStorage.setItem("userName", `${user.first_name} ${user.last_name}`);
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
        }
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

  return { login, error, isSubmitting };
}