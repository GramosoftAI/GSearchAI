"use client";

import { useEffect, useState } from "react";
import { Modal, Button, Spin, Tag, App, Checkbox } from "antd";
import { CheckOutlined, DisconnectOutlined, SyncOutlined, PlusOutlined, LinkOutlined } from "@ant-design/icons";
import { getCookie } from "../../config/cookies";
import useAxios from "../../hooks/useAxios";

interface Agent {
  id: string;
  name: string;
  is_active: boolean;
  tenant_id: string;
  user_id: string;
  created_at: string;
  updated_at: string;
}

interface Props {
  open: boolean;
  type: "google" | "sharepoint" | "email" | "outlook";
  onClose: () => void;
  onConnect: (agent: { id: string; name: string }, kbId: string) => void;
  onAdd: (agent: { id: string; name: string }, kbId: string) => void;
}

export default function IntegrationConnectModal({
  open,
  type,
  onClose,
  onConnect,
  onAdd,
}: Props) {
  const { modal, notification } = App.useApp();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [connectionStates, setConnectionStates] = useState<Record<string, string[]>>({});
  const [kbIds, setKbIds] = useState<Record<string, string>>({});

  // Endpoint to get agent list
  const [getAgents] = useAxios<any>({ endpoint: "GETAGENTLIST", hideErrorMsg: true });
  // Disconnect endpoint
  const [disconnectKb] = useAxios<any>({ endpoint: "DISCONNECT", hideErrorMsg: true });

  const providerLabel = 
    type === "google" ? "Google Drive" : 
    type === "sharepoint" ? "SharePoint" : 
    type === "email" ? "Email" : "Outlook";
  const providerKey = 
    type === "google" ? "google_drive" : 
    type === "sharepoint" ? "sharepoint" : 
    type === "email" ? "email" : "outlook";

  // Helper to fetch details for a single agent to check connection
  // Helper to fetch/create KB ID for a single agent
  const fetchAgentKbId = async (agentId: string, agentName: string) => {
    try {
      const token = getCookie("AUTH_TOKEN");
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL}/knowledge-bases`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            agent_id: agentId,
            name: agentName,
          }),
        }
      );
      if (!res.ok) throw new Error("Failed to fetch/create knowledge base");
      const data = await res.json();
      return data?.data?.kb?.id || null;
    } catch (err) {
      console.error(`Error fetching KB for agent ${agentId}:`, err);
      return null;
    }
  };

  const checkAgentConnection = async (agentId: string) => {
    try {
      const token = getCookie("AUTH_TOKEN");
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL}/agents/${agentId}`,
        {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        }
      );
      if (!res.ok) throw new Error("Failed to check agent integrations");
      const data = await res.json();
      return data?.data?.agent?.connected_integrations || [];
    } catch (err) {
      console.error(`Error checking connection for agent ${agentId}:`, err);
      // Fallback to local storage simulated state
      const localConnections = localStorage.getItem(`mock_connections_${agentId}`);
      if (localConnections) {
        return JSON.parse(localConnections);
      }
      return [];
    }
  };

  // Load all agents and their connection states
  const loadAgentsAndConnections = async () => {
    setLoading(true);
    try {
      // 1. Fetch agents
      let agentsList: Agent[] = [];
      await getAgents(undefined, (payload) => {
        agentsList = payload?.data?.agents ?? [];
        setAgents(agentsList);
      });

      if (agentsList.length === 0) {
        setLoading(false);
        return;
      }

      // 2. Fetch connection states and KB IDs in parallel
      const statesMap: Record<string, string[]> = {};
      const kbMap: Record<string, string> = {};

      await Promise.all(
        agentsList.map(async (agent) => {
          // Check integration status
          const integrations = await checkAgentConnection(agent.id);
          statesMap[agent.id] = integrations;

          // Check/Fetch KB ID
          const kbId = await fetchAgentKbId(agent.id, agent.name);
          if (kbId) {
            kbMap[agent.id] = kbId;
          }
        })
      );

      setConnectionStates(statesMap);
      setKbIds(kbMap);
    } catch (err) {
      console.error("Failed to load integrations data", err);
      notification.error({
        message: "Failed to load agents",
        description: "An error occurred while loading agents details.",
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      setSelectedAgentId(null);
      loadAgentsAndConnections();
    }
  }, [open, type]);

  // Handle Disconnect logic with confirmation dialog
  const handleDisconnectClick = (e: React.MouseEvent, agentId: string, agentName: string) => {
    e.stopPropagation();

    modal.confirm({
      title: `Disconnect ${providerLabel}?`,
      content: `Are you sure you want to disconnect ${providerLabel} from agent "${agentName}"?`,
      okText: "Disconnect",
      cancelText: "Cancel",
      okButtonProps: {
        danger: true,
      },
      onOk: async () => {
        try {
          // const kbId = kbIds[agentId];
          if (!agentId) {
            throw new Error("Agent is  not found .");
          }

          // Call disconnect API
          await disconnectKb({
            path: `${agentId}/integration/${providerKey}`,
          });

          // Update local simulated/cached state as a fallback
          const integrations = connectionStates[agentId] || [];
          const updated = integrations.filter((item) => item !== providerKey);
          localStorage.setItem(`mock_connections_${agentId}`, JSON.stringify(updated));

          notification.success({
            message: "Disconnected",
            description: `${providerLabel} has been disconnected from "${agentName}".`,
          });

          // Reload/refresh agent list in the modal instantly
          await loadAgentsAndConnections();
          if (selectedAgentId === agentId) {
            setSelectedAgentId(null);
          }
        } catch (err) {
          console.error("Disconnect error:", err);
          notification.error({
            message: "Disconnect Failed",
            description: "An error occurred during disconnection.",
          });
        }
      },
    });
  };

  const selectedAgent = agents.find((a) => a.id === selectedAgentId);
  const isSelectedAgentSynced = selectedAgentId
    ? connectionStates[selectedAgentId]?.includes(providerKey)
    : false;

  const handleActionClick = () => {
    if (!selectedAgentId || !selectedAgent) return;
    const kbId = kbIds[selectedAgentId];
    if (!kbId) {
      notification.error({
        message: "Knowledge Base Error",
        description: `Knowledge Base for agent "${selectedAgent.name}" could not be created or fetched.`,
      });
      return;
    }

    if (isSelectedAgentSynced) {
      onAdd({ id: selectedAgent.id, name: selectedAgent.name }, kbId);
    } else {
      onConnect({ id: selectedAgent.id, name: selectedAgent.name }, kbId);
    }
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={580}
      destroyOnClose
      title={null}
      closable
      className="custom-integration-modal"
    >
      <div className="p-6 md:p-8">
        {/* Header */}
        <div className="mb-6 flex items-center gap-3">
          <div className="p-2.5 bg-purple-500/10 rounded-xl">
            <LinkOutlined className="text-purple-600 text-xl" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-[var(--app-text)] m-0">
              Manage {providerLabel} Connection
            </h3>
            <p className="text-xs text-[var(--app-text-muted)] mt-1">
              Select an agent to connect or sync folder documents. Only one agent can be selected at a time.
            </p>
          </div>
        </div>

        {/* List content */}
        {loading ? (
          <div className="flex flex-col items-center justify-center py-16 gap-3">
            <Spin size="large" />
            <span className="text-sm text-[var(--app-text-soft)]">Loading agents...</span>
          </div>
        ) : agents.length === 0 ? (
          <div className="text-center py-12 text-[var(--app-text-muted)]">
            No agents found. Please create an agent first.
          </div>
        ) : (
          <div className="max-h-[320px] overflow-y-auto pr-1 flex flex-col gap-3 custom-scrollbar mb-8">
            {agents.map((agent) => {
              const integrations = connectionStates[agent.id] || [];
              const isSynced = integrations.includes(providerKey);
              const isSelected = selectedAgentId === agent.id;

              return (
                <div
                  key={agent.id}
                  onClick={() => setSelectedAgentId(isSelected ? null : agent.id)}
                  className={`flex items-center justify-between p-4 rounded-2xl border transition-all cursor-pointer select-none ${isSelected
                      ? "border-purple-500 bg-purple-500/5 shadow-sm"
                      : "border-[var(--app-border)] hover:border-purple-300 hover:bg-slate-50/50"
                    }`}
                >
                  <div className="flex items-center gap-3.5 flex-1 min-w-0">
                    {/* Custom Checkbox */}
                    <div
                      className={`w-5 h-5 rounded-md flex items-center justify-center border transition-all ${isSelected
                          ? "bg-purple-500 border-purple-500 text-white"
                          : "border-slate-300 bg-white"
                        }`}
                    >
                      {isSelected && <CheckOutlined className="text-[10px] stroke-[3]" />}
                    </div>

                    <div className="min-w-0">
                      <p className="font-semibold text-sm text-[var(--app-text)] truncate m-0">
                        {agent.name}
                      </p>
                      <p className="text-xs text-[var(--app-text-muted)] m-0 mt-0.5 truncate">
                        ID: {agent.id}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 flex-shrink-0">
                    {isSynced ? (
                      <div className="flex items-center gap-2">
                        <Tag color="success" className="px-2.5 py-0.5 rounded-full border-none font-medium text-xs">
                          Synced
                        </Tag>
                        <Button
                          type="text"
                          danger
                          size="small"
                          icon={<DisconnectOutlined />}
                          onClick={(e) => handleDisconnectClick(e, agent.id, agent.name)}
                          className="hover:bg-red-50 rounded-lg text-xs flex items-center justify-center font-medium"
                        >
                          Disconnect
                        </Button>
                      </div>
                    ) : (
                      <Tag color="default" className="px-2.5 py-0.5 rounded-full border-none font-medium text-xs">
                        Not Synced
                      </Tag>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Footer Actions */}
        <div className="flex justify-end gap-3 pt-4 border-t border-[var(--app-border)]">
          <Button
            size="large"
            onClick={onClose}
            className="rounded-xl px-6 font-semibold border-[var(--app-border)] text-[var(--app-text)] hover:bg-slate-50"
          >
            Cancel
          </Button>
          <Button
            type="primary"
            size="large"
            disabled={!selectedAgentId || loading}
            onClick={handleActionClick}
            icon={isSelectedAgentSynced ? <PlusOutlined /> : <SyncOutlined />}
            className={`rounded-xl px-8 font-semibold ${selectedAgentId
                ? "bg-purple-500 border-purple-500 hover:bg-purple-600"
                : "bg-slate-200 border-slate-200 text-slate-400"
              }`}
          >
            {isSelectedAgentSynced ? "Add" : "Connect"}
          </Button>
        </div>
      </div>

      <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 5px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: #cbd5e1;
          border-radius: 99px;
        }
        .custom-integration-modal .ant-modal-content {
          padding: 0 !important;
          border-radius: 24px !important;
          overflow: hidden;
        }
      `}</style>
    </Modal>
  );
}
