import axios from "axios";
import type {
  AxiosRequestConfig,
  AxiosResponse,
  Method,
} from "axios";

import { useRef, useState , useCallback} from "react";
// import { App as AntApp } from "antd";
// import Cookies from "js-cookie";
import { getCookie } from "../config/cookies";
import { toast } from "react-hot-toast";
import {useRouter} from "next/navigation"
import { endpoints, type endpointsType, type endpointType } from "../services/endpoints";
// import { endpoints } from "./endpoints";
// import type { endpointType, endpointsType } from "./endpoints";

const DEFAULT_SUCCESS_STATUS_CODES = [200, 201];

/* -------------------------------------------------------------------------- */
/*                                AXIOS SETUP                                 */
/* -------------------------------------------------------------------------- */

axios.defaults.baseURL = process.env.NEXT_PUBLIC_API_BASE_URL;

/* -------------------------------------------------------------------------- */
/*                                   TYPES                                    */
/* -------------------------------------------------------------------------- */

export interface AxiosConfig<R> extends AxiosRequestConfig {
  path?: string;
  data?: R;
  isFormData?: boolean;
}

interface UseAxiosProps<T, R> {
  endpoint?: endpointsType;

  showSuccessMsg?: boolean;
  hideErrorMsg?: boolean;

  successMsg?: string;

  initialData?: T;
  initialLoading?: boolean;

  successStatusCode?: number[];

  payload?: R;

  successCb?: () => void;
  errorCb?: () => void;
}

/* -------------------------------------------------------------------------- */
/*                                CUSTOM HOOK                                 */
/* -------------------------------------------------------------------------- */

export default function useAxios<T = any, R = any>({
  endpoint,

  showSuccessMsg = false,
  hideErrorMsg = false,

  successMsg = "",

  initialData,
  initialLoading = false,

  successStatusCode = DEFAULT_SUCCESS_STATUS_CODES,

  payload,

  successCb,
  errorCb,
}: UseAxiosProps<T, R>) {
  // const { message } = AntApp.useApp();

  /* -------------------------------------------------------------------------- */
  /*                               ENDPOINT DATA                                */
  /* -------------------------------------------------------------------------- */

  const {
    url = "",
    method = "GET",
    baseURL,
    withCredentials,
  } = endpoint
    ? (endpoints[endpoint] as endpointType)
    : {};

  /* -------------------------------------------------------------------------- */
  /*                                   STATES                                   */
  /* -------------------------------------------------------------------------- */

  const [loading, setLoading] = useState(initialLoading);
  const router = useRouter();
  const [data, setData] = useState<T>(initialData as T);

  /* -------------------------------------------------------------------------- */
  /*                             ABORT CONTROLLER                               */
  /* -------------------------------------------------------------------------- */

  const controller = useRef<AbortController | null>(null);

  /* -------------------------------------------------------------------------- */
  /*                                MAIN REQUEST                                */
  /* -------------------------------------------------------------------------- */

  

  const request =useCallback( async (
    config?: AxiosConfig<R>,
    cb?: (resData: T) => void
  ) => {
    try {
      /* -------------------------------------------------------------------------- */
      /*                          CANCEL PREVIOUS REQUEST                            */
      /* -------------------------------------------------------------------------- */

      controller.current?.abort();

      controller.current = new AbortController();

      setLoading(true);


      const token = getCookie("AUTH_TOKEN");

      /* -------------------------------------------------------------------------- */
      /*                                  HEADERS                                   */
      /* -------------------------------------------------------------------------- */

      const headers = config?.isFormData
        ? {
            ...(config?.headers ?? {}),
            Authorization: token ? `Bearer ${token}` : "",
          }
        : {
            "Content-Type": "application/json",

            Authorization: token ? `Bearer ${token}` : "",

            ...(config?.headers ?? {}),
          };

      /* -------------------------------------------------------------------------- */
      /*                               AXIOS REQUEST                                */
      /* -------------------------------------------------------------------------- */

      const response: AxiosResponse<any> =
        await axios.request({
          method: method as Method,

          baseURL,

          withCredentials,

          url: url + (config?.path ?? ""),

          signal: controller.current.signal,

          timeout: 5 * 60000,

          headers,

          data: config?.data ?? payload,

          ...config,
        });

     
      /* -------------------------------------------------------------------------- */
      /*                              SUCCESS HANDLING                              */
      /* -------------------------------------------------------------------------- */

      const isSuccess =
        // response.status === successStatusCode 
       successStatusCode.includes(response.status) &&
        (response.data?.status ??
          response.data?.result?.status) !== false;

      if (isSuccess) {
        successCb?.();

        const responseData =
          response?.data || null;

        if (cb) {
          cb(responseData);
        } else {
          setData(responseData);
        }

        if (showSuccessMsg) {
          toast.success(
            response?.data?.message ??
              response?.data?.result?.message ?? response?.data?.meta?.message ??
              successMsg
          );
        }

        return responseData as T;
      }

      /* -------------------------------------------------------------------------- */
      /*                               FAILED RESPONSE                              */
      /* -------------------------------------------------------------------------- */

      if (!hideErrorMsg) {
        if(response.status === 201)
        {
          toast.success(
            response?.data?.message ??
              response?.data?.result?.message ?? response?.data?.meta?.message ??
              successMsg
          );
        }
        else{
          toast.error(
            response?.data?.message || response?.data?.detail || response?.data?.meta?.message ||
              "Something went wrong"
          );
        }
      }

      errorCb?.();

      return null;
    } catch (error: any) {
      /* -------------------------------------------------------------------------- */
      /*                              RESET DATA STATE                              */
      /* -------------------------------------------------------------------------- */

      setData(initialData as T);
      console.log("Full Error:", error);
  console.log("Status:", error?.response?.status);
  console.log("Data:", error?.response?.data);

      if (error.response?.status === 401) {
    toast.error(
      error?.response?.data?.detail ||
      error?.response?.data?.message || error?.response?.data?.error || error?.response?.data?.meta?.message ||
      "Invalid username or password"
    );
    router.push("/login");
    return null;
  }

  // toast.error(
  //   error?.response?.data?.detail ||
  //   error?.response?.data?.message ||
  //   error?.response?.data?.title ||
  //   error?.message ||
  //   "Something went wrong"
  // );


      if (error.code === "ERR_CANCELED") {
        return;
      }

      /* -------------------------------------------------------------------------- */
      /*                              NORMAL ERRORS                                 */
      /* -------------------------------------------------------------------------- */

      if (
        !["ERR_CANCELED", "ECONNABORTED"].includes(
          error.code
        ) &&
        !hideErrorMsg
      ) {
        toast.error(
          (typeof error?.response?.data ===
          "string"
            ? error?.response?.data
            : error?.response?.data?.message) ||
            error?.response?.data?.title ||
            error?.message ||
            "Something went wrong"
        );
      // router.push("/login");
      }

      errorCb?.();

      return null;
    } finally {
      /* -------------------------------------------------------------------------- */
      /*                              STOP LOADING                                  */
      /* -------------------------------------------------------------------------- */

      setLoading(false);
    }
    }, [baseURL, hideErrorMsg, initialData, method, payload, router, showSuccessMsg, successCb, errorCb, successMsg, successStatusCode, url, withCredentials]);

  /* -------------------------------------------------------------------------- */
  /*                                   RETURN                                   */
  /* -------------------------------------------------------------------------- */

  return [
    request,
    data,
    loading,
    setData,
    setLoading,
  ] as const;
}