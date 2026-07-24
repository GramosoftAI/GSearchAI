// ─── Request Payloads ────────────────────────────────────────────────────────

export interface LoginPayload {
  email: string;
  password: string;
}

export interface RegisterPayload {
  first_name: string;
  last_name: string;
  email: string;
  password: string;
  confirm_password: string;
  tenant_name: string;
  otp:string
}

// ─── Response Shapes ─────────────────────────────────────────────────────────

export interface AuthUser {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token?: string;
}

export interface RoleInfo {
  permissions: string[];
}

export interface LoginResponse {
  user: AuthUser;
  tokens: AuthTokens;
  roleInfo?: RoleInfo;
}

export interface RegisterResponse {
  user: AuthUser;
  tokens: AuthTokens;
}

// ─── Form Field Values ────────────────────────────────────────────────────────

export interface LoginFormValues {
  email: string;
  password: string;
}

export interface RegisterFormValues {
  first_name: string;
  last_name: string;
  email: string;
  password: string;
  confirm_password: string;
  tenant_name: string;
  otp:string
}