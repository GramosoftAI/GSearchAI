"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  Card,
  Button,
  Typography,
  Select,
  Tag,
  Spin,
  App,
  Tooltip,
  Empty,
  Input,
  Drawer,
} from "antd";
import {
  RobotOutlined,
  ReloadOutlined,
  CheckCircleOutlined,
  DisconnectOutlined,
  SyncOutlined,
  PlusOutlined,
  SearchOutlined,
  NumberOutlined,
  CheckOutlined,
  CloseCircleOutlined,
  DeleteOutlined,
  LeftOutlined,
  RightOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import { FaSlack } from "react-icons/fa6";
import { getCookie } from "../../config/cookies";
import { AUTH_COOKIE_KEY, API_BASE_URL } from "../../config/config";

const { Title, Text, Paragraph } = Typography;

export type SlackBoxInstance = {
  id: string;
  name: string;
  agentId: string;
  teamName?: string;
  connected: boolean;
  channelId?: string;
  channelName?: string;
  linkedChannels: { id: string; name: string }[];
  createdAt: number;
};

export type SlackChannel = {
  id: string;
  name: string;
};

export type Agent = {
  id: string;
  name: string;
  description?: string;
  personality?: string;
  is_active?: boolean;
  total_conversations?: number;
  [key: string]: any;
};

const getAuthHeaders = (): Record<string, string> => {
  const token = getCookie(AUTH_COOKIE_KEY) || getCookie("AUTH_TOKEN");
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
};

const SLACK_BOXES_STORAGE_KEY = "slack_workspace_cards_v7";

function SlackIntegrationContent() {
  const { message, modal } = App.useApp();

  const [agents, setAgents] = useState<Agent[]>([]);
  const [loadingAgents, setLoadingAgents] = useState<boolean>(true);

  // Multiple Slack Workspace Boxes
  const [slackBoxes, setSlackBoxes] = useState<SlackBoxInstance[]>([]);

  // Store Slack channel options per agent
  const [channels, setChannels] = useState<Record<string, SlackChannel[]>>({});

  // Loading state per box action
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});

  // Search query to filter Slack Boxes
  const [boxSearchText, setBoxSearchText] = useState<string>("");

  // Slide Drawer state for adding channels to a specific box
  const [drawerTargetBox, setDrawerTargetBox] = useState<SlackBoxInstance | null>(null);
  const [channelSearchText, setChannelSearchText] = useState<string>("");

  // Slider container ref and scroll state
  const sliderRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  // Check scroll capability
  const updateScrollButtons = useCallback(() => {
    if (sliderRef.current) {
      const { scrollLeft, scrollWidth, clientWidth } = sliderRef.current;
      setCanScrollLeft(scrollLeft > 10);
      setCanScrollRight(scrollLeft + clientWidth < scrollWidth - 10);
    }
  }, []);

  // Slide controls
  const handleSlideLeft = () => {
    if (sliderRef.current) {
      sliderRef.current.scrollBy({ left: -370, behavior: "smooth" });
    }
  };

  const handleSlideRight = () => {
    if (sliderRef.current) {
      sliderRef.current.scrollBy({ left: 370, behavior: "smooth" });
    }
  };

  // Helper to persist boxes
  const saveBoxesToStorage = (boxes: SlackBoxInstance[]) => {
    try {
      localStorage.setItem(SLACK_BOXES_STORAGE_KEY, JSON.stringify(boxes));
    } catch (err) {
      console.warn("Storage save error:", err);
    }
  };

  // Fetch channels for a connected agent/box
  const fetchSlackChannels = useCallback(
    async (agentId: string, boxId?: string, silent = false) => {
      if (!agentId) return;
      try {
        if (!silent && boxId) {
          setActionLoading((prev) => ({ ...prev, [boxId]: true }));
        }

        const res = await fetch(`${API_BASE_URL}/slack/channels?agent_id=${agentId}`, {
          method: "GET",
          headers: getAuthHeaders(),
        });

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}: Failed to fetch Slack channels`);
        }

        const data = await res.json();

        let channelList: SlackChannel[] = [];
        let teamName = "";
        let selectedChannelId = "";
        let selectedChannelName = "";

        if (Array.isArray(data)) {
          channelList = data;
        } else if (data?.data && Array.isArray(data.data)) {
          channelList = data.data;
        } else if (data?.channels && Array.isArray(data.channels)) {
          channelList = data.channels;
          teamName = data.team_name || data.teamName || "";
          selectedChannelId = data.channel_id || data.channelId || data.selected_channel_id || "";
          selectedChannelName = data.channel_name || data.channelName || "";
        } else if (data?.data?.channels && Array.isArray(data.data.channels)) {
          channelList = data.data.channels;
          teamName = data.data.team_name || data.data.teamName || "";
          selectedChannelId = data.data.channel_id || data.data.channelId || "";
          selectedChannelName = data.data.channel_name || data.data.channelName || "";
        }

        setChannels((prev) => ({ ...prev, [agentId]: channelList }));

        setSlackBoxes((prev) => {
          const updated = prev.map((box) => {
            if ((boxId && box.id === boxId) || (!boxId && box.agentId === agentId)) {
              const currentLinked = box.linkedChannels || [];
              const newLinked =
                selectedChannelId && selectedChannelName && !currentLinked.some((c) => c.id === selectedChannelId)
                  ? [...currentLinked, { id: selectedChannelId, name: selectedChannelName }]
                  : currentLinked;

              return {
                ...box,
                connected: true,
                teamName: teamName || box.teamName || "Workspace",
                channelId: selectedChannelId || box.channelId,
                channelName: selectedChannelName || box.channelName,
                linkedChannels: newLinked,
              };
            }
            return box;
          });
          saveBoxesToStorage(updated);
          return updated;
        });
      } catch (err: any) {
        console.error(`Error fetching channels for agent ${agentId}:`, err);
      } finally {
        if (boxId) {
          setActionLoading((prev) => ({ ...prev, [boxId]: false }));
        }
      }
    },
    []
  );

  // Fetch agents list & load/initialize boxes
  const fetchAgents = useCallback(async () => {
    setLoadingAgents(true);
    try {
      let res = await fetch(`${API_BASE_URL}/agents`, {
        method: "GET",
        headers: getAuthHeaders(),
      });

      if (!res.ok) {
        const userId = typeof window !== "undefined" ? localStorage.getItem("userId") : null;
        if (userId) {
          res = await fetch(`${API_BASE_URL}/agents/by-user?user_id=${userId}`, {
            method: "GET",
            headers: getAuthHeaders(),
          });
        }
      }

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: Failed to fetch agents list`);
      }

      const responseData = await res.json();
      const agentList: Agent[] =
        responseData?.data?.agents ||
        responseData?.agents ||
        (Array.isArray(responseData?.data) ? responseData.data : null) ||
        (Array.isArray(responseData) ? responseData : []);

      setAgents(agentList);

      // Load boxes from storage
      let storedBoxes: SlackBoxInstance[] = [];
      try {
        const raw = localStorage.getItem(SLACK_BOXES_STORAGE_KEY);
        if (raw) {
          storedBoxes = JSON.parse(raw);
        }
      } catch (e) {
        console.warn("Error reading stored boxes", e);
      }

      // If no box exists yet and we have agents, initialize default box 1
      if (storedBoxes.length === 0 && agentList.length > 0) {
        const firstAgent = agentList[0];
        const isConnected = !!(firstAgent.slack_connected || firstAgent.slack_team_name);
        const initBox: SlackBoxInstance = {
          id: `box_${Date.now()}_1`,
          name: "Slack Workspace 1",
          agentId: firstAgent.id,
          teamName: firstAgent.slack_team_name || firstAgent.slack_team || (isConnected ? "Workspace" : undefined),
          connected: isConnected,
          channelId: firstAgent.slack_channel_id,
          channelName: firstAgent.slack_channel_name,
          linkedChannels:
            firstAgent.slack_channel_id && firstAgent.slack_channel_name
              ? [{ id: firstAgent.slack_channel_id, name: firstAgent.slack_channel_name }]
              : [],
          createdAt: Date.now(),
        };
        storedBoxes = [initBox];
        saveBoxesToStorage(storedBoxes);
      }

      setSlackBoxes(storedBoxes);

      // Fetch channels for connected agents
      storedBoxes.forEach((box) => {
        if (box.agentId) {
          fetchSlackChannels(box.agentId, box.id, true);
        }
      });
    } catch (err: any) {
      console.error("Error fetching agents:", err);
      message.error(err?.message || "Failed to load agents list. Please try again.");
    } finally {
      setLoadingAgents(false);
    }
  }, [fetchSlackChannels, message]);

  // Handle URL query parameters for Slack OAuth return
  useEffect(() => {
    if (typeof window === "undefined") return;

    const searchParams = new URLSearchParams(window.location.search);
    const slackParam = searchParams.get("slack");
    const agentIdParam = searchParams.get("agent_id") || searchParams.get("agentId");

    if (slackParam === "connected") {
      message.success("Slack workspace connected successfully!");
      const cleanUrl = window.location.pathname;
      window.history.replaceState({}, document.title, cleanUrl);

      if (agentIdParam) {
        fetchSlackChannels(agentIdParam);
      }
      fetchAgents();
    } else if (slackParam === "error") {
      message.error("Failed to connect Slack workspace. Please try again.");
      const cleanUrl = window.location.pathname;
      window.history.replaceState({}, document.title, cleanUrl);
    } else {
      fetchAgents();
    }
  }, [fetchAgents, fetchSlackChannels, message]);

  // Update scroll buttons on box change & window resize
  useEffect(() => {
    const timer = setTimeout(updateScrollButtons, 200);
    const handleResize = () => updateScrollButtons();
    window.addEventListener("resize", handleResize);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("resize", handleResize);
    };
  }, [slackBoxes, updateScrollButtons]);

  // ADD NEW SLACK BOX (Plus Button)
  const handleAddNewSlackBox = () => {
    if (agents.length === 0) {
      message.warning("Please create an agent first.");
      return;
    }

    const newIndex = slackBoxes.length + 1;
    const defaultAgentId = agents[0].id;

    const newBox: SlackBoxInstance = {
      id: `box_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
      name: `Slack Workspace ${newIndex}`,
      agentId: defaultAgentId,
      teamName: undefined,
      connected: false,
      channelId: undefined,
      channelName: undefined,
      linkedChannels: [],
      createdAt: Date.now(),
    };

    const updated = [...slackBoxes, newBox];
    setSlackBoxes(updated);
    saveBoxesToStorage(updated);

    message.success(`New Slack Workspace card created!`);

    // Smoothly scroll slider to the new card
    setTimeout(() => {
      if (sliderRef.current) {
        sliderRef.current.scrollTo({
          left: sliderRef.current.scrollWidth,
          behavior: "smooth",
        });
      }
    }, 150);
  };

  // DELETE SLACK BOX
  const handleDeleteSlackBox = (boxId: string, boxName: string) => {
    if (slackBoxes.length <= 1) {
      message.info("At least one Slack connection box is required.");
      return;
    }

    modal.confirm({
      title: `Delete ${boxName}?`,
      icon: <DeleteOutlined style={{ color: "#ff4d4f" }} />,
      content: `Are you sure you want to remove this Slack connection box? This will remove channel mappings for this workspace.`,
      okText: "Delete Box",
      okType: "danger",
      cancelText: "Cancel",
      maskClosable: true,
      centered: true,
      onOk: () => {
        const updated = slackBoxes.filter((b) => b.id !== boxId);
        setSlackBoxes(updated);
        saveBoxesToStorage(updated);
        message.success(`Slack box removed successfully`);
      },
    });
  };

  // CHANGE AGENT FOR A BOX
  const handleAgentChangeForBox = (boxId: string, newAgentId: string) => {
    const updated = slackBoxes.map((b) => {
      if (b.id === boxId) {
        return {
          ...b,
          agentId: newAgentId,
        };
      }
      return b;
    });
    setSlackBoxes(updated);
    saveBoxesToStorage(updated);

    fetchSlackChannels(newAgentId, boxId);
  };

  // CONNECT TO SLACK FOR A BOX
  const handleConnectSlack = async (boxId: string, agentId: string) => {
    setActionLoading((prev) => ({ ...prev, [boxId]: true }));
    try {
      const res = await fetch(`${API_BASE_URL}/slack/connect?agent_id=${agentId}`, {
        method: "GET",
        headers: getAuthHeaders(),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: Unable to initiate Slack authorization`);
      }

      const data = await res.json();
      const authUrl = data?.authorization_url || data?.data?.authorization_url || data?.url;

      if (authUrl) {
        message.loading("Redirecting to Slack authorization...", 1.5);
        window.location.href = authUrl;
      } else {
        throw new Error("Authorization URL not received from server");
      }
    } catch (err: any) {
      console.error("Connect to Slack error:", err);
      message.error(err?.message || "Failed to initiate Slack connection.");
      setActionLoading((prev) => ({ ...prev, [boxId]: false }));
    }
  };

  // LINK CHANNEL FOR A BOX
  const handleSelectChannel = async (boxId: string, agentId: string, channelId: string, channelName: string) => {
    setActionLoading((prev) => ({ ...prev, [boxId]: true }));

    try {
      const res = await fetch(`${API_BASE_URL}/slack/set-channel`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({
          agent_id: agentId,
          channel_id: channelId,
          channel_name: channelName,
        }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: Failed to link Slack channel`);
      }

      const updated = slackBoxes.map((box) => {
        if (box.id === boxId) {
          const currentLinked = box.linkedChannels || [];
          const newLinked = currentLinked.some((c) => c.id === channelId)
            ? currentLinked
            : [...currentLinked, { id: channelId, name: channelName }];

          return {
            ...box,
            connected: true,
            channelId,
            channelName,
            linkedChannels: newLinked,
          };
        }
        return box;
      });

      setSlackBoxes(updated);
      saveBoxesToStorage(updated);

      if (drawerTargetBox && drawerTargetBox.id === boxId) {
        setDrawerTargetBox((prev) => (prev ? { ...prev, channelId, channelName, linkedChannels: updated.find(b => b.id === boxId)?.linkedChannels || [] } : null));
      }

      message.success(`Channel #${channelName} linked successfully!`);
    } catch (err: any) {
      console.error("Set channel error:", err);
      message.error(err?.message || "Failed to link channel to agent.");
    } finally {
      setActionLoading((prev) => ({ ...prev, [boxId]: false }));
    }
  };

  // REMOVE LINKED CHANNEL FROM A BOX
  const handleRemoveLinkedChannel = (boxId: string, channelId: string) => {
    const updated = slackBoxes.map((box) => {
      if (box.id === boxId) {
        const newLinked = (box.linkedChannels || []).filter((c) => c.id !== channelId);
        const newChannelId = box.channelId === channelId ? newLinked[0]?.id : box.channelId;
        const newChannelName = box.channelId === channelId ? newLinked[0]?.name : box.channelName;
        return {
          ...box,
          channelId: newChannelId,
          channelName: newChannelName,
          linkedChannels: newLinked,
        };
      }
      return box;
    });

    setSlackBoxes(updated);
    saveBoxesToStorage(updated);

    if (drawerTargetBox && drawerTargetBox.id === boxId) {
      setDrawerTargetBox((prev) => (prev ? { ...prev, linkedChannels: updated.find(b => b.id === boxId)?.linkedChannels || [] } : null));
    }

    message.info("Channel removed from workspace mappings");
  };

  // DISCONNECT SLACK FOR A BOX
  const handleDisconnectSlack = (boxId: string, agentId: string, boxName: string) => {
    modal.confirm({
      title: `Disconnect Slack from ${boxName}?`,
      icon: <DisconnectOutlined style={{ color: "#ff4d4f" }} />,
      content: (
        <Text className="text-[var(--app-text-soft)]">
          Are you sure you want to disconnect this Slack workspace? The agent will no longer respond to events in this workspace.
        </Text>
      ),
      okText: "Disconnect",
      okType: "danger",
      cancelText: "Cancel",
      maskClosable: true,
      centered: true,
      onOk: async () => {
        setActionLoading((prev) => ({ ...prev, [boxId]: true }));
        try {
          await fetch(`${API_BASE_URL}/slack/disconnect?agent_id=${agentId}`, {
            method: "DELETE",
            headers: getAuthHeaders(),
          });

          const updated = slackBoxes.map((box) => {
            if (box.id === boxId) {
              return {
                ...box,
                connected: false,
                teamName: undefined,
                channelId: undefined,
                channelName: undefined,
                linkedChannels: [],
              };
            }
            return box;
          });

          setSlackBoxes(updated);
          saveBoxesToStorage(updated);
          message.success("Disconnected from Slack successfully");
        } catch (err: any) {
          console.error("Disconnect Slack error:", err);
          message.error("Failed to disconnect from Slack.");
        } finally {
          setActionLoading((prev) => ({ ...prev, [boxId]: false }));
        }
      },
    });
  };

  // Filter Slack Boxes by search bar text
  const filteredBoxes = useMemo(() => {
    if (!boxSearchText.trim()) return slackBoxes;
    const q = boxSearchText.toLowerCase().trim().replace(/^#/, "");
    return slackBoxes.filter((box) => {
      const ag = agents.find((a) => a.id === box.agentId);
      const agName = ag?.name?.toLowerCase() || "";
      const team = box.teamName?.toLowerCase() || "";
      const boxName = box.name.toLowerCase();
      const channelMatches = box.linkedChannels?.some((c) => c.name.toLowerCase().includes(q));
      return boxName.includes(q) || agName.includes(q) || team.includes(q) || channelMatches;
    });
  }, [slackBoxes, agents, boxSearchText]);

  // Channels for the Slide Drawer
  const drawerTargetAgent = useMemo(() => {
    if (!drawerTargetBox) return null;
    return agents.find((a) => a.id === drawerTargetBox.agentId) || null;
  }, [agents, drawerTargetBox]);

  const drawerChannels = useMemo(() => {
    if (!drawerTargetAgent) return [];
    return channels[drawerTargetAgent.id] || [];
  }, [channels, drawerTargetAgent]);

  const filteredDrawerChannels = useMemo(() => {
    if (!channelSearchText.trim()) return drawerChannels;
    const q = channelSearchText.toLowerCase().trim().replace(/^#/, "");
    return drawerChannels.filter((c) => c.name.toLowerCase().includes(q) || c.id.toLowerCase().includes(q));
  }, [drawerChannels, channelSearchText]);

  return (
    <div className="w-full flex flex-col gap-6 my-4">
      {/* HEADER CARD WITH SEARCH BAR & SLIDER CONTROLS */}
      <Card
        className="overflow-hidden bg-[var(--app-surface)] border border-[var(--app-border)] rounded-3xl shadow-sm"
        styles={{ body: { padding: "24px 28px" } }}
      >
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-5">
          {/* Branding & Title */}
          <div className="flex items-center gap-4 min-w-0">
            <div className="w-13 h-13 shrink-0 rounded-2xl bg-[#4A154B] text-white flex items-center justify-center text-3xl shadow-md">
              <FaSlack />
            </div>
            <div className="min-w-0 space-y-0.5">
              <div className="flex items-center gap-2.5 flex-wrap">
                <Title level={4} className="!m-0 !text-[var(--app-text)] !font-extrabold tracking-tight">
                  Slack Workspace Integrations
                </Title>
                <Tag color="purple" className="rounded-full px-2.5 py-0.5 text-xs font-semibold m-0">
                  {slackBoxes.length} {slackBoxes.length === 1 ? "Workspace" : "Workspaces"}
                </Tag>
              </div>
              <Text className="text-[var(--app-text-soft)] text-xs md:text-sm font-normal block">
                Connect your AI agents to Slack channels. Slide through to manage workspaces!
              </Text>
            </div>
          </div>

          {/* Right Toolbar: Search Bar & Navigation Arrows */}
          <div className="flex items-center gap-3 w-full md:w-auto justify-start md:justify-end flex-wrap">
            {/* Real-Time Search Bar for Slack Boxes */}
            <div className="w-full sm:w-64">
              <Input
                prefix={<SearchOutlined className="text-slate-400 mr-1" />}
                placeholder="Search workspaces, agents..."
                allowClear
                value={boxSearchText}
                onChange={(e) => setBoxSearchText(e.target.value)}
                className="rounded-xl h-10"
              />
            </div>

            {/* Slider Navigation Arrows */}
            <div className="flex items-center gap-1.5 bg-slate-100 dark:bg-slate-800/80 p-1 rounded-xl border border-[var(--app-border)]">
              <Tooltip title="Slide Left">
                <Button
                  type="text"
                  size="small"
                  icon={<LeftOutlined />}
                  onClick={handleSlideLeft}
                  disabled={!canScrollLeft}
                  className="h-8 w-8 flex items-center justify-center rounded-lg text-xs"
                />
              </Tooltip>
              <Tooltip title="Slide Right">
                <Button
                  type="text"
                  size="small"
                  icon={<RightOutlined />}
                  onClick={handleSlideRight}
                  disabled={!canScrollRight}
                  className="h-8 w-8 flex items-center justify-center rounded-lg text-xs"
                />
              </Tooltip>
            </div>

            {/* Header Add Button: ONLY visible on mobile screens (hidden on md/lg desktop) */}
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleAddNewSlackBox}
              className="h-10 px-4 rounded-xl !bg-[#0fb5a1] hover:!bg-[#0a8576] font-bold text-white shadow-sm flex md:hidden items-center gap-1.5 active:scale-95 transition-transform shrink-0"
            >
              Add
            </Button>

            <Tooltip title="Refresh all Agents and Slack connections">
              <Button
                icon={<ReloadOutlined />}
                onClick={() => fetchAgents()}
                loading={loadingAgents}
                className="h-10 px-3.5 rounded-xl border-[var(--app-border)] font-semibold text-[var(--app-text)] hover:!border-[#0fb5a1] hover:!text-[#0fb5a1] transition-all shrink-0"
              />
            </Tooltip>
          </div>
        </div>
      </Card>

      {/* SLIDER WITH WORKSPACE CARDS AND ADJACENT '+ ADD WORKSPACE' CARD */}
      {loadingAgents ? (
        <div className="py-24 text-center bg-[var(--app-surface)] border border-[var(--app-border)] rounded-3xl">
          <Spin size="large" />
          <Text className="block mt-4 text-[var(--app-text-soft)] font-medium">
            Loading AI agents & Slack connections...
          </Text>
        </div>
      ) : agents.length === 0 ? (
        <Card className="py-16 text-center bg-[var(--app-surface)] border border-[var(--app-border)] rounded-3xl">
          <Empty
            description={
              <Text className="text-[var(--app-text-soft)] font-medium">
                No AI agents found for your account. Please create an agent first.
              </Text>
            }
          />
        </Card>
      ) : (
        <div className="w-full relative group/slider">
          {/* Floating Slider Left/Right Buttons */}
          {canScrollLeft && (
            <button
              onClick={handleSlideLeft}
              className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-3 z-20 w-11 h-11 rounded-full bg-white dark:bg-slate-800 text-[var(--app-text)] shadow-lg border border-[var(--app-border)] hover:bg-[#0fb5a1] hover:text-white flex items-center justify-center transition-all cursor-pointer"
            >
              <LeftOutlined />
            </button>
          )}

          {canScrollRight && (
            <button
              onClick={handleSlideRight}
              className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-3 z-20 w-11 h-11 rounded-full bg-white dark:bg-slate-800 text-[var(--app-text)] shadow-lg border border-[var(--app-border)] hover:bg-[#0fb5a1] hover:text-white flex items-center justify-center transition-all cursor-pointer"
            >
              <RightOutlined />
            </button>
          )}

          {/* Sliding Container for workspace cards + Add Workspace card (NO scrollbar) */}
          <div
            ref={sliderRef}
            onScroll={updateScrollButtons}
            className="flex items-stretch gap-6 overflow-x-auto scroll-smooth snap-x snap-mandatory py-1 pb-2 px-1 no-scrollbar w-full"
          >
            {filteredBoxes.map((box) => {
              const currentAgent = agents.find((a) => a.id === box.agentId) || agents[0];
              const isBoxConnected = !!box.connected;
              const isBoxLoading = !!actionLoading[box.id];
              const linkedChannelsList = box.linkedChannels || [];

              return (
                <Card
                  key={box.id}
                  className="w-[320px] sm:w-[350px] lg:w-[360px] min-h-[440px] shrink-0 snap-start group relative overflow-hidden bg-[var(--app-surface)] border border-[var(--app-border)] rounded-3xl transition-all duration-300 hover:shadow-xl hover:border-[#0fb5a1]/40 flex flex-col justify-between"
                  styles={{
                    body: {
                      padding: "24px",
                      display: "flex",
                      flexDirection: "column",
                      height: "100%",
                      minHeight: "440px",
                      justifyContent: "space-between",
                      gap: "18px",
                    },
                  }}
                >
                  {/* Ambient Corner Accent */}
                  <div className="absolute top-0 right-0 w-24 h-24 bg-[#0fb5a1]/5 rounded-bl-[60px] pointer-events-none transition-transform duration-500 group-hover:scale-125" />

                  {/* Top: Header & Agent Selector */}
                  <div className="space-y-4">
                    {/* Card Title & Delete Option */}
                    <div className="flex items-center justify-between gap-2 pb-3 border-b border-[var(--app-border)]">
                      <div className="flex items-center gap-2 min-w-0">
                        <div className="w-7 h-7 rounded-lg bg-[#4A154B] text-white flex items-center justify-center text-sm font-bold shrink-0">
                          <FaSlack />
                        </div>
                        <span className="font-bold text-xs md:text-sm text-[var(--app-text)] truncate">
                          {box.name}
                        </span>
                      </div>

                      <div className="flex items-center gap-1.5 shrink-0">
                        {isBoxConnected ? (
                          <Tag
                            icon={<CheckCircleOutlined />}
                            color="success"
                            className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold m-0"
                          >
                            {box.teamName || "Connected"}
                          </Tag>
                        ) : (
                          <Tag color="default" className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold m-0">
                            Offline
                          </Tag>
                        )}

                        {slackBoxes.length > 1 && (
                          <Tooltip title="Delete this Slack box">
                            <Button
                              type="text"
                              danger
                              size="small"
                              icon={<DeleteOutlined />}
                              onClick={() => handleDeleteSlackBox(box.id, box.name)}
                              className="text-xs p-1 h-7 w-7 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/40"
                            />
                          </Tooltip>
                        )}
                      </div>
                    </div>

                    {/* SELECT AGENT FOR THIS WORKSPACE DROPDOWN */}
                    <div className="space-y-1.5">
                      <label className="text-[11px] font-bold text-[var(--app-text)] uppercase tracking-wider flex items-center gap-1.5">
                        <RobotOutlined className="text-[#0fb5a1]" /> Select Agent for this Workspace:
                      </label>

                      <Select
                        value={box.agentId}
                        onChange={(newAgId) => handleAgentChangeForBox(box.id, newAgId)}
                        size="large"
                        className="w-full rounded-xl"
                        showSearch
                        filterOption={(input, option) =>
                          (option?.label as string)?.toLowerCase().includes(input.toLowerCase())
                        }
                        options={agents.map((ag) => ({
                          value: ag.id,
                          label: `${ag.name} ${ag.personality ? `(${ag.personality})` : ""}`,
                          render: (
                            <div className="flex items-center justify-between py-0.5">
                              <div className="flex items-center gap-2">
                                <span className="font-semibold text-xs">{ag.name}</span>
                                {ag.personality && (
                                  <Tag color="cyan" className="text-[9px] rounded-md m-0 px-1">
                                    {ag.personality}
                                  </Tag>
                                )}
                              </div>
                            </div>
                          ),
                        }))}
                      />
                    </div>

                    {/* AGENT DETAIL MINI CARD */}
                    {currentAgent && (
                      <div className="p-3.5 rounded-2xl bg-slate-50/70 dark:bg-slate-900/30 border border-[var(--app-border)] flex items-start gap-3">
                        <div className="w-10 h-10 shrink-0 rounded-xl bg-[#0fb5a1]/15 text-[#0fb5a1] flex items-center justify-center text-xl font-bold">
                          <RobotOutlined />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-xs text-[var(--app-text)] truncate">
                              {currentAgent.name}
                            </span>
                            {currentAgent.personality && (
                              <span className="text-[9px] font-bold text-[#0fb5a1] uppercase tracking-wider">
                                {currentAgent.personality}
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-[var(--app-text-soft)] line-clamp-2 mt-1 m-0 leading-relaxed">
                            {currentAgent.description || "Autonomous AI agent ready to respond in Slack channels."}
                          </p>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Bottom: Channels & Connect Actions */}
                  <div className="pt-4 border-t border-[var(--app-border)] space-y-3.5">
                    {isBoxConnected ? (
                      <div className="space-y-3">
                        {/* Linked Channels Header & Plus Button */}
                        <div>
                          <div className="flex justify-between items-center mb-2">
                            <span className="text-xs font-bold text-[var(--app-text)]">
                              Linked Channels ({linkedChannelsList.length}):
                            </span>

                            {/* Plus (+) Button to Add Channel to this Box */}
                            <Button
                              size="small"
                              type="primary"
                              icon={<PlusOutlined />}
                              onClick={() => {
                                setDrawerTargetBox(box);
                                setChannelSearchText("");
                                if (currentAgent) {
                                  fetchSlackChannels(currentAgent.id, box.id);
                                }
                              }}
                              className="rounded-lg text-xs font-semibold !bg-[#0fb5a1] hover:!bg-[#0a8576] !border-none px-2.5 h-7 flex items-center gap-1"
                            >
                              Add Channel
                            </Button>
                          </div>

                          {/* Linked Channel Tags */}
                          <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto no-scrollbar p-1">
                            {linkedChannelsList.length === 0 ? (
                              <div
                                onClick={() => {
                                  setDrawerTargetBox(box);
                                  setChannelSearchText("");
                                  if (currentAgent) {
                                    fetchSlackChannels(currentAgent.id, box.id);
                                  }
                                }}
                                className="w-full py-3 text-center rounded-xl border border-dashed border-[var(--app-border)] text-[11px] text-[#0fb5a1] cursor-pointer hover:bg-[#0fb5a1]/5 transition-colors"
                              >
                                + Click to link a Slack channel
                              </div>
                            ) : (
                              linkedChannelsList.map((ch) => {
                                const isPrimary = ch.id === box.channelId;
                                return (
                                  <div
                                    key={ch.id}
                                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border text-xs font-semibold ${
                                      isPrimary
                                        ? "bg-[#0fb5a1]/10 border-[#0fb5a1]/40 text-[#0fb5a1]"
                                        : "bg-slate-100 dark:bg-slate-800 border-[var(--app-border)] text-[var(--app-text)]"
                                    }`}
                                  >
                                    <NumberOutlined className="text-[10px] text-slate-400" />
                                    <span className="truncate max-w-[110px]">{ch.name}</span>
                                    <button
                                      onClick={() => handleRemoveLinkedChannel(box.id, ch.id)}
                                      className="text-slate-400 hover:text-red-500 bg-transparent border-none cursor-pointer p-0 ml-1 flex items-center"
                                    >
                                      <CloseCircleOutlined className="text-[10px]" />
                                    </button>
                                  </div>
                                );
                              })
                            )}
                          </div>
                        </div>

                        {/* Bottom Quick Actions */}
                        <div className="flex justify-between items-center pt-2">
                          <Tooltip title="Refresh Slack channels list">
                            <Button
                              type="text"
                              size="small"
                              icon={<SyncOutlined spin={isBoxLoading} />}
                              onClick={() => currentAgent && fetchSlackChannels(currentAgent.id, box.id)}
                              disabled={isBoxLoading}
                              className="text-xs text-[var(--app-text-soft)] hover:text-[#0fb5a1] px-1"
                            >
                              Sync
                            </Button>
                          </Tooltip>

                          <Button
                            danger
                            type="default"
                            size="small"
                            icon={<DisconnectOutlined />}
                            loading={isBoxLoading}
                            onClick={() => currentAgent && handleDisconnectSlack(box.id, currentAgent.id, box.name)}
                            className="rounded-xl text-xs font-semibold border-red-200 dark:border-red-900/50"
                          >
                            Disconnect
                          </Button>
                        </div>
                      </div>
                    ) : (
                      /* Not Connected State */
                      <div className="space-y-3">
                        <div className="flex items-center gap-2 text-xs text-[var(--app-text-soft)]">
                          <InfoCircleOutlined className="text-[#0fb5a1] shrink-0" />
                          <span>Authorize this agent with your Slack workspace</span>
                        </div>

                        <Button
                          type="primary"
                          icon={<FaSlack className="text-base shrink-0" />}
                          loading={isBoxLoading}
                          onClick={() => currentAgent && handleConnectSlack(box.id, currentAgent.id)}
                          className="w-full h-11 rounded-xl !bg-[#0fb5a1] hover:!bg-[#0a8576] !border-none font-bold text-white shadow-sm transition-all active:scale-[0.98] flex items-center justify-center gap-2"
                        >
                          Connect {currentAgent?.name || "Agent"} to Slack
                        </Button>
                      </div>
                    )}
                  </div>
                </Card>
              );
            })}

            {/* ADJACENT '+ ADD WORKSPACE' CARD (Identical size & sits directly next to previous card) */}
            <Card
              onClick={handleAddNewSlackBox}
              className="w-[320px] sm:w-[350px] lg:w-[360px] min-h-[440px] shrink-0 snap-start border-2 border-dashed border-[var(--app-border)] hover:border-[#0fb5a1] bg-[var(--app-surface)]/60 hover:bg-[#0fb5a1]/5 rounded-3xl transition-all duration-300 hover:shadow-xl cursor-pointer select-none group flex flex-col justify-between"
              styles={{
                body: {
                  padding: "24px",
                  display: "flex",
                  flexDirection: "column",
                  height: "100%",
                  minHeight: "440px",
                  justifyContent: "center",
                  alignItems: "center",
                  textAlign: "center",
                  gap: "16px",
                },
              }}
            >
              <div className="w-16 h-16 rounded-2xl bg-[#0fb5a1]/10 text-[#0fb5a1] group-hover:scale-110 flex items-center justify-center text-3xl font-bold shadow-inner transition-transform">
                <PlusOutlined />
              </div>
              <div className="space-y-1">
                <h4 className="font-bold text-base text-[var(--app-text)] m-0">
                  + Add Workspace
                </h4>
                <p className="text-xs text-[var(--app-text-soft)] max-w-xs m-0 leading-relaxed">
                  Connect the same agent or another agent to a new workspace.
                </p>
              </div>
              <Button
                type="primary"
                className="mt-2 rounded-xl !bg-[#0fb5a1] hover:!bg-[#0a8576] font-semibold text-xs text-white pointer-events-none px-6 h-9"
              >
                + Create Box
              </Button>
            </Card>
          </div>
        </div>
      )}

      {/* SLIDE DRAWER FOR CHANNEL SELECTION & REAL-TIME SEARCH */}
      <Drawer
        open={!!drawerTargetBox}
        onClose={() => setDrawerTargetBox(null)}
        width={480}
        title={
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-[#4A154B] text-white flex items-center justify-center text-lg">
              <FaSlack />
            </div>
            <div>
              <div className="font-bold text-sm text-[var(--app-text)]">
                Add Channel to {drawerTargetAgent?.name || "Agent"}
              </div>
              <div className="text-[11px] text-[var(--app-text-soft)] font-normal">
                {drawerTargetBox?.teamName ? `Workspace: ${drawerTargetBox.teamName}` : drawerTargetBox?.name || "Slack Channels"}
              </div>
            </div>
          </div>
        }
        className="slack-channel-slide-drawer"
        styles={{
          body: {
            padding: "20px 24px",
            display: "flex",
            flexDirection: "column",
            gap: "16px",
          },
        }}
        footer={
          <div className="flex items-center justify-between gap-3 py-2">
            <Button
              type="text"
              icon={<SyncOutlined spin={drawerTargetBox ? !!actionLoading[drawerTargetBox.id] : false} />}
              onClick={() => drawerTargetAgent && drawerTargetBox && fetchSlackChannels(drawerTargetAgent.id, drawerTargetBox.id)}
              disabled={drawerTargetBox ? !!actionLoading[drawerTargetBox.id] : false}
              className="text-xs text-[var(--app-text-soft)]"
            >
              Refresh Slack Channels
            </Button>
            <Button
              type="primary"
              onClick={() => setDrawerTargetBox(null)}
              className="rounded-xl px-6 font-semibold !bg-[#0fb5a1] hover:!bg-[#0a8576] !border-none"
            >
              Done
            </Button>
          </div>
        }
      >
        {/* Sticky Real-Time Search Bar inside Slide Drawer */}
        <div className="space-y-2 sticky top-0 z-10 bg-[var(--app-surface)] pb-2">
          <Input
            size="large"
            prefix={<SearchOutlined className="text-[#0fb5a1] mr-1" />}
            placeholder="Search Slack channels (#general, #support)..."
            allowClear
            value={channelSearchText}
            onChange={(e) => setChannelSearchText(e.target.value)}
            className="rounded-xl"
            autoFocus
          />
          <div className="flex justify-between items-center px-1 text-[11px] text-[var(--app-text-soft)]">
            <span>
              Showing {filteredDrawerChannels.length} of {drawerChannels.length} channels
            </span>
            {channelSearchText && (
              <button
                onClick={() => setChannelSearchText("")}
                className="text-[#0fb5a1] hover:underline bg-transparent border-none cursor-pointer p-0 text-[11px]"
              >
                Clear filter
              </button>
            )}
          </div>
        </div>

        {/* Channel Items List */}
        <div className="flex-1 overflow-y-auto space-y-2.5 no-scrollbar pr-1">
          {drawerTargetBox && actionLoading[drawerTargetBox.id] ? (
            <div className="py-16 text-center">
              <Spin size="default" />
              <Text className="block mt-3 text-xs text-[var(--app-text-soft)]">
                Fetching channels from Slack...
              </Text>
            </div>
          ) : filteredDrawerChannels.length === 0 ? (
            <div className="py-12 text-center rounded-2xl border border-dashed border-[var(--app-border)] p-6 space-y-3">
              <div className="w-10 h-10 mx-auto rounded-full bg-slate-100 dark:bg-slate-800 text-slate-400 flex items-center justify-center">
                <NumberOutlined className="text-lg" />
              </div>
              <div>
                <p className="font-semibold text-xs text-[var(--app-text)] m-0">
                  {channelSearchText ? "No channels match your search" : "No channels found"}
                </p>
                <p className="text-[11px] text-[var(--app-text-soft)] mt-1 m-0">
                  {channelSearchText
                    ? "Try searching for a different channel name"
                    : "Make sure the Slack app has permission to view channels in your workspace."}
                </p>
              </div>
            </div>
          ) : (
            filteredDrawerChannels.map((ch) => {
              const isLinked = drawerTargetBox?.linkedChannels?.some((l) => l.id === ch.id);
              const isPrimary = drawerTargetBox?.channelId === ch.id;

              return (
                <div
                  key={ch.id}
                  className={`flex items-center justify-between p-3.5 rounded-2xl border transition-all ${
                    isLinked
                      ? "bg-[#0fb5a1]/5 border-[#0fb5a1]/30 shadow-xs"
                      : "border-[var(--app-border)] hover:border-[#0fb5a1]/40 hover:bg-slate-50/80 dark:hover:bg-slate-800/40"
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0 flex-1">
                    <div
                      className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 ${
                        isLinked
                          ? "bg-[#0fb5a1] text-white"
                          : "bg-slate-100 dark:bg-slate-800 text-slate-500"
                      }`}
                    >
                      <NumberOutlined className="text-sm font-bold" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-xs text-[var(--app-text)] truncate">
                          #{ch.name}
                        </span>
                        {isPrimary && (
                          <span className="text-[9px] font-bold px-1.5 py-0.2 bg-[#0fb5a1] text-white rounded-md">
                            Primary
                          </span>
                        )}
                      </div>
                      <span className="text-[10px] text-[var(--app-text-soft)] block truncate">
                        ID: {ch.id}
                      </span>
                    </div>
                  </div>

                  <div className="shrink-0 ml-3">
                    {isLinked ? (
                      <div className="flex items-center gap-1.5">
                        <Tag color="success" icon={<CheckOutlined />} className="rounded-full text-[10px] m-0">
                          Linked
                        </Tag>
                        <Button
                          type="text"
                          danger
                          size="small"
                          onClick={() => drawerTargetBox && handleRemoveLinkedChannel(drawerTargetBox.id, ch.id)}
                          className="text-[11px] px-1.5 py-0.5"
                        >
                          Remove
                        </Button>
                      </div>
                    ) : (
                      <Button
                        size="small"
                        type="primary"
                        icon={<PlusOutlined />}
                        loading={drawerTargetBox ? !!actionLoading[drawerTargetBox.id] : false}
                        onClick={() =>
                          drawerTargetBox &&
                          drawerTargetAgent &&
                          handleSelectChannel(drawerTargetBox.id, drawerTargetAgent.id, ch.id, ch.name)
                        }
                        className="rounded-xl text-xs font-semibold !bg-[#0fb5a1] hover:!bg-[#0a8576] !border-none"
                      >
                        Link
                      </Button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </Drawer>

      {/* GLOBAL UTILITY CSS FOR NO-SCROLLBAR */}
      <style jsx global>{`
        .no-scrollbar::-webkit-scrollbar {
          display: none !important;
        }
        .no-scrollbar {
          -ms-overflow-style: none !important;
          scrollbar-width: none !important;
        }
      `}</style>
    </div>
  );
}

export default function SlackIntegrationSettings() {
  return (
    <App>
      <SlackIntegrationContent />
    </App>
  );
}
