export type Agent = {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  tenant_id: string;
  user_id: string;
  created_at: string;
  updated_at: string;
};

export type AgentListResponse = {
  success: boolean;
  data: {
    agents: Agent[];
    count: number;
    total: number;
  };
  error: null | string;
};

export type AgentItem = {
  id: string;
  name: string;
  status: string;
};