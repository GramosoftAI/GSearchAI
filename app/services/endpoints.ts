// import { useStore } from "../hooks/useStore";


// const getUserId = () => useStore.getState().userId;
export enum methods {
  get = "get",
  post = "post",
  put = "put",
  delete = "delete",
  patch = "patch",
}

export type endpointType = {
  url: string;
  method: methods;
  baseURL?: string;
  withCredentials?: boolean;
};

export const endpoints = {
  LOGIN: {
    url: "/auth/login",
    method: methods.post,
  },
  REGISTER: {
    url: "/auth/register",
    method: methods.post,
  },
  FORGOT_PASSWORD: {
    url: "/auth/forgot-password",
    method: methods.post,
    // withCredentials: true,
  },
  RESET_PASSWORD: {
    url: "/auth/reset-password",
    method: methods.post,
    // withCredentials: true,
  },
  GETAGENTLIST: {
    url: `/agents`,
    method: methods.get,
  },
  CREATEAGENT: {
    url: "/agents",
    method: methods.post
  },
  UPDATEAGENT: {
    url: "/agents",
    method: methods.patch
  },
  DELETEAGENT: {
    url: "/agents",
    method: methods.delete
  },
  KNOWLEDGEBASE: {
    url: "/agents",
    method: methods.post
  },

  GRAPHVIEW: {
    url: "/graphs/agent",
    method: methods.get
  },
  ANALYTICS_DASHBOARD: {
    url: "/analytics/dashboard",
    method: methods.get,
  },
  FEEDBACK_REASONS: {
    url: "/analytics/feedback-reasons",
    method: methods.get,
  },
  FEEDBACK_MESSAGES: {
    url: "/analytics/feedback-messages",
    method: methods.get,
  },
  GET_AGENTS_BY_USER: {
    url: "/agents/by-user",
    method: methods.get,
  },
  GET_LIST: {
    url: "/knowledge-bases",
    method: methods.get
  },
  GET_LISTS: {
    url: "/knowledge-bases",
    method: methods.post
  },
  GET_USER_KBS: {
    url: "/knowledge-bases/users",
    method: methods.get
  },
  DISCONNECT: {
    url: "/knowledge-bases/agent/",
    method: methods.delete
  },
  GET_AGENT_BY_ID: {
    url: "/personalities",
    method: methods.get
  },
  GET_USERS: {
    url: "/users",
    method: methods.get,
  },
  UPDATE_USER: {
    url: "/users",
    method: methods.put,
  },
  DELETE_USER: {
    url: "/users",
    method: methods.delete,
  },
  USER_COSTS: {
    url: "/analytics/token-usage",
    method: methods.get,
  },
  URL_DISCOVER: {
    url: "/agents",
    method: methods.post,
  },
  URL_SELECT: {
    url: "/agents",
    method: methods.post,
  },
  GET_WIDGET_CONFIG: {
    url: "/embed/configs",
    method: methods.get,
  },
  SAVE_WIDGET_CONFIG: {
    url: "/embed/configs",
    method: methods.post,
  }
} as const;

export type endpointsType = keyof typeof endpoints;
