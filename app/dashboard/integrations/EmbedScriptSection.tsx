"use client";
import { Flex, Typography, Card, Button, Tooltip, App, Radio, Input, Modal, Switch, Spin, Tabs, Select } from "antd";
import {
  CopyOutlined,
  CheckCircleOutlined,
  SettingOutlined,
  EyeOutlined,
  CloudUploadOutlined,
  MessageOutlined,
  RobotOutlined,
  InfoCircleOutlined,
  BookOutlined,
  QuestionCircleOutlined,
  PlusOutlined,
  CommentOutlined,
  FileTextOutlined,
  UnorderedListOutlined,
  DownloadOutlined,
  LinkOutlined,
  LikeOutlined,
  DislikeOutlined,
  TeamOutlined,
  UserOutlined,
  CustomerServiceOutlined,
} from "@ant-design/icons";
import { useState, useEffect, useRef } from "react";
import { SiCrowdsource } from "react-icons/si";
import axios from "axios";
import AgentList from "../../components/ui/AgentList";
import useAxios from "../../hooks/useAxios";
import { useStore } from "../../hooks/useStore";
import { getCookie } from "../../config/cookies";
import type { Agent } from "../../components/ui/type";
import { LeadCaptureForm, EscalationHeaderLink, EscalationSystemMessage } from "./LeadEscalationComponents";

const { Title, Text } = Typography;

type Message = {
  role: "user" | "assistant";
  content: string;
};

type AgentListResponse = {
  data?: {
    agents?: Agent[];
  };
};

type ChatSession = {
  id: string;
  agentId: string;
  agentName: string;
  messages: Message[];
  updatedAt: number;
  agent_id: string;
  title: string;
  message_count: number;
  is_active: boolean;
  last_message_at: string;
  created_at: string;
};

// Preset colors for brand theme picker
const COLOR_PRESETS = [
  { name: "Teal", hex: "#0fb5a1" },
  { name: "Blue", hex: "#0066cc" },
  { name: "Purple", hex: "#7f00ff" },
  { name: "Green", hex: "#22c55e" },
  { name: "Red", hex: "#ef4444" },
];

// SVG Data URLs for Presets (Valid inline SVGs ensuring no broken images)
const LOGO_PRESET_DARK = "";
const LOGO_PRESET_LIGHT = "";
const LOGO_PRESET_MINI = "";

const AVATAR_PRESET_CHAT = "";
const AVATAR_PRESET_ROBOT = "";
const AVATAR_PRESET_SETTING = "";
const AVATAR_PRESET_INFO = "";
const AVATAR_PRESET_BOOK = "";
const AVATAR_PRESET_QUESTION = "";

// Convert S3 logo URLs to backend proxy render URLs (S3 returns 403 Forbidden)
const toProxyLogoUrl = (url: string): string => {
  if (!url) return url;
  const cleanUrl = url.split("?")[0];
  const s3Match = cleanUrl.match(/amazonaws\.com\/grag\/logos\/(.+)/);
  const proxyMatch = cleanUrl.match(/\/embed\/logo\/render\/(.+)/);
  const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "";
  if (s3Match) {
    return `${apiBase}/embed/logo/render/${s3Match[1]}`;
  } else if (proxyMatch) {
    return `${apiBase}/embed/logo/render/${proxyMatch[1]}`;
  }
  return url;
};


export default function EmbedScriptSection() {
  const { notification } = App.useApp();
  const [copied, setCopied] = useState(false);
  const setAgentList = useStore((state) => state.setAgentList);
  const setBotsCache = useStore((state) => state.setBotsCache);
  const [agentresp, setAgentresponse] = useState<any>(null);
  const [agent, setAgent] = useState<{ id: string; name: string } | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [getAgents] = useAxios<AgentListResponse>({ endpoint: "GETAGENTLIST", hideErrorMsg: true });

  // 1. Core Layout & Theme States
  const [chatType, setChatType] = useState<"icon" | "search">("icon");
  const [position, setPosition] = useState<"center" | "right">("center");
  const [placeholderText, setPlaceholderText] = useState("Ask about web scraping, Zyte API, anything data extraction...");
  const [themeColor, setThemeColor] = useState("#0fb5a1");

  // 2. Header Styles States
  const [headerLogo, setHeaderLogo] = useState<string>(LOGO_PRESET_DARK);
  const [headerAlignment, setHeaderAlignment] = useState<"left" | "center">("center");

  // 3. Bot Identity States
  const [botAvatar, setBotAvatar] = useState<string>("chat");

  // 4. Entry Button States
  const [buttonIcon, setButtonIcon] = useState<string>("chat");
  const [buttonAlignment, setButtonAlignment] = useState<"left" | "right">("right");
  const [showButtonText, setShowButtonText] = useState<boolean>(true);
  const [buttonText, setButtonText] = useState<string>("Help");

  // 5. Content States
  const [initialMessage, setInitialMessage] = useState<string>("Hi! I'm your AI Support Agent. How can I help you today?");
  const [displaySources, setDisplaySources] = useState<boolean>(true);
  const [allowDownloads, setAllowDownloads] = useState<boolean>(false);
  const [displayCopyBtn, setDisplayCopyBtn] = useState<boolean>(true);
  const [displayFeedback, setDisplayFeedback] = useState<boolean>(true);
  const [linkSafety, setLinkSafety] = useState<boolean>(false);

  // 6. Lead Collection & Support Escalation States
  const [leadCollection, setLeadCollection] = useState<boolean>(false);
  const [leadFields, setLeadFields] = useState<string>("name,email");
  const [leadTiming, setLeadTiming] = useState<string>("pre-chat");
  const [escalationEnabled, setEscalationEnabled] = useState<boolean>(false);
  const [escalationLink, setEscalationLink] = useState<string>("https://docsbot.ai/");

  const [draftLeadCollection, setDraftLeadCollection] = useState<boolean>(false);
  const [draftLeadFields, setDraftLeadFields] = useState<string>("name,email");
  const [draftLeadTiming, setDraftLeadTiming] = useState<string>("pre-chat");
  const [draftEscalationEnabled, setDraftEscalationEnabled] = useState<boolean>(false);
  const [draftEscalationLink, setDraftEscalationLink] = useState<string>("https://docsbot.ai/");

  // Modal Customizer Draft States
  const [isCustomizerOpen, setIsCustomizerOpen] = useState(false);
  const [draftChatType, setDraftChatType] = useState<"icon" | "search">("icon");
  const [draftPosition, setDraftPosition] = useState<"center" | "right">("center");
  const [draftPlaceholderText, setDraftPlaceholderText] = useState("Ask about web scraping, Zyte API, anything data extraction...");
  const [draftThemeColor, setDraftThemeColor] = useState("#0fb5a1");

  const [draftHeaderLogo, setDraftHeaderLogo] = useState<string>(headerLogo);
  const [draftHeaderAlignment, setDraftHeaderAlignment] = useState<"left" | "center">(headerAlignment);
  const [draftBotAvatar, setDraftBotAvatar] = useState<string>("chat");

  // Logo Placement Visibility States
  const [showInHeader, setShowInHeader] = useState<boolean>(true);
  const [showInChat, setShowInChat] = useState<boolean>(true);
  const [showInEmbed, setShowInEmbed] = useState<boolean>(false);

  const [draftShowInHeader, setDraftShowInHeader] = useState<boolean>(true);
  const [draftShowInChat, setDraftShowInChat] = useState<boolean>(true);
  const [draftShowInEmbed, setDraftShowInEmbed] = useState<boolean>(false);

  const [draftButtonIcon, setDraftButtonIcon] = useState<string>(buttonIcon);
  const [draftButtonAlignment, setDraftButtonAlignment] = useState<"left" | "right">(buttonAlignment);
  const [draftShowButtonText, setDraftShowButtonText] = useState<boolean>(showButtonText);
  const [draftButtonText, setDraftButtonText] = useState<string>(buttonText);

  const [draftInitialMessage, setDraftInitialMessage] = useState<string>(initialMessage);
  const [draftDisplaySources, setDraftDisplaySources] = useState<boolean>(displaySources);
  const [draftAllowDownloads, setDraftAllowDownloads] = useState<boolean>(allowDownloads);
  const [draftDisplayCopyBtn, setDraftDisplayCopyBtn] = useState<boolean>(displayCopyBtn);
  const [draftDisplayFeedback, setDraftDisplayFeedback] = useState<boolean>(displayFeedback);
  const [draftLinkSafety, setDraftLinkSafety] = useState<boolean>(linkSafety);

  // Upload Loading States
  const [uploadingHeaderLogo, setUploadingHeaderLogo] = useState(false);
  const [uploadingBotAvatar, setUploadingBotAvatar] = useState(false);
  const [uploadingButtonIcon, setUploadingButtonIcon] = useState(false);

  // Helper to reliably extract Authorization Token from cookies
  const getAuthToken = (): string => {
    if (typeof window === "undefined") return "";
    let token = getCookie("AUTH_TOKEN") || getCookie("auth_token") || getCookie("token") || getCookie("access_token") || "";
    console.log("🔍 [DEBUG] getCookie('AUTH_TOKEN'):", getCookie("AUTH_TOKEN"));
    console.log("🔍 [DEBUG] document.cookie:", document.cookie);
    if (!token && typeof document !== "undefined") {
      const match = document.cookie.match(new RegExp("(?:^|; )(?:AUTH_TOKEN|auth_token|token|access_token)=([^;]*)"));
      if (match && match[1]) token = decodeURIComponent(match[1]);
    }
    if (!token && typeof localStorage !== "undefined") {
      token = localStorage.getItem("AUTH_TOKEN") || localStorage.getItem("auth_token") || localStorage.getItem("token") || localStorage.getItem("access_token") || "";
    }
    if (token) {
      token = token.replace(/^["']|["']$/g, "").replace(/^Bearer\s+/i, "").trim();
    }
    return token;
  };

  // Fetch Stored Embed Customization (GET API)
  useEffect(() => {
    const fetchEmbedCustomization = async () => {
      try {
        const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
        const token = getAuthToken();
        const authHeader = token ? (token.startsWith("Bearer ") ? token : `Bearer ${token}`) : "";

        const tenantId = localStorage.getItem("tenantId") || agentresp?.[0]?.tenant_id || "default_tenant";
        const res = await fetch(`${baseUrl}/embed/customization?tenant_id=${tenantId}`, {
          headers: authHeader ? { Authorization: authHeader } : {},
          credentials: "include"
        });

        if (res.ok) {
          const result = await res.json();
          const data = result.data ?? result;
          if (data) {
            if (data.logo_url) {
              const proxyUrl = toProxyLogoUrl(data.logo_url);
              setHeaderLogo(proxyUrl);
              setDraftHeaderLogo(proxyUrl);
            }
            if (typeof data.show_in_header === "boolean") {
              setShowInHeader(data.show_in_header);
              setDraftShowInHeader(data.show_in_header);
            }
            if (typeof data.show_in_chat === "boolean") {
              setShowInChat(data.show_in_chat);
              setDraftShowInChat(data.show_in_chat);
            }
            if (typeof data.show_in_embed === "boolean") {
              setShowInEmbed(data.show_in_embed);
              setDraftShowInEmbed(data.show_in_embed);
            }
          }
        }
      } catch (err) {
        console.warn("Failed to fetch customization:", err);
      }
    };
    fetchEmbedCustomization();
  }, []);

  // Sandbox Live Preview States (Inside Modal)
  const [previewMessages, setPreviewMessages] = useState<any[]>([]);
  const [previewInput, setPreviewInput] = useState("");
  const [previewIsTyping, setPreviewIsTyping] = useState(false);
  const [previewIsOpen, setPreviewIsOpen] = useState(true);
  const [previewLeadFormSubmitted, setPreviewLeadFormSubmitted] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll chat body on new preview messages
  useEffect(() => {
    const chatContainer = document.getElementById("embed-sandbox-chat-messages");
    if (chatContainer) {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }, [previewMessages, previewIsTyping, previewIsOpen]);

  const isWideLayout = draftChatType === "search" && draftPosition === "center";

  // Dynamic Theme state observer
  const [isDarkTheme, setIsDarkTheme] = useState(false);
  useEffect(() => {
    if (typeof window !== "undefined") {
      const checkDark = () => {
        return (
          document.documentElement.classList.contains("dark") ||
          document.documentElement.getAttribute("data-theme") === "dark"
        );
      };
      setIsDarkTheme(checkDark());
      const observer = new MutationObserver(() => {
        setIsDarkTheme(checkDark());
      });
      observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["class", "data-theme"],
      });
      return () => observer.disconnect();
    }
  }, []);

  function mapAgentsToList(agents: Agent[]) {
    return agents.map((agent) => ({
      id: agent.id,
      name: agent.name,
      status: agent.is_active ? "active" : "draft",
    }));
  }

  useEffect(() => {
    getAgents(undefined, (payload) => {
      const agents = payload?.data?.agents ?? [];
      setAgentresponse(agents);
      setBotsCache(agents);
      setAgentList(mapAgentsToList(agents));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reset sandbox chat state when switching draft modes in live preview
  useEffect(() => {
    setPreviewMessages([]);
    setPreviewIsOpen(false);
    setPreviewIsTyping(false);
    setPreviewInput("");
  }, [draftChatType, draftPosition]);

  // Open customizer and copy values to drafts
  const openCustomizer = () => {
    setDraftChatType(chatType);
    setDraftPosition(position);
    setDraftPlaceholderText(placeholderText);
    setDraftThemeColor(themeColor);
    setDraftHeaderLogo(headerLogo);
    setDraftHeaderAlignment(headerAlignment);
    setDraftBotAvatar(botAvatar);
    setDraftButtonIcon(buttonIcon);
    setDraftButtonAlignment(buttonAlignment);
    setDraftShowButtonText(showButtonText);
    setDraftButtonText(buttonText);

    setDraftShowInHeader(showInHeader);
    setDraftShowInChat(showInChat);
    setDraftShowInEmbed(showInEmbed);

    setDraftInitialMessage(initialMessage);
    setDraftDisplaySources(displaySources);
    setDraftAllowDownloads(allowDownloads);
    setDraftDisplayCopyBtn(displayCopyBtn);
    setDraftDisplayFeedback(displayFeedback);
    setDraftLinkSafety(linkSafety);

    setDraftLeadCollection(leadCollection);
    setDraftLeadFields(leadFields);
    setDraftLeadTiming(leadTiming);
    setDraftEscalationEnabled(escalationEnabled);
    setDraftEscalationLink(escalationLink);

    setPreviewLeadFormSubmitted(false);
    setIsCustomizerOpen(true);
  };

  // Apply customizations and update the code block
  const handleApply = async () => {
    setChatType(draftChatType);
    setPosition(draftPosition);
    setPlaceholderText(draftPlaceholderText);
    setThemeColor(draftThemeColor);
    setHeaderLogo(draftHeaderLogo);
    setHeaderAlignment(draftHeaderAlignment);
    setBotAvatar(draftBotAvatar);
    setButtonIcon(draftButtonIcon);
    setButtonAlignment(draftButtonAlignment);
    setShowButtonText(draftShowButtonText);
    setButtonText(draftButtonText);

    setShowInHeader(draftShowInHeader);
    setShowInChat(draftShowInChat);
    setShowInEmbed(draftShowInEmbed);

    setInitialMessage(draftInitialMessage);
    setDisplaySources(draftDisplaySources);
    setAllowDownloads(draftAllowDownloads);
    setDisplayCopyBtn(draftDisplayCopyBtn);
    setDisplayFeedback(draftDisplayFeedback);
    setLinkSafety(draftLinkSafety);

    setLeadCollection(draftLeadCollection);
    setLeadFields(draftLeadFields);
    setLeadTiming(draftLeadTiming);
    setEscalationEnabled(draftEscalationEnabled);
    setEscalationLink(draftEscalationLink);

    // Call PUT /api/v1/embed/customization to persist backend configuration
    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
      const token = getAuthToken();
      const authHeader = token ? (token.startsWith("Bearer ") ? token : `Bearer ${token}`) : "";
      const tenantId = localStorage.getItem("tenantId") || agentresp?.[0]?.tenant_id || "default_tenant";

      await fetch(`${baseUrl}/embed/customization`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: authHeader,
        },
        credentials: "include",
        body: JSON.stringify({
          logo_url: draftHeaderLogo || "",
          show_in_header: draftShowInHeader,
          show_in_chat: draftShowInChat,
          show_in_embed: draftShowInEmbed
        })
      });

      // Call GET /api/v1/embed/customization on OK/Apply to fetch and store stored settings
      const getRes = await fetch(`${baseUrl}/embed/customization?tenant_id=${tenantId}`, {
        method: "GET",
        headers: {
          ...(authHeader ? { Authorization: authHeader } : {})
        },
        credentials: "include"
      });
      if (getRes.ok) {
        const result = await getRes.json();
        const data = result.data ?? result;
        if (data) {
          if (data.logo_url) {
            const proxyUrl = toProxyLogoUrl(data.logo_url);
            setHeaderLogo(proxyUrl);
            setDraftHeaderLogo(proxyUrl);
          }
          if (typeof data.show_in_header === "boolean") {
            setShowInHeader(data.show_in_header);
            setDraftShowInHeader(data.show_in_header);
          }
          if (typeof data.show_in_chat === "boolean") {
            setShowInChat(data.show_in_chat);
            setDraftShowInChat(data.show_in_chat);
          }
          if (typeof data.show_in_embed === "boolean") {
            setShowInEmbed(data.show_in_embed);
            setDraftShowInEmbed(data.show_in_embed);
          }
        }
      }
    } catch (err) {
      console.warn("Failed to persist or fetch customization API:", err);
    }

    setIsCustomizerOpen(false);
    notification.success({
      message: "Widget Configuration Applied",
      description: "All header, content, bot avatar, entry button, and styling attributes have been updated.",
      placement: "topRight",
    });
  };

  // Revert draft changes and close
  const handleCancel = () => {
    setDraftChatType(chatType);
    setDraftPosition(position);
    setDraftPlaceholderText(placeholderText);
    setDraftThemeColor(themeColor);
    setDraftHeaderLogo(headerLogo);
    setDraftHeaderAlignment(headerAlignment);
    setDraftBotAvatar(botAvatar);
    setDraftButtonIcon(buttonIcon);
    setDraftButtonAlignment(buttonAlignment);
    setDraftShowButtonText(showButtonText);
    setDraftButtonText(buttonText);

    setDraftShowInHeader(showInHeader);
    setDraftShowInChat(showInChat);
    setDraftShowInEmbed(showInEmbed);

    setDraftInitialMessage(initialMessage);
    setDraftDisplaySources(displaySources);
    setDraftAllowDownloads(allowDownloads);
    setDraftDisplayCopyBtn(displayCopyBtn);
    setDraftDisplayFeedback(displayFeedback);
    setDraftLinkSafety(linkSafety);

    setDraftLeadCollection(leadCollection);
    setDraftLeadFields(leadFields);
    setDraftLeadTiming(leadTiming);
    setDraftEscalationEnabled(escalationEnabled);
    setDraftEscalationLink(escalationLink);

    setIsCustomizerOpen(false);
  };

  // Upload image file to backend API -> receive logo_url
  const uploadImageToBackend = async (file: File): Promise<string> => {
    const formData = new FormData();
    formData.append("logo", file);

    const token = getAuthToken();
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL;
    const tenantId = localStorage.getItem("tenantId") || agentresp?.[0]?.tenant_id || "default_tenant";

    const headers: Record<string, string> = {};
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const response = await axios.post(`${apiBase}/embed/logo`, formData, {
      headers,
      withCredentials: true,
    });

    const logoUrl =
      response.data?.logo_url ||
      response.data?.data?.logo_url ||
      response.data?.url ||
      response.data?.image_url;

    if (logoUrl) return toProxyLogoUrl(logoUrl);
    throw new Error("logo_url not returned by backend logo upload API");
  };

  const handleFileUpload = async (file: File, target: "headerLogo" | "botAvatar" | "buttonIcon") => {
    if (target === "headerLogo") setUploadingHeaderLogo(true);
    if (target === "botAvatar") setUploadingBotAvatar(true);
    if (target === "buttonIcon") setUploadingButtonIcon(true);

    try {
      const logoUrl = await uploadImageToBackend(file);
      if (target === "headerLogo") setDraftHeaderLogo(logoUrl);
      if (target === "botAvatar") setDraftBotAvatar(logoUrl);
      if (target === "buttonIcon") setDraftButtonIcon(logoUrl);

      // Target-specific boolean flags for PUT /api/v1/embed/customization:
      const targetShowHeader = target === "headerLogo";
      const targetShowChat = target === "botAvatar";
      const targetShowEmbed = target === "buttonIcon";

      setDraftShowInHeader(targetShowHeader);
      setDraftShowInChat(targetShowChat);
      setDraftShowInEmbed(targetShowEmbed);

      try {
        const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL;
        const token = getAuthToken();
        const authHeader = token ? (token.startsWith("Bearer ") ? token : `Bearer ${token}`) : "";
        const tenantId = localStorage.getItem("tenantId") || agentresp?.[0]?.tenant_id || "default_tenant";

        await fetch(`${apiBase}/embed/customization?tenant_id=${tenantId}`, {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            ...(authHeader ? { Authorization: authHeader } : {})
          },
          credentials: "include",
          body: JSON.stringify({
            logo_url: logoUrl,
            show_in_header: targetShowHeader,
            show_in_chat: targetShowChat,
            show_in_embed: targetShowEmbed
          })
        });
      } catch (syncErr) {
        console.warn("Auto customization sync after upload warning:", syncErr);
      }

      notification.success({
        message: "Logo Uploaded Successfully",
        description: "Logo uploaded and saved in embed customization settings.",
        placement: "topRight",
      });
    } catch (err: any) {
      console.warn("Backend upload endpoint offline or error, creating object URL fallback for preview:", err);
      const fallbackUrl = URL.createObjectURL(file);
      if (target === "headerLogo") setDraftHeaderLogo(fallbackUrl);
      if (target === "botAvatar") setDraftBotAvatar(fallbackUrl);
      if (target === "buttonIcon") setDraftButtonIcon(fallbackUrl);

      notification.info({
        message: "Image Selected",
        description: "",
        placement: "topRight",
      });
    } finally {
      if (target === "headerLogo") setUploadingHeaderLogo(false);
      if (target === "botAvatar") setUploadingBotAvatar(false);
      if (target === "buttonIcon") setUploadingButtonIcon(false);
    }
  };

  // Generate dynamic embed script block based on APPLIED states
  const scriptCode = `<script src='${process.env.NEXT_PUBLIC_API_BASES_URL || "http://grag.gramopro.ai"}/chat.js'
  data-agent-id="${agent?.id || "YOUR_AGENT_ID"}"
  data-tenant-id="${agentresp?.[0]?.tenant_id || "YOUR_TENANT_ID"}"
  data-chat-type="${chatType}"${chatType === "search" ? `\n  data-position="${position}"\n  data-placeholder="${placeholderText}"` : ""}
  data-theme-color="${themeColor}"
  data-header-logo="${headerLogo}"
  data-header-align="${headerAlignment}"
  data-bot-avatar="${botAvatar}"
  data-button-icon="${buttonIcon}"
  data-button-align="${buttonAlignment}"
  data-show-button-text="${showButtonText}"
  data-button-text="${buttonText}"${initialMessage ? `\n  data-initial-message="${initialMessage}"` : ""}
  data-display-sources="${displaySources}"
  data-allow-downloads="${allowDownloads}"
  data-display-copy="${displayCopyBtn}"
  data-display-feedback="${displayFeedback}"
  data-link-safety="${linkSafety}"
  data-lead-collection="${leadCollection}"
  data-lead-fields='${JSON.stringify(leadFields.split(",").map(f => f.trim()))}'
  data-lead-timing="${leadTiming}"
  data-escalation-enabled="${escalationEnabled}"
  data-escalation-link="${escalationLink}"
>
</script>`;

  const handleCopy = () => {
    if (!agent?.id) {
      notification.warning({
        message: "Select an Agent",
        description: "Please select an agent before copying the script.",
        placement: "topRight",
      });
      return;
    }

    const textarea = document.createElement("textarea");
    textarea.value = scriptCode;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);

    setCopied(true);
    notification.success({
      message: "Copied to Clipboard",
      description: "The snippet is ready to be pasted into your web code base.",
      placement: "topRight",
    });

    setTimeout(() => setCopied(false), 2000);
  };

  const loadSession = (session: ChatSession) => {
    setAgent({
      id: session.agent_id || session.agentId,
      name: session.title || session.agentName,
    });
  };

  const startNewChat = (selectedAgent: { id: string; name: string }) => {
    const newSessionId = `session_${Date.now()}`;
    const newSession: any = {
      id: newSessionId,
      agentId: selectedAgent.id,
      agentName: selectedAgent.name,
      messages: [],
      updatedAt: Date.now(),
    };
    setSessions((prev) => [newSession, ...prev]);
    setAgent(selectedAgent);
  };

  const handlePreviewSend = (text: string) => {
    const query = text.trim();
    if (!query) return;

    setPreviewIsOpen(true);
    setPreviewMessages((prev) => [...prev, { role: "user", content: query }]);
    setPreviewInput("");
    setPreviewIsTyping(true);
    setTimeout(() => {
      setPreviewIsTyping(false);
      setPreviewMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `This is a **live simulated response** using theme color (**${draftThemeColor}**)! \n\nOnce embedded, it streams real-time responses from AI Agent (**${agent?.name || "Gsearch AI"
            }**).`,
        },
      ]);
    }, 1200);
  };

  // Preset arrays for Bot Avatar and Entry Button Icons
  const botAvatarPresets = [
    { id: "chat", icon: <MessageOutlined className="text-lg text-slate-500" /> },
    { id: "robot", icon: <RobotOutlined className="text-lg text-slate-500" /> },
    { id: "setting", icon: <SettingOutlined className="text-lg text-slate-500" /> },
    { id: "info", icon: <InfoCircleOutlined className="text-lg text-slate-500" /> },
    { id: "book", icon: <BookOutlined className="text-lg text-slate-500" /> },
  ];

  const buttonIconPresets = [
    { id: "chat", icon: <MessageOutlined className="text-lg text-slate-500" /> },
    { id: "robot", icon: <RobotOutlined className="text-lg text-slate-500" /> },
    { id: "setting", icon: <SettingOutlined className="text-lg text-slate-500" /> },
    { id: "question", icon: <QuestionCircleOutlined className="text-lg text-slate-500" /> },
    { id: "book", icon: <BookOutlined className="text-lg text-slate-500" /> },
  ];

  return (
    <Flex vertical gap={40}>
      {/* Header Section */}
      <div className="space-y-3 max-w-3xl">
        <Title level={1} className="!m-0 !text-[var(--app-text)] !font-extrabold !text-3xl md:!text-5xl tracking-tight">
          Omnichannel Integrations
        </Title>
        <Text className="text-[var(--app-text-muted)] text-base md:text-lg block leading-relaxed">
          Deploy your cognitive AI agents across every customer touchpoint with seamless integration hooks.
        </Text>
      </div>

      {/* Embed Control card on page */}
      <Card
        className="bg-[var(--app-surface)] border border-[var(--app-border)] rounded-3xl shadow-md overflow-hidden"
        styles={{ body: { padding: "24px md:36px" } }}
      >
        <Flex vertical gap={24}>
          <Flex justify="space-between" align="center" wrap="wrap" gap={16}>
            <div className="space-y-1">
              <Title level={3} className="!m-0 !text-[var(--app-text)] !font-bold !text-xl tracking-tight">
                Embed Script Snippet
              </Title>
              <Text className="text-[var(--app-text-soft)] text-xs font-medium uppercase tracking-wider block">
                Copy the snippet below to initialize the custom widget on your host page.
              </Text>
            </div>

            <Flex gap={12} wrap="wrap" className="w-full sm:w-auto">
              <Button
                type="default"
                size="large"
                icon={<SettingOutlined />}
                onClick={openCustomizer}
                className="w-full sm:w-auto !h-11 !px-5 !rounded-xl !border-[#0fb5a1] !text-[#0fb5a1] hover:!text-[#0a8576] hover:!border-[#0a8576] !font-semibold transition-transform active:scale-95 flex items-center justify-center gap-1.5"
              >
                Customize Chat Style
              </Button>
              <Tooltip title={copied ? "Copied!" : "Copy Script"}>
                <Button
                  type="primary"
                  size="large"
                  icon={copied ? <CheckCircleOutlined /> : <CopyOutlined />}
                  onClick={handleCopy}
                  className="w-full sm:w-auto !h-11 !px-6 !rounded-xl !bg-[#0fb5a1] !border-none !font-semibold transition-transform active:scale-95 flex items-center justify-center gap-2"
                >
                  {copied ? "Copied" : "Copy Code"}
                </Button>
              </Tooltip>
            </Flex>
          </Flex>
          <div className="flex items-center gap-4 bg-[var(--app-surface-muted)] p-3 rounded-2xl border border-[var(--app-border)] max-w-sm">
            <Text className="text-xs font-bold uppercase tracking-wider text-[var(--app-text-muted)] shrink-0">Select AI Agent:</Text>
            <div className="flex-1" style={{ minWidth: "180px", maxWidth: "240px" }}>
              <AgentList
                selectedId={agent?.id}
                size="middle"
                style={{ width: "100%", height: 38 }}
                onChange={(id: string, name: string) => {
                  const existing = sessions.find((s) => s.agentId === id);
                  if (existing) loadSession(existing);
                  else startNewChat({ id, name });
                }}
              />
            </div>
          </div>

          {/* Code block window display */}
          <div className="relative group rounded-2xl border border-[var(--app-border)] bg-[var(--app-surface-muted)] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--app-border)] bg-[var(--app-surface)]/50">
              <div className="flex gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-red-400/70" />
                <span className="w-2.5 h-2.5 rounded-full bg-amber-400/70" />
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-400/70" />
              </div>
              <Text className="text-[9px] font-bold uppercase tracking-widest text-slate-400">HTML</Text>
            </div>
            <pre className="p-4 md:p-5 overflow-x-auto custom-scrollbar m-0">
              <code className="text-[var(--app-text)] font-mono text-xs leading-relaxed block whitespace-pre">
                <span className="text-[#0fb5a1] opacity-80">{"<script "}</span>
                <span className="text-[#3b82f6]">src=</span>
                <span className="text-emerald-500">{`'${process.env.NEXT_PUBLIC_API_BASES_URL || "http://grag.gramopro.ai"}/chat.js'`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-agent-id=</span>
                <span className="text-emerald-500">{`"${agent?.id || "YOUR_AGENT_ID"}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-tenant-id=</span>
                <span className="text-emerald-500">{`"${agentresp?.[0]?.tenant_id || "YOUR_TENANT_ID"}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-chat-type=</span>
                <span className="text-emerald-500">{`"${chatType}"`}</span>
                {chatType === "search" && (
                  <>
                    {"\n  "}
                    <span className="text-[#3b82f6]">data-position=</span>
                    <span className="text-emerald-500">{`"${position}"`}</span>
                    {"\n  "}
                    <span className="text-[#3b82f6]">data-placeholder=</span>
                    <span className="text-emerald-500">{`"${placeholderText}"`}</span>
                  </>
                )}
                {"\n  "}
                <span className="text-[#3b82f6]">data-theme-color=</span>
                <span className="text-emerald-500">{`"${themeColor}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-header-logo=</span>
                <span className="text-emerald-500">{`"${headerLogo}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-header-align=</span>
                <span className="text-emerald-500">{`"${headerAlignment}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-bot-avatar=</span>
                <span className="text-emerald-500">{`"${botAvatar}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-button-icon=</span>
                <span className="text-emerald-500">{`"${buttonIcon}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-button-align=</span>
                <span className="text-emerald-500">{`"${buttonAlignment}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-show-button-text=</span>
                <span className="text-emerald-500">{`"${showButtonText}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-button-text=</span>
                <span className="text-emerald-500">{`"${buttonText}"`}</span>
                {initialMessage && (
                  <>
                    {"\n  "}
                    <span className="text-[#3b82f6]">data-initial-message=</span>
                    <span className="text-emerald-500">{`"${initialMessage}"`}</span>
                  </>
                )}
                {"\n  "}
                <span className="text-[#3b82f6]">data-display-sources=</span>
                <span className="text-emerald-500">{`"${displaySources}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-allow-downloads=</span>
                <span className="text-emerald-500">{`"${allowDownloads}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-display-copy=</span>
                <span className="text-emerald-500">{`"${displayCopyBtn}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-display-feedback=</span>
                <span className="text-emerald-500">{`"${displayFeedback}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-link-safety=</span>
                <span className="text-emerald-500">{`"${linkSafety}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-lead-collection=</span>
                <span className="text-emerald-500">{`"${leadCollection}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-lead-fields=</span>
                <span className="text-emerald-500">{`'${JSON.stringify(leadFields.split(",").map(f => f.trim()))}'`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-lead-timing=</span>
                <span className="text-emerald-500">{`"${leadTiming}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-escalation-enabled=</span>
                <span className="text-emerald-500">{`"${escalationEnabled}"`}</span>
                {"\n  "}
                <span className="text-[#3b82f6]">data-escalation-link=</span>
                <span className="text-emerald-500">{`"${escalationLink}"`}</span>
                <span className="text-[#0fb5a1] opacity-80">{">"}</span>
                <span className="text-[#0fb5a1] opacity-80">{"</script>"}</span>
              </code>
            </pre>
          </div>
        </Flex>
      </Card>

      {/* FULL CUSTOMIZATION POPUP MODAL */}
      <Modal
        title={
          <div className="text-lg font-extrabold text-slate-800 dark:text-slate-100 border-b border-slate-100 dark:border-slate-800 pb-3 flex items-center gap-2">
            <span className="w-7 h-7 rounded-lg bg-[#0fb5a1]/10 flex items-center justify-center text-[#0fb5a1]">
              <SettingOutlined size={16} />
            </span>
            Customize Chat Widget Style & Color
          </div>
        }
        open={isCustomizerOpen}
        onOk={handleApply}
        onCancel={handleCancel}
        okText="OK"
        cancelText="Cancel"
        okButtonProps={{
          className: "!bg-[#0fb5a1] hover:!bg-[#0a8576] !border-none !rounded-xl !h-10 !px-6 !font-semibold",
        }}
        cancelButtonProps={{
          className: "!rounded-xl !h-10 !px-5",
        }}
        width={1180}
        centered
        className="custom-widget-modal"
      >
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 py-4 items-start">
          {/* Modal Left Column: Ant Design Tabs for Configurations (span 6) */}
          <div className="lg:col-span-6 flex flex-col gap-4">
            <Tabs
              defaultActiveKey="header"
              type="card"
              className="custom-widget-tabs"
              items={[
                {
                  key: "header",
                  label: (
                    <span className="flex items-center gap-1.5 font-bold text-xs">
                      <SettingOutlined /> Header Styles
                    </span>
                  ),
                  children: (
                    <div className="p-4 rounded-2xl bg-slate-50/70 dark:bg-slate-900/60 border border-slate-200/80 dark:border-slate-800 space-y-4 min-h-[350px]">
                      <div>
                        <h4 className="font-bold text-sm text-slate-800 dark:text-slate-200 m-0">Header Styles</h4>
                        <p className="text-[11px] text-slate-400 m-0">Personalize the look of your widget header.</p>
                      </div>

                      {/* Preset Header Logos */}
                      {/* <div>
                        <label className="text-xs font-semibold text-slate-500 block mb-1.5">Preset Logos:</label>
                        <div className="flex items-center gap-3">
                          {[LOGO_PRESET_DARK, LOGO_PRESET_LIGHT, LOGO_PRESET_MINI].map((presetUrl, idx) => (
                            <div
                              key={idx}
                              onClick={() => setDraftHeaderLogo(presetUrl)}
                              className={`w-14 h-14 rounded-xl border-2 cursor-pointer p-1.5 flex items-center justify-center bg-white dark:bg-slate-950 transition-all ${draftHeaderLogo === presetUrl
                                  ? "border-[#0fb5a1] ring-2 ring-[#0fb5a1]/20 scale-105"
                                  : "border-slate-200 dark:border-slate-800 hover:border-slate-300"
                                }`}
                            >
                              <img src={presetUrl} alt={`Preset ${idx + 1}`} className="max-h-full max-w-full object-contain rounded-md" />
                            </div>
                          ))}
                        </div>
                      </div> */}

                      {/* Selected Logo & Upload to S3 */}
                      <div>
                        <label className="text-xs font-semibold text-slate-500 block mb-1.5">Selected Logo:</label>
                        <div className="flex items-center gap-3">
                          <div className="relative w-28 h-14 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950 p-1 flex items-center justify-center shadow-sm">
                            {draftHeaderLogo ? (
                              <>
                                <img src={draftHeaderLogo} alt="Selected Logo" className="max-h-full max-w-full object-contain" />
                                <button
                                  type="button"
                                  onClick={() => setDraftHeaderLogo("")}
                                  className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-red-500 text-white flex items-center justify-center text-xs hover:bg-red-600 transition-colors shadow-md border-none cursor-pointer"
                                  title="Remove logo"
                                >
                                  ✕
                                </button>
                              </>
                            ) : (
                              <span className="text-[10px] text-slate-400 italic">No logo selected</span>
                            )}
                          </div>

                          {/* Cloud Upload Button */}
                          <label className="w-14 h-14 rounded-xl border border-slate-200 dark:border-slate-800 hover:border-[#0fb5a1] cursor-pointer flex items-center justify-center bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-300 hover:text-[#0fb5a1] transition-all shadow-sm">
                            {uploadingHeaderLogo ? (
                              <Spin size="small" />
                            ) : (
                              <CloudUploadOutlined className="text-xl" />
                            )}
                            <input
                              type="file"
                              accept="image/*"
                              className="hidden"
                              onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) handleFileUpload(file, "headerLogo");
                              }}
                            />
                          </label>
                        </div>
                        <p className="text-[10px] text-slate-400 mt-1.5 mb-0">Recommended size: 120 × 40 px or 3:1 aspect ratio (PNG, SVG, JPG, max 2MB)</p>
                      </div>

                      {/* Logo Alignment */}
                      <div>
                        <label className="text-xs font-semibold text-slate-500 block mb-1.5">Alignment</label>
                        <Radio.Group
                          value={draftHeaderAlignment}
                          onChange={(e) => setDraftHeaderAlignment(e.target.value)}
                          size="middle"
                        >
                          <Radio value="left">Left</Radio>
                          <Radio value="center">Center</Radio>
                        </Radio.Group>
                      </div>
                    </div>
                  ),
                },
                {
                  key: "content",
                  label: (
                    <span className="flex items-center gap-1.5 font-bold text-xs">
                      <FileTextOutlined /> Content
                    </span>
                  ),
                  children: (
                    <div className="p-4 rounded-2xl bg-slate-50/70 dark:bg-slate-900/60 border border-slate-200/80 dark:border-slate-800 space-y-3.5 min-h-[350px] max-h-[450px] overflow-y-auto custom-scrollbar">
                      {/* Initial Message Section */}
                      <div>
                        <label className="font-bold text-xs text-slate-800 dark:text-slate-200 block mb-0.5">
                          Initial Message
                        </label>
                        <p className="text-[10px] text-slate-400 m-0 mb-1.5 leading-normal">
                          This text will appear as the first message from the bot displayed to the user. Supports Markdown. Optional, leave blank to disable.
                        </p>
                        <Input.TextArea
                          rows={2}
                          value={draftInitialMessage}
                          onChange={(e) => setDraftInitialMessage(e.target.value)}
                          placeholder="Hi! I'm your AI Support Agent. How can I help you today?"
                          className="rounded-xl border-slate-300 dark:border-slate-700 dark:bg-slate-950 focus:border-[#0fb5a1] text-xs p-2.5"
                        />
                      </div>

                      {/* Switch Toggles List */}
                      <div className="space-y-2 pt-1">
                        {/* 1. Display Sources */}
                        <div className="p-2.5 rounded-xl bg-white dark:bg-slate-950 border border-slate-200/80 dark:border-slate-800 flex items-center justify-between gap-3 shadow-xs">
                          <div className="flex items-start gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-900 flex items-center justify-center text-slate-600 dark:text-slate-300 shrink-0 mt-0.5">
                              <UnorderedListOutlined className="text-xs" />
                            </div>
                            <div>
                              <div className="text-xs font-bold text-slate-800 dark:text-slate-200">Display Sources</div>
                              <div className="text-[10px] text-slate-400 leading-tight">Show sources titles and links after answers.</div>
                            </div>
                          </div>
                          <Switch
                            checked={draftDisplaySources}
                            onChange={(checked) => setDraftDisplaySources(checked)}
                            style={{ backgroundColor: draftDisplaySources ? draftThemeColor : undefined }}
                          />
                        </div>

                        {/* 2. Allow Source Downloads */}
                        <div className="p-2.5 rounded-xl bg-white dark:bg-slate-950 border border-slate-200/80 dark:border-slate-800 flex items-center justify-between gap-3 shadow-xs">
                          <div className="flex items-start gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-900 flex items-center justify-center text-slate-600 dark:text-slate-300 shrink-0 mt-0.5">
                              <DownloadOutlined className="text-xs" />
                            </div>
                            <div>
                              <div className="flex items-center gap-1.5">
                                <span className="text-xs font-bold text-slate-800 dark:text-slate-200">Allow Source Downloads</span>
                                {/* <span className="px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-[#00a3c4] text-white leading-none">New!</span> */}
                              </div>
                              <div className="text-[10px] text-slate-400 leading-tight">Lets visitors download original document/media files from cited sources via securely signed urls.</div>
                            </div>
                          </div>
                          <Switch
                            checked={draftAllowDownloads}
                            onChange={(checked) => setDraftAllowDownloads(checked)}
                            style={{ backgroundColor: draftAllowDownloads ? draftThemeColor : undefined }}
                          />
                        </div>

                        {/* 3. Display Copy Button */}
                        <div className="p-2.5 rounded-xl bg-white dark:bg-slate-950 border border-slate-200/80 dark:border-slate-800 flex items-center justify-between gap-3 shadow-xs">
                          <div className="flex items-start gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-900 flex items-center justify-center text-slate-600 dark:text-slate-300 shrink-0 mt-0.5">
                              <CopyOutlined className="text-xs" />
                            </div>
                            <div>
                              <div className="text-xs font-bold text-slate-800 dark:text-slate-200">Display Copy Button</div>
                              <div className="text-[10px] text-slate-400 leading-tight">Shows a copy-to-clipboard button after answer.</div>
                            </div>
                          </div>
                          <Switch
                            checked={draftDisplayCopyBtn}
                            onChange={(checked) => setDraftDisplayCopyBtn(checked)}
                            style={{ backgroundColor: draftDisplayCopyBtn ? draftThemeColor : undefined }}
                          />
                        </div>

                        {/* 4. Display Feedback (Thumbs Up / Down) */}
                        <div className="p-2.5 rounded-xl bg-white dark:bg-slate-950 border border-slate-200/80 dark:border-slate-800 flex items-center justify-between gap-3 shadow-xs">
                          <div className="flex items-start gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-900 flex items-center justify-center text-slate-600 dark:text-slate-300 shrink-0 mt-0.5">
                              <LikeOutlined className="text-xs" />
                            </div>
                            <div>
                              <div className="text-xs font-bold text-slate-800 dark:text-slate-200">Display Feedback Buttons</div>
                              <div className="text-[10px] text-slate-400 leading-tight">Shows thumbs up and thumbs down feedback buttons under AI responses.</div>
                            </div>
                          </div>
                          <Switch
                            checked={draftDisplayFeedback}
                            onChange={(checked) => setDraftDisplayFeedback(checked)}
                            style={{ backgroundColor: draftDisplayFeedback ? draftThemeColor : undefined }}
                          />
                        </div>

                        {/* 5. Link Safety */}
                        <div className="p-2.5 rounded-xl bg-white dark:bg-slate-950 border border-slate-200/80 dark:border-slate-800 flex items-center justify-between gap-3 shadow-xs">
                          <div className="flex items-start gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-900 flex items-center justify-center text-slate-600 dark:text-slate-300 shrink-0 mt-0.5">
                              <LinkOutlined className="text-xs" />
                            </div>
                            <div>
                              <div className="text-xs font-bold text-slate-800 dark:text-slate-200">Link Safety</div>
                              <div className="text-[10px] text-slate-400 leading-tight">When enabled, clicking links inside the chat widget outside the current site or allowed domains will show a confirmation modal.</div>
                            </div>
                          </div>
                          <Switch
                            checked={draftLinkSafety}
                            onChange={(checked) => setDraftLinkSafety(checked)}
                            style={{ backgroundColor: draftLinkSafety ? draftThemeColor : undefined }}
                          />
                        </div>
                      </div>

                      {/* Divider */}
                      <div className="border-t border-slate-200 dark:border-slate-800 my-4" />

                      {/* Lead & Support Escalation Section */}
                      <div className="space-y-3.5 pb-2">
                        <div>
                          <h4 className="font-bold text-xs text-slate-800 dark:text-slate-200 m-0">Lead & Support Escalation</h4>
                          <p className="text-[10px] text-slate-400 m-0">Configure lead collection forms and support escalation links.</p>
                        </div>

                        {/* Lead Collection Toggle */}
                        <div className="p-2.5 rounded-xl bg-white dark:bg-slate-950 border border-slate-200/80 dark:border-slate-800 flex items-center justify-between gap-3 shadow-xs">
                          <div className="flex items-start gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-900 flex items-center justify-center text-slate-600 dark:text-slate-300 shrink-0 mt-0.5">
                              <UserOutlined className="text-xs" />
                            </div>
                            <div>
                              <div className="text-xs font-bold text-slate-800 dark:text-slate-200">Lead Collection Form</div>
                              <div className="text-[10px] text-slate-400 leading-tight">Display a form to collect information from visitors.</div>
                            </div>
                          </div>
                          <Switch
                            checked={draftLeadCollection}
                            onChange={(checked) => {
                              setDraftLeadCollection(checked);
                              setPreviewLeadFormSubmitted(false);
                            }}
                            style={{ backgroundColor: draftLeadCollection ? draftThemeColor : undefined }}
                          />
                        </div>

                        {draftLeadCollection && (
                          <div className="space-y-3 pl-2.5 border-l-2 border-slate-200 dark:border-slate-800 ml-3.5 animate-in fade-in slide-in-from-left duration-200">
                            <div className="space-y-1">
                              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                                Required Fields (Comma Separated)
                              </label>
                              <Input
                                value={draftLeadFields}
                                onChange={(e) => setDraftLeadFields(e.target.value)}
                                placeholder="name, email"
                                className="rounded-lg h-9 text-xs border-slate-300 dark:border-slate-700 dark:bg-slate-950 focus:border-[#0fb5a1]"
                              />
                            </div>

                            <div className="space-y-1">
                              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                                Lead Capture Timing
                              </label>
                              <Select
                                value={draftLeadTiming}
                                onChange={(val) => setDraftLeadTiming(val)}
                                className="w-full text-xs"
                                size="middle"
                                options={[
                                  { value: "pre-chat", label: "Pre-Chat (Form shows before chatting starts)" }
                                ]}
                              />
                            </div>
                          </div>
                        )}

                        {/* Escalation Toggle */}
                        <div className="p-2.5 rounded-xl bg-white dark:bg-slate-950 border border-slate-200/80 dark:border-slate-800 flex items-center justify-between gap-3 shadow-xs">
                          <div className="flex items-start gap-2.5">
                            <div className="w-7 h-7 rounded-lg bg-slate-100 dark:bg-slate-900 flex items-center justify-center text-slate-600 dark:text-slate-300 shrink-0 mt-0.5">
                              <CustomerServiceOutlined className="text-xs" />
                            </div>
                            <div>
                              <div className="text-xs font-bold text-slate-800 dark:text-slate-200">Human Support Escalation</div>
                              <div className="text-[10px] text-slate-400 leading-tight">Prompt a "Talk to Human Agent" redirection link.</div>
                            </div>
                          </div>
                          <Switch
                            checked={draftEscalationEnabled}
                            onChange={(checked) => setDraftEscalationEnabled(checked)}
                            style={{ backgroundColor: draftEscalationEnabled ? draftThemeColor : undefined }}
                          />
                        </div>

                        {draftEscalationEnabled && (
                          <div className="space-y-3 pl-2.5 border-l-2 border-slate-200 dark:border-slate-800 ml-3.5 animate-in fade-in slide-in-from-left duration-200">
                            <div className="space-y-1">
                              <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                                Support Escalation Link URL
                              </label>
                              <Input
                                value={draftEscalationLink}
                                onChange={(e) => setDraftEscalationLink(e.target.value)}
                                placeholder="e.g. https://docsbot.ai/"
                                className="rounded-lg h-9 text-xs border-slate-300 dark:border-slate-700 dark:bg-slate-950 focus:border-[#0fb5a1]"
                              />
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ),
                },
                {
                  key: "button",
                  label: (
                    <span className="flex items-center gap-1.5 font-bold text-xs">
                      <MessageOutlined /> Entry Button
                    </span>
                  ),
                  children: (
                    <div className="p-4 rounded-2xl bg-slate-50/70 dark:bg-slate-900/60 border border-slate-200/80 dark:border-slate-800 space-y-4 min-h-[350px]">
                      <div>
                        <h4 className="font-bold text-sm text-slate-800 dark:text-slate-200 m-0">Entry Button</h4>
                        <p className="text-[11px] text-slate-400 m-0">Customize floating chat launcher button icon & text.</p>
                      </div>

                      <div>
                        <label className="text-xs font-semibold text-slate-500 block mb-1.5">Button Icon</label>
                        <div className="flex flex-wrap items-center gap-2.5">
                          {buttonIconPresets.map((preset, idx) => (
                            <div
                              key={idx}
                              onClick={() => setDraftButtonIcon(preset.id)}
                              className={`w-10 h-10 rounded-full border-2 cursor-pointer flex items-center justify-center bg-white dark:bg-slate-950 transition-all ${draftButtonIcon === preset.id
                                ? "border-[#0fb5a1] ring-2 ring-[#0fb5a1]/20 scale-105"
                                : "border-slate-200 dark:border-slate-800 hover:border-slate-300"
                                }`}
                            >
                              {preset.icon}
                            </div>
                          ))}

                          <label className="w-10 h-10 rounded-full border-2 border-dashed border-slate-300 dark:border-slate-700 hover:border-[#0fb5a1] cursor-pointer flex items-center justify-center text-slate-400 hover:text-[#0fb5a1] transition-all bg-white dark:bg-slate-950">
                            {uploadingButtonIcon ? <Spin size="small" /> : <PlusOutlined className="text-sm" />}
                            <input
                              type="file"
                              accept="image/*"
                              className="hidden"
                              onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) handleFileUpload(file, "buttonIcon");
                              }}
                            />
                          </label>
                        </div>
                        <p className="text-[10px] text-slate-400 mt-1.5 mb-0">Recommended size: 64 × 64 px square icon (PNG, SVG, max 2MB)</p>
                      </div>

                      <div>
                        <label className="text-xs font-semibold text-slate-500 block mb-1.5">Button Alignment</label>
                        <Radio.Group
                          value={draftButtonAlignment}
                          onChange={(e) => setDraftButtonAlignment(e.target.value)}
                          size="middle"
                        >
                          <Radio value="left">Left</Radio>
                          <Radio value="right">Right</Radio>
                        </Radio.Group>
                      </div>

                      <div className="p-3 rounded-xl bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 flex items-center justify-between">
                        <div>
                          <div className="text-xs font-bold text-slate-800 dark:text-slate-200">Show Button Text</div>
                          <div className="text-[10px] text-slate-400">Show text next to the floating button icon?</div>
                        </div>
                        <Switch
                          checked={draftShowButtonText}
                          onChange={(checked) => setDraftShowButtonText(checked)}
                          style={{ backgroundColor: draftShowButtonText ? draftThemeColor : undefined }}
                        />
                      </div>

                      {draftShowButtonText && (
                        <div>
                          <label className="text-xs font-semibold text-slate-500 block mb-1.5">Button Text</label>
                          <Input
                            value={draftButtonText}
                            onChange={(e) => setDraftButtonText(e.target.value)}
                            placeholder="Help"
                            className="rounded-xl h-9 text-xs border-slate-300 dark:border-slate-700 dark:bg-slate-950 focus:border-[#0fb5a1]"
                          />
                        </div>
                      )}
                    </div>
                  ),
                },
                {
                  key: "layout",
                  label: (
                    <span className="flex items-center gap-1.5 font-bold text-xs">
                      <EyeOutlined /> Layout & Theme
                    </span>
                  ),
                  children: (
                    <div className="p-4 rounded-2xl bg-slate-50/70 dark:bg-slate-900/60 border border-slate-200/80 dark:border-slate-800 space-y-4 min-h-[350px]">
                      {/* Bot Identity Avatar Selection */}
                      <div>
                        <label className="text-xs font-bold uppercase tracking-wider text-slate-400 block mb-1.5">
                          Bot Identity Avatar
                        </label>
                        <div className="flex flex-wrap items-center gap-2.5">
                          <div
                            onClick={() => setDraftBotAvatar("none")}
                            className={`w-10 h-10 rounded-full border-2 cursor-pointer flex items-center justify-center text-xs font-bold bg-white dark:bg-slate-950 transition-all ${draftBotAvatar === "none"
                              ? "border-[#0fb5a1] ring-2 ring-[#0fb5a1]/20 text-[#0fb5a1]"
                              : "border-slate-200 dark:border-slate-800 text-slate-400"
                              }`}
                          >
                            None
                          </div>

                          {botAvatarPresets.map((preset, idx) => (
                            <div
                              key={idx}
                              onClick={() => setDraftBotAvatar(preset.id)}
                              className={`w-10 h-10 rounded-full border-2 cursor-pointer flex items-center justify-center bg-white dark:bg-slate-950 transition-all ${draftBotAvatar === preset.id
                                ? "border-[#0fb5a1] ring-2 ring-[#0fb5a1]/20 scale-105"
                                : "border-slate-200 dark:border-slate-800 hover:border-slate-300"
                                }`}
                            >
                              {preset.icon}
                            </div>
                          ))}

                          <label className="w-10 h-10 rounded-full border-2 border-dashed border-slate-300 dark:border-slate-700 hover:border-[#0fb5a1] cursor-pointer flex items-center justify-center text-slate-400 hover:text-[#0fb5a1] transition-all bg-white dark:bg-slate-950">
                            {uploadingBotAvatar ? <Spin size="small" /> : <PlusOutlined className="text-sm" />}
                            <input
                              type="file"
                              accept="image/*"
                              className="hidden"
                              onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) handleFileUpload(file, "botAvatar");
                              }}
                            />
                          </label>
                        </div>
                        <p className="text-[10px] text-slate-400 mt-1.5 mb-0">Recommended size: 128 × 128 px square image (PNG, JPG, max 2MB)</p>
                      </div>

                      <label className="text-xs font-bold uppercase tracking-wider text-slate-400 block pt-1">
                        Interface Layout & Theme Color
                      </label>

                      <div className="grid grid-cols-2 gap-3">
                        <div
                          onClick={() => setDraftChatType("icon")}
                          className={`p-3 rounded-2xl border-2 cursor-pointer transition-all duration-200 flex flex-col items-center text-center gap-1.5 bg-white dark:bg-slate-950 ${draftChatType === "icon"
                            ? "border-[#0fb5a1] bg-[#0fb5a1]/5 ring-2 ring-[#0fb5a1]/10"
                            : "border-slate-200 dark:border-slate-800 hover:border-slate-300"
                            }`}
                        >
                          <div
                            className="w-8 h-8 rounded-full flex items-center justify-center transition-colors"
                            style={{ background: `${draftThemeColor}15`, color: draftThemeColor }}
                          >
                            <MessageOutlined />
                          </div>
                          <div>
                            <div className="font-bold text-xs text-slate-800 dark:text-slate-200">Icon Bubble</div>
                            <div className="text-[9px] text-slate-400 mt-0.5 leading-tight">Floating corner button</div>
                          </div>
                        </div>

                        <div
                          onClick={() => setDraftChatType("search")}
                          className={`p-3 rounded-2xl border-2 cursor-pointer transition-all duration-200 flex flex-col items-center text-center gap-1.5 bg-white dark:bg-slate-950 ${draftChatType === "search"
                            ? "border-[#0fb5a1] bg-[#0fb5a1]/5 ring-2 ring-[#0fb5a1]/10"
                            : "border-slate-200 dark:border-slate-800 hover:border-slate-300"
                            }`}
                        >
                          <div
                            className="w-8 h-8 rounded-full flex items-center justify-center transition-colors"
                            style={{ background: `${draftThemeColor}15`, color: draftThemeColor }}
                          >
                            <EyeOutlined />
                          </div>
                          <div>
                            <div className="font-bold text-xs text-slate-800 dark:text-slate-200">Search Bar</div>
                            <div className="text-[9px] text-slate-400 mt-0.5 leading-tight">Search field layout</div>
                          </div>
                        </div>
                      </div>

                      {draftChatType === "search" && (
                        <div className="space-y-3 pt-2">
                          <div className="space-y-1">
                            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                              Alignment Position
                            </label>
                            <Radio.Group value={draftPosition} onChange={(e) => setDraftPosition(e.target.value)} size="small">
                              <Radio.Button value="center" className="!rounded-l-lg">Center Bottom</Radio.Button>
                              <Radio.Button value="right" className="!rounded-r-lg">Right Bottom</Radio.Button>
                            </Radio.Group>
                          </div>
                          <div className="space-y-1">
                            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                              Input Placeholder Text
                            </label>
                            <Input
                              value={draftPlaceholderText}
                              onChange={(e) => setDraftPlaceholderText(e.target.value)}
                              placeholder="Customize search bar placeholder..."
                              className="rounded-lg h-9 text-xs border-slate-300 dark:border-slate-700 dark:bg-slate-950 focus:border-[#0fb5a1]"
                            />
                          </div>
                        </div>
                      )}

                      <div className="space-y-2 pt-1">
                        <label className="text-xs font-bold uppercase tracking-wider text-slate-400 block">
                          Select Theme Color
                        </label>
                        <div className="flex items-center gap-2.5">
                          {COLOR_PRESETS.map((color) => (
                            <button
                              key={color.hex}
                              onClick={() => setDraftThemeColor(color.hex)}
                              style={{ background: color.hex }}
                              className={`w-7 h-7 rounded-full border-2 transition-transform duration-200 active:scale-90 relative cursor-pointer ${draftThemeColor.toLowerCase() === color.hex.toLowerCase()
                                ? "border-slate-800 scale-110 shadow-md"
                                : "border-transparent hover:scale-105"
                                }`}
                              title={color.name}
                            >
                              {draftThemeColor.toLowerCase() === color.hex.toLowerCase() && (
                                <span className="absolute inset-0 flex items-center justify-center text-white text-[10px]">
                                  ✓
                                </span>
                              )}
                            </button>
                          ))}
                          <div className="flex items-center gap-1.5 border border-slate-200 dark:border-slate-800 rounded-lg p-1 bg-white dark:bg-slate-950 ml-1">
                            <input
                              type="color"
                              value={draftThemeColor}
                              onChange={(e) => setDraftThemeColor(e.target.value)}
                              className="w-6 h-6 rounded-md border-0 cursor-pointer p-0 bg-transparent shrink-0 outline-none"
                              title="Custom hex color"
                            />
                            <span className="text-[10px] font-mono text-slate-500 font-bold select-all uppercase">
                              {draftThemeColor}
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ),
                },
              ]}
            />
          </div>


          {/* Modal Right Column: Live Web Sandbox Preview (span 6) */}
          <div className="lg:col-span-6 flex flex-col gap-3">
            <div className="flex justify-between items-center px-1">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <EyeOutlined /> Live Sandbox Preview
              </span>
              <span className="px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-emerald-500 bg-emerald-500/10 rounded-full">
                Interactive
              </span>
            </div>

            {/* Sandbox Browser frame mockup */}
            <div
              style={{
                backgroundColor: isDarkTheme ? "#0f172a" : "#ffffff",
                borderColor: isDarkTheme ? "#1e293b" : "#e2e8f0",
              }}
              className="border rounded-2xl overflow-hidden shadow-xl w-full flex-1 flex flex-col relative min-h-[520px] h-[520px]"
            >
              {/* Browser bar */}
              <div
                style={{
                  backgroundColor: isDarkTheme ? "#0b0f19" : "#f1f5f9",
                  borderBottomColor: isDarkTheme ? "#1e293b" : "#cbd5e1",
                }}
                className="flex items-center justify-between px-3 py-2 border-b"
              >
                <div className="flex gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-red-500/60" />
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-500/60" />
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/60" />
                </div>
                <div
                  style={{
                    backgroundColor: isDarkTheme ? "#090d16" : "#ffffff",
                    borderColor: isDarkTheme ? "#1e293b" : "#e2e8f0",
                    color: isDarkTheme ? "#94a3b8" : "#64748b",
                  }}
                  className="border rounded-md px-3 py-0.5 text-[10px] font-mono w-2/5 text-center truncate"
                >
                  https://your-website.com
                </div>
                <div className="w-10" />
              </div>

              {/* Website canvas */}
              <div
                style={{
                  background: isDarkTheme
                    ? "linear-gradient(135deg, #090d16 0%, #0f172a 50%, #1e1b4b 100%)"
                    : "linear-gradient(135deg, #f8fafc 0%, #f1f5f9 50%, #e2e8f0 100%)",
                }}
                className="flex-1 flex flex-col items-center justify-center p-6 text-center relative select-none overflow-hidden"
              >
                <div
                  style={{ backgroundColor: isDarkTheme ? "rgba(99, 102, 241, 0.1)" : "rgba(59, 130, 246, 0.05)" }}
                  className="absolute top-1/4 left-1/4 w-32 h-32 rounded-full blur-[60px]"
                />
                <div
                  style={{ backgroundColor: isDarkTheme ? "rgba(15, 181, 161, 0.1)" : "rgba(15, 181, 161, 0.05)" }}
                  className="absolute bottom-1/4 right-1/4 w-32 h-32 rounded-full blur-[60px]"
                />

                <div className="space-y-3 max-w-sm relative z-10 p-3">
                  <h4
                    style={{ color: isDarkTheme ? "#ffffff" : "#1e293b" }}
                    className="m-0 font-extrabold text-xl tracking-tight leading-tight"
                  >
                    Welcome to Your Website
                  </h4>
                  <p
                    style={{ color: isDarkTheme ? "#94a3b8" : "#64748b" }}
                    className="m-0 text-xs leading-relaxed font-light"
                  >
                    Observe logo header styles, bot identity avatar, entry button icons & text dynamically updated live.
                  </p>
                </div>

                {/* FLOATING ENTRY BUTTON PREVIEW */}
                {draftChatType === "icon" && (
                  <div
                    onClick={() => setPreviewIsOpen(!previewIsOpen)}
                    style={{
                      background: draftThemeColor,
                      color: "#ffffff",
                    }}
                    className={`absolute bottom-5 z-30 px-3.5 py-2.5 rounded-full shadow-xl flex items-center gap-2 cursor-pointer hover:scale-105 transition-all duration-200 animate-bounce [animation-duration:3s] ${draftButtonAlignment === "left" ? "left-5" : "right-5"
                      }`}
                  >
                    {/* Render Selected Button Icon */}
                    {draftButtonIcon.startsWith("http") || draftButtonIcon.startsWith("blob:") || draftButtonIcon.startsWith("data:") ? (
                      <img src={draftButtonIcon} alt="Icon" className="w-5 h-5 rounded-full object-contain" />
                    ) : draftButtonIcon === "robot" ? (
                      <RobotOutlined className="text-lg text-white" />
                    ) : draftButtonIcon === "setting" ? (
                      <SettingOutlined className="text-lg text-white" />
                    ) : draftButtonIcon === "question" ? (
                      <QuestionCircleOutlined className="text-lg text-white" />
                    ) : draftButtonIcon === "book" ? (
                      <BookOutlined className="text-lg text-white" />
                    ) : draftButtonIcon === "chat2" ? (
                      <CommentOutlined className="text-lg text-white" />
                    ) : (
                      <MessageOutlined className="text-lg text-white" />
                    )}

                    {/* Show Button Text if enabled */}
                    {draftShowButtonText && (
                      <span className="text-xs font-bold pr-0.5 select-none">{draftButtonText || "Help"}</span>
                    )}
                  </div>
                )}

                {/* SEARCH BAR PREVIEW */}
                {draftChatType === "search" && !previewIsOpen && (
                  <div
                    className={`absolute z-30 w-[90%] bottom-5 ${draftPosition === "center" ? "left-1/2 -translate-x-1/2" : "right-5"
                      }`}
                    style={{ maxWidth: draftPosition === "center" ? "90%" : "340px" }}
                  >
                    <div
                      className="p-[1.5px] rounded-[24px] transition-all duration-300 shadow-md sandbox-glow-container"
                      style={{ background: isDarkTheme ? "#334155" : "#cbd5e1" }}
                    >
                      <div
                        style={{
                          backgroundColor: isDarkTheme ? "#090d16" : "#ffffff",
                          borderColor: isDarkTheme ? "#1e293b" : "#e2e8f0",
                        }}
                        className="flex items-center border rounded-[22.5px] px-3.5 py-1.5 gap-2 w-full"
                      >
                        <input
                          type="text"
                          value={previewInput}
                          onChange={(e) => setPreviewInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handlePreviewSend(previewInput);
                          }}
                          placeholder={draftPlaceholderText}
                          style={{
                            backgroundColor: "transparent",
                            color: isDarkTheme ? "#ffffff" : "#1e293b",
                            border: "none",
                            outline: "none",
                            flex: 1,
                            fontSize: "11px",
                            paddingTop: "4px",
                            paddingBottom: "4px",
                          }}
                        />
                        <button
                          onClick={() => handlePreviewSend(previewInput)}
                          disabled={!previewInput.trim()}
                          style={{
                            background: previewInput.trim() ? draftThemeColor : isDarkTheme ? "#1e293b" : "#f1f5f9",
                            color: previewInput.trim() ? "#ffffff" : isDarkTheme ? "#475569" : "#94a3b8",
                          }}
                          className="w-6 h-6 rounded-full flex items-center justify-center border-none transition-all duration-200 cursor-pointer"
                        >
                          ↑
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* CHAT MODAL OVERLAY PREVIEW */}
                {previewIsOpen && (
                  <div
                    style={{
                      backgroundColor: isDarkTheme ? "#0f172a" : "#ffffff",
                      borderColor: isDarkTheme ? "#1e293b" : "#e2e8f0",
                    }}
                    className={`absolute rounded-2xl shadow-2xl flex flex-col border z-40 transition-all duration-300 h-[360px] bottom-[84px] ${isWideLayout
                      ? "w-[90%] left-1/2 -translate-x-1/2"
                      : "w-[90%] max-w-[340px] " +
                      (draftChatType === "icon" && draftButtonAlignment === "left"
                        ? "left-5"
                        : "right-5")
                      }`}
                  >
                    {/* Header with Custom Header Logo & Alignment */}
                    <div
                      style={{
                        backgroundColor: isDarkTheme ? "#1e293b" : "#f8fafc",
                        borderBottom: isDarkTheme ? "1px solid #334155" : "1px solid #e2e8f0",
                      }}
                      className={`flex items-center justify-between px-3.5 py-2.5 rounded-t-2xl ${draftHeaderAlignment === "center" ? "text-center" : "text-left"
                        }`}
                    >
                      <div className={`flex items-center gap-2 w-full ${draftHeaderAlignment === "center" ? "justify-center" : "justify-start"}`}>
                        {draftHeaderLogo && (
                          <div className="h-6 max-w-[100px] flex items-center">
                            {draftHeaderLogo.startsWith("http") || draftHeaderLogo.startsWith("blob:") || draftHeaderLogo.startsWith("data:") ? (
                              <img src={draftHeaderLogo} alt="Header Logo" className="max-h-full max-w-full object-contain" />
                            ) : (
                              <span className="text-xs font-extrabold text-[#0fb5a1]">{draftHeaderLogo}</span>
                            )}
                          </div>
                        )}
                        <div>
                          <div
                            style={{ color: isDarkTheme ? "#ffffff" : "#1e293b" }}
                            className="text-xs font-bold flex items-center gap-1 leading-none"
                          >
                            {agent?.name || "Gsearch AI"}
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                          </div>
                        </div>
                      </div>

                      {/* Escalation button in Header if enabled and lead form is NOT active */}
                      {draftEscalationEnabled && (!draftLeadCollection || previewLeadFormSubmitted) && (
                        <div className="mr-1 shrink-0 text-slate-400">
                          <EscalationHeaderLink
                            escalationLink={draftEscalationLink}
                            themeColor={draftThemeColor}
                            isDark={isDarkTheme}
                          />
                        </div>
                      )}

                      <button
                        onClick={() => setPreviewIsOpen(false)}
                        className="border-none bg-transparent text-slate-400 hover:text-slate-700 cursor-pointer text-sm font-semibold ml-2"
                      >
                        ✕
                      </button>
                    </div>

                    {draftLeadCollection && !previewLeadFormSubmitted ? (
                      <LeadCaptureForm
                        fields={draftLeadFields}
                        themeColor={draftThemeColor}
                        isDark={isDarkTheme}
                        onSubmit={(data) => {
                          console.log("Simulated Lead Form Submission:", data);
                          setPreviewLeadFormSubmitted(true);
                        }}
                      />
                    ) : (
                      <>
                        {/* Chat Feed with Bot Avatar */}
                        <div
                          id="embed-sandbox-chat-messages"
                          style={{ backgroundColor: isDarkTheme ? "#090d16" : "#f1f5f9" }}
                          className="flex-1 overflow-y-auto p-3.5 flex flex-col gap-2.5 text-left"
                        >
                          {(() => {
                            const messagesToRender = previewMessages.length > 0
                              ? previewMessages
                              : (draftInitialMessage ? [{ role: "assistant", content: draftInitialMessage }] : []);

                            if (messagesToRender.length === 0) {
                              return (
                                <div className="flex flex-col items-center justify-center text-center h-full text-slate-400 p-4">
                                  <MessageOutlined className="text-2xl mb-1.5 opacity-50" />
                                  <span className="text-[10px]">No messages yet. Send a query to test!</span>
                                </div>
                              );
                            }

                            return (
                              <>
                                {messagesToRender.map((msg: any, index: number) => {
                                  const isUser = msg.role === "user";
                                  return (
                                    <div key={index} className={`flex items-start gap-2 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
                                      {/* Bot Avatar preview */}
                                      {!isUser && draftBotAvatar !== "none" && (
                                        <div
                                          className="w-6 h-6 rounded-full flex items-center justify-center overflow-hidden shrink-0 mt-1"
                                          style={{ background: draftThemeColor }}
                                        >
                                          {draftBotAvatar.startsWith("http") || draftBotAvatar.startsWith("blob:") || draftBotAvatar.startsWith("data:") ? (
                                            <img src={draftBotAvatar} alt="Bot" className="w-full h-full object-cover" />
                                          ) : draftBotAvatar === "robot" ? (
                                            <RobotOutlined className="text-xs text-white" />
                                          ) : draftBotAvatar === "setting" ? (
                                            <SettingOutlined className="text-xs text-white" />
                                          ) : draftBotAvatar === "info" ? (
                                            <InfoCircleOutlined className="text-xs text-white" />
                                          ) : draftBotAvatar === "book" ? (
                                            <BookOutlined className="text-xs text-white" />
                                          ) : (
                                            <MessageOutlined className="text-xs text-white" />
                                          )}
                                        </div>
                                      )}
                                      <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
                                        <span className="text-[8px] text-slate-400 mb-0.5">{isUser ? "You" : agent?.name || "Agent"}</span>
                                        <div
                                          style={{
                                            background: isUser
                                              ? isDarkTheme ? "#1e293b" : "#f1f5f9"
                                              : isDarkTheme ? "#0f172a" : "#ffffff",
                                            borderColor: isUser
                                              ? isDarkTheme ? "#334155" : "#e2e8f0"
                                              : isDarkTheme ? "#1e293b" : "#f1f5f9",
                                            color: isDarkTheme ? "#ffffff" : "#1e293b",
                                          }}
                                          className="px-2.5 py-1.5 rounded-2xl text-[11px] max-w-[85%] border shadow-sm leading-normal relative group"
                                        >
                                          {msg.content}
                                        </div>

                                        {!isUser && (draftDisplayCopyBtn || draftDisplayFeedback || draftDisplaySources) && (
                                          <div className="flex items-center gap-2 mt-1 ml-1 text-slate-400 w-full">
                                            {draftDisplayCopyBtn && (
                                              <Tooltip title="Copy Answer">
                                                <CopyOutlined
                                                  onClick={() => {
                                                    navigator.clipboard?.writeText(msg.content);
                                                    notification.success({ message: "Copied answer to clipboard", placement: "topRight" });
                                                  }}
                                                  className="text-xs text-slate-400 hover:text-[#0fb5a1] cursor-pointer"
                                                />
                                              </Tooltip>
                                            )}
                                            {draftDisplayFeedback && (
                                              <>
                                                <Tooltip title="Helpful">
                                                  <LikeOutlined className="text-xs text-slate-400 hover:text-emerald-500 cursor-pointer" />
                                                </Tooltip>
                                                <Tooltip title="Not helpful">
                                                  <DislikeOutlined className="text-xs text-slate-400 hover:text-rose-500 cursor-pointer" />
                                                </Tooltip>
                                              </>
                                            )}
                                            {draftDisplaySources && (
                                              <div className="text-[11px] text-[#0066cc] font-bold flex items-center gap-1 cursor-pointer ml-25">
                                                <SiCrowdsource className="text-slate-800 text-[13px]" />
                                                <span>Source</span>
                                              </div>
                                            )}
                                          </div>
                                        )}
                                      </div>
                                    </div>
                                  );
                                })}

                                {draftEscalationEnabled && (
                                  <div className="mt-2 w-full">
                                    <EscalationSystemMessage
                                      escalationLink={draftEscalationLink}
                                      themeColor={draftThemeColor}
                                      isDark={isDarkTheme}
                                    />
                                  </div>
                                )}
                              </>
                            );
                          })()}
                          {previewIsTyping && (
                            <div className="flex items-center gap-1.5 animate-fade-in">
                              <span className="text-[8px] text-slate-400">Agent typing...</span>
                              <div className="px-2 py-1 rounded-xl bg-white border border-slate-100 shadow-sm flex items-center gap-1">
                                <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce" />
                                <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce [animation-delay:0.2s]" />
                                <span className="w-1 h-1 rounded-full bg-slate-400 animate-bounce [animation-delay:0.4s]" />
                              </div>
                            </div>
                          )}
                          <div ref={messagesEndRef} />
                        </div>

                        {/* Chat Input Bar */}
                        <div
                          className="p-2.5 border-t rounded-b-2xl"
                          style={{
                            backgroundColor: isDarkTheme ? "#0f172a" : "#ffffff",
                            borderTopColor: isDarkTheme ? "#1e293b" : "#f1f5f9",
                          }}
                        >
                          <div
                            className="flex items-center border rounded-full px-2.5 py-1 gap-1.5"
                            style={{
                              backgroundColor: isDarkTheme ? "#090d16" : "#f8fafc",
                              borderColor: isDarkTheme ? "#1e293b" : "#e2e8f0",
                            }}
                          >
                            <input
                              type="text"
                              value={previewInput}
                              onChange={(e) => setPreviewInput(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") handlePreviewSend(previewInput);
                              }}
                              placeholder={draftChatType === "search" ? "Ask a follow up..." : "Type your message..."}
                              style={{
                                backgroundColor: "transparent",
                                color: isDarkTheme ? "#ffffff" : "#1e293b",
                                border: "none",
                                outline: "none",
                                flex: 1,
                                fontSize: "11px",
                              }}
                            />
                            <button
                              onClick={() => handlePreviewSend(previewInput)}
                              disabled={!previewInput.trim()}
                              style={{
                                background: previewInput.trim() ? draftThemeColor : "#e2e8f0",
                                color: previewInput.trim() ? "#ffffff" : "#94a3b8",
                              }}
                              className="w-5 h-5 rounded-full flex items-center justify-center border-none cursor-pointer text-xs transition-colors duration-200"
                            >
                              ↑
                            </button>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </Modal>

      <style jsx global>{`
        @keyframes borderShift {
          0% { background-position: 0% 50%; }
          100% { background-position: 100% 50%; }
        }
        .sandbox-glow-container {
          transition: background 0.3s ease, box-shadow 0.3s ease;
        }
        .sandbox-glow-container:hover, .sandbox-glow-container.active-focus {
          background: linear-gradient(90deg, ${draftThemeColor}, #ff8c00, #ff0080, ${draftThemeColor}) !important;
          background-size: 300% 100% !important;
          animation: borderShift 4s linear infinite !important;
          box-shadow: 0 4px 20px ${draftThemeColor}50 !important;
        }
        .custom-widget-modal .ant-modal-content {
          border-radius: 28px !important;
          padding: 24px 32px !important;
          box-shadow: 0 24px 50px rgba(0,0,0,0.2) !important;
          background: #ffffff !important;
        }
        .dark .custom-widget-modal .ant-modal-content {
          background: #151b26 !important;
          border: 1px solid #1f293d !important;
        }
        .custom-widget-modal .ant-modal-header {
          background: transparent !important;
          border-bottom: none !important;
          margin-bottom: 0 !important;
        }
        .custom-widget-modal .ant-modal-title {
          background: transparent !important;
        }
        .custom-widget-modal .ant-modal-close:hover {
          color: #64748b !important;
        }
        .custom-widget-tabs .ant-tabs-nav {
          margin-bottom: 12px !important;
        }
        .custom-widget-tabs .ant-tabs-tab {
          border-radius: 12px !important;
          border: 1px solid #e2e8f0 !important;
          background: #f8fafc !important;
          padding: 6px 12px !important;
          transition: all 0.2s ease !important;
        }
        .dark .custom-widget-tabs .ant-tabs-tab {
          border: 1px solid #1e293b !important;
          background: #0f172a !important;
        }
        .custom-widget-tabs .ant-tabs-tab-active {
          border-color: #0fb5a1 !important;
          background: #0fb5a1 !important;
        }
        .custom-widget-tabs .ant-tabs-nav::before {
            border-bottom: none;
          }
        .custom-widget-tabs .ant-tabs-tab-active .ant-tabs-tab-btn {
          color: #ffffff !important;
        }
      `}</style>
    </Flex>
  );
}
