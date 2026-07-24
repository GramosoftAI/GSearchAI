import useAxios from "@/app/hooks/useAxios";
import { LoginPayload, LoginResponse, RegisterPayload, RegisterResponse } from "./types";
import { MutableRefObject } from "react";

// ─── Login ────────────────────────────────────────────────────────────────────

export function useLoginApi() {
  return useAxios<LoginResponse, LoginPayload>({
    endpoint: "LOGIN",
    // hideErrorMsg: false,
    showSuccessMsg: true,
  });

}


// ─── Register ─────────────────────────────────────────────────────────────────

export function useRegisterApi(onValidationError?: React.Dispatch<React.SetStateAction<string[]>>,inputRefs?: MutableRefObject<HTMLInputElement[]>) {
  return useAxios<RegisterResponse, RegisterPayload>({
    endpoint: "REGISTER",
    showSuccessMsg: true,
    errorCb :(()=>{
        if (onValidationError) {
        onValidationError(new Array(6).fill(""));
      }
      if (inputRefs && inputRefs.current && inputRefs.current[0]) {
        setTimeout(() => {
          inputRefs.current[0]?.focus();
        }, 50)}
    })
  });
}