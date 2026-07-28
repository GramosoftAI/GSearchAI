"use client";

import { useCallback, useEffect } from "react";
import { useStore } from "./useStore";
import useAxios from "./useAxios";
import { AgentItem } from "../components/ui/type";

export function useAgents() {
  const { userId, agentList, setAgentList } = useStore();
  const [request, , isLoading, , setLoading] = useAxios<AgentItem[]>({
    endpoint: "GET_AGENTS_BY_USER",
    hideErrorMsg: true,
    initialLoading: agentList.length === 0,
  });

  const fetchAgents = useCallback(async (forcedUserId?: string) => {
    const id = forcedUserId || userId || localStorage.getItem("userId");
    if (!id) {
      setLoading(false);
      return;
    }

    try {
      await request({ path: `?user_id=${id}` }, (res) => {
        const data = (res as any)?.data?.agents || (res as any)?.agents;
        if (Array.isArray(data)) {
          setAgentList(data);
        } else if (Array.isArray(res)) {
          setAgentList(res);}
      });
    } catch (err) {
      console.error("Failed to fetch agents:", err);
    }
  }, [userId, request, setAgentList, setLoading]);

  // Initial fetch if list is empty
  useEffect(() => {
    if (agentList.length === 0) {
      fetchAgents();
    }
  }, [agentList.length, fetchAgents]);

  return { agents: agentList, fetchAgents, isLoading };
}
