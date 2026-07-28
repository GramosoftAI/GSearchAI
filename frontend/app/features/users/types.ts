export interface User {
  id: string;
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  role: string;
  created_at: string;
  updated_at: string;
}

export interface UpdateUserPayload {
  email: string;
  username: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  role: string;
}
