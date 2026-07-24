import { useState } from "react";
import { getCookie } from "@/app/config/cookies";
import { toast } from "react-hot-toast";
import { User, UpdateUserPayload } from "./types";
import { inc, dec } from "../../config/loader";

// Base URL without /api/v1 prefix
const getBaseUrl = () => {
  const envUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "";
  return envUrl.replace(/\/api\/v1\/?$/, "").replace(/\/+$/, "");
};

export function useGetUsersApi() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<User[] | null>(null);

  const request = async (config?: { params?: { skip: number; limit: number } }) => {
    setLoading(true);
    inc();
    const token = getCookie("AUTH_TOKEN");
    const skip = config?.params?.skip ?? 0;
    const limit = config?.params?.limit ?? 10;
    try {
      const res = await fetch(`${getBaseUrl()}/users/?skip=${skip}&limit=${limit}`, {
        method: "GET",
        headers: {
          accept: "application/json",
          Authorization: `Bearer ${token}`,
        },
      });
      if (!res.ok) throw new Error(`Request failed with status ${res.status}`);
      const resData = await res.json();
      setData(resData);
      return resData;
    } catch (err: any) {
      console.error(err);
      toast.error(err?.message || "Failed to fetch users");
      return null;
    } finally {
      setLoading(false);
      dec();
    }
  };

  return [request, data, loading] as const;
}

export function useUpdateUserApi() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<User | null>(null);

  const request = async (config: { path: string; data: UpdateUserPayload }) => {
    setLoading(true);
    inc();
    const token = getCookie("AUTH_TOKEN");
    const userId = config.path.replace(/^\//, "");
    try {
      const res = await fetch(`${getBaseUrl()}/users/${userId}`, {
        method: "PUT",
        headers: {
          accept: "application/json",
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(config.data),
      });
      if (!res.ok) throw new Error(`Request failed with status ${res.status}`);
      const resData = await res.json();
      setData(resData);
      toast.success("User updated successfully");
      return resData;
    } catch (err: any) {
      console.error(err);
      toast.error(err?.message || "Failed to update user");
      return null;
    } finally {
      setLoading(false);
      dec();
    }
  };

  return [request, data, loading] as const;
}

export function useDeleteUserApi() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any>(null);

  const request = async (config: { path: string }) => {
    setLoading(true);
    inc();
    const token = getCookie("AUTH_TOKEN");
    const userId = config.path.replace(/^\//, "");
    try {
      const res = await fetch(`${getBaseUrl()}/users/${userId}`, {
        method: "DELETE",
        headers: {
          accept: "*/*",
          Authorization: `Bearer ${token}`,
        },
      });
      if (!res.ok) throw new Error(`Request failed with status ${res.status}`);
      toast.success("User deleted successfully");
      return true;
    } catch (err: any) {
      console.error(err);
      toast.error(err?.message || "Failed to delete user");
      return null;
    } finally {
      setLoading(false);
      dec();
    }
  };

  return [request, data, loading] as const;
}
