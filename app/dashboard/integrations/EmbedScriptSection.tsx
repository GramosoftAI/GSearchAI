"use client";
import { Flex, Typography, Card, Button, Tooltip, App, Radio, Input, Modal, Switch, Spin, Tabs} from "antd";
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
  CustomerServiceOutlined,
} from "@ant-design/icons";
import { useState, useEffect, useRef, useCallback } from "react";
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

const COLOR_PRESETS = [
  { name: "Teal", hex: "#0fb5a1" },
  { name: "Blue", hex: "#0066cc" },
  { name: "Purple", hex: "#7f00ff" },
  { name: "Green", hex: "#22c55e" },
  { name: "Red", hex: "#ef4444" },
];

const LOGO_PRESET_DARK = "";
const LOGO_PRESET_LIGHT = "";
const LOGO_PRESET_MINI = "";

const AVATAR_PRESET_CHAT = "";
const AVATAR_PRESET_ROBOT = "";
const AVATAR_PRESET_SETTING = "";
const AVATAR_PRESET_INFO = "";
const AVATAR_PRESET_BOOK = "";
const AVATAR_PRESET_QUESTION = "";

const toProxyLogoUrl = (url: string): string => {
  if (!url) return url;
  const cleanUrl = url.split("?")[0];
  const s3Match = cleanUrl.match(/amazonaws\.com\/grag\/logos\/(.+)/);
  if (s3Match) {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "";
    return `${apiBase}/embed/logo/render/${s3Match[1]}`;
  }
  if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("blob:") || url.startsWith("data:")) {
    return url;
  }
  const proxyMatch = cleanUrl.match(/\/embed\/logo\/render\/(.+)/);
  if (proxyMatch) {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || "";
    return `${apiBase}/embed/logo/render/${proxyMatch[1]}`;
  }
  return url;
};

const CustomRobotIcon = ({ size = 18, color = "currentColor" }: { size?: number; color?: string }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ display: "block" }}>
    <rect x="3" y="11" width="18" height="10" rx="2" fill="none" />
    <circle cx="8.5" cy="15.5" r="1.5" fill={color} />
    <circle cx="15.5" cy="15.5" r="1.5" fill={color} />
    <path d="M12 2v6M9 5h6" />
  </svg>
);

export default function EmbedScriptSection() {
  const { notification } = App.useApp();
  const [copied, setCopied] = useState(false);
  const setAgentList = useStore((state) => state.setAgentList);
  const setBotsCache = useStore((state) => state.setBotsCache);
  const [agentresp, setAgentresponse] = useState<any>(null);
  const [agent, setAgent] = useState<{ id: string; name: string } | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [getAgents] = useAxios<AgentListResponse>({ endpoint: "GETAGENTLIST", hideErrorMsg: true });
  const [getWidgetConfig] = useAxios({ endpoint: "GET_WIDGET_CONFIG", hideErrorMsg: true });
  const [saveWidgetConfig] = useAxios({ endpoint: "SAVE_WIDGET_CONFIG", hideErrorMsg: false });
  const [expectedVersion, setExpectedVersion] = useState<number>(1);

  
  const [chatType, setChatType] = useState<"icon" | "search">("icon");
  const [position, setPosition] = useState<"center" | "right">("center");
  const [placeholderText, setPlaceholderText] = useState("Ask about web scraping, Zyte API, anything data extraction...");
  const [themeColor, setThemeColor] = useState("#0fb5a1");
  const [themeTextColor, setThemeTextColor] = useState<string>("#ffffff");
  const [btnBgColor, setBtnBgColor] = useState<string>("#0fb5a1");
  const [btnBorderColor, setBtnBorderColor] = useState<string>("#0fb5a1");

  
  const [headerLogo, setHeaderLogo] = useState<string>("/512_512.png");
  const [headerAlignment, setHeaderAlignment] = useState<"left" | "center">("center");
  const [headerName, setHeaderName] = useState<string>("Gsearch AI");
  const [headerSubtext, setHeaderSubtext] = useState<string>("The team can also help");

  
  const [botAvatar, setBotAvatar] = useState<string>("chat");
  const [agentLabel, setAgentLabel] = useState<string>("Agent");

  
  const [buttonIcon, setButtonIcon] = useState<string>("chat");
  const [buttonAlignment, setButtonAlignment] = useState<"left" | "right">("right");
  const [showButtonText, setShowButtonText] = useState<boolean>(true);
  const [buttonText, setButtonText] = useState<string>("Help");

  
  const [initialMessage, setInitialMessage] = useState<string>("Hi! I'm your AI Support Agent. How can I help you today?");
  const [displaySources, setDisplaySources] = useState<boolean>(true);
  const [allowDownloads, setAllowDownloads] = useState<boolean>(false);
  const [displayCopyBtn, setDisplayCopyBtn] = useState<boolean>(true);
  const [displayFeedback, setDisplayFeedback] = useState<boolean>(true);
  const [linkSafety, setLinkSafety] = useState<boolean>(true);

  
  const [leadCollection, setLeadCollection] = useState<boolean>(false);
  const [leadFields, setLeadFields] = useState<string>("name,email");
  const [leadTiming, setLeadTiming] = useState<string>("pre-chat");
  const [escalationEnabled, setEscalationEnabled] = useState<boolean>(false);
  const [escalationLink, setEscalationLink] = useState<string>("");

  const [draftLeadCollection, setDraftLeadCollection] = useState<boolean>(false);
  const [draftLeadFields, setDraftLeadFields] = useState<string>("name,email");
  const [draftLeadTiming, setDraftLeadTiming] = useState<string>("pre-chat");
  const [draftEscalationEnabled, setDraftEscalationEnabled] = useState<boolean>(false);
  const [draftEscalationLink, setDraftEscalationLink] = useState<string>("");

  const [isCustomizerOpen, setIsCustomizerOpen] = useState(false);
  const [draftChatType, setDraftChatType] = useState<"icon" | "search">("icon");
  const [draftPosition, setDraftPosition] = useState<"center" | "right">("center");
  const [draftPlaceholderText, setDraftPlaceholderText] = useState("Ask about web scraping, Zyte API, anything data extraction...");
  const [draftThemeColor, setDraftThemeColor] = useState("#0fb5a1");
  const [draftThemeTextColor, setDraftThemeTextColor] = useState<string>("#ffffff");
  const [draftBtnBgColor, setDraftBtnBgColor] = useState<string>("#0fb5a1");
  const [draftBtnBorderColor, setDraftBtnBorderColor] = useState<string>("#0fb5a1");

  const [draftHeaderLogo, setDraftHeaderLogo] = useState<string>(headerLogo);
  const [draftHeaderAlignment, setDraftHeaderAlignment] = useState<"left" | "center">(headerAlignment);
  const [draftHeaderName, setDraftHeaderName] = useState<string>("Gsearch AI");
  const [draftHeaderSubtext, setDraftHeaderSubtext] = useState<string>("The team can also help");
  const [draftBotAvatar, setDraftBotAvatar] = useState<string>("chat");
  const [draftAgentLabel, setDraftAgentLabel] = useState<string>("Agent");

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

  const [uploadingHeaderLogo, setUploadingHeaderLogo] = useState(false);
  const [uploadingBotAvatar, setUploadingBotAvatar] = useState(false);
  const [uploadingButtonIcon, setUploadingButtonIcon] = useState(false);

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

  const resetToDefaults = () => {
    setChatType("icon");
    setPosition("center");
    setPlaceholderText("Ask about web scraping, Zyte API, anything data extraction...");
    setThemeColor("#0fb5a1");
    setThemeTextColor("#ffffff");
    setBtnBgColor("#0fb5a1");
    setBtnBorderColor("#0fb5a1");
    setHeaderLogo("/512_512.png");
    setHeaderAlignment("center");
    setHeaderName("Gsearch AI");
    setHeaderSubtext("The team can also help");
    setBotAvatar("chat");
    setAgentLabel("Agent");
    setButtonIcon("chat");
    setButtonAlignment("right");
    setShowButtonText(true);
    setButtonText("Help");
    setInitialMessage("Hi! I'm your AI Support Agent. How can I help you today?");
    setDisplaySources(true);
    setAllowDownloads(false);
    setDisplayCopyBtn(true);
    setDisplayFeedback(true);
    setLinkSafety(true);
    setLeadCollection(false);
    setLeadFields("name,email");
    setLeadTiming("pre-chat");
    setEscalationEnabled(false);
    setEscalationLink("");
    setShowInHeader(true);
    setShowInChat(true);
    setShowInEmbed(false);

    // Drafts
    setDraftChatType("icon");
    setDraftPosition("center");
    setDraftPlaceholderText("Ask about web scraping, Zyte API, anything data extraction...");
    setDraftThemeColor("#0fb5a1");
    setDraftThemeTextColor("#ffffff");
    setDraftBtnBgColor("#0fb5a1");
    setDraftBtnBorderColor("#0fb5a1");
    setDraftHeaderLogo("/512_512.png");
    setDraftHeaderAlignment("center");
    setDraftHeaderName("Gsearch AI");
    setDraftHeaderSubtext("The team can also help");
    setDraftBotAvatar("chat");
    setDraftAgentLabel("Agent");
    setDraftButtonIcon("chat");
    setDraftButtonAlignment("right");
    setDraftShowButtonText(true);
    setDraftButtonText("Help");
    setDraftInitialMessage("Hi! I'm your AI Support Agent. How can I help you today?");
    setDraftDisplaySources(true);
    setDraftAllowDownloads(false);
    setDraftDisplayCopyBtn(true);
    setDraftDisplayFeedback(true);
    setDraftLinkSafety(true);
    setDraftLeadCollection(false);
    setDraftLeadFields("name,email");
    setDraftLeadTiming("pre-chat");
    setDraftEscalationEnabled(false);
    setDraftEscalationLink("");
    setDraftShowInHeader(true);
    setDraftShowInChat(true);
    setDraftShowInEmbed(false);
  };

  const fetchWidgetConfig = useCallback((agentId: string) => {
    getWidgetConfig({ path: `/${agentId}` }, (payload) => {
      if (payload?.success && payload?.data && payload?.data.exists) {
        const data = payload.data;
        setExpectedVersion(data.version || 1);

        if (data.theme_color) { setThemeColor(data.theme_color); setDraftThemeColor(data.theme_color); }
        if (data.theme_text_color) { setThemeTextColor(data.theme_text_color); setDraftThemeTextColor(data.theme_text_color); }
        if (data.btn_bg_color) { setBtnBgColor(data.btn_bg_color); setDraftBtnBgColor(data.btn_bg_color); }
        if (data.btn_border_color) { setBtnBorderColor(data.btn_border_color); setDraftBtnBorderColor(data.btn_border_color); }
        if (data.header_logo !== undefined && data.header_logo !== null) {
          setHeaderLogo(data.header_logo);
          setDraftHeaderLogo(data.header_logo);
        } else {
          setHeaderLogo("/512_512.png");
          setDraftHeaderLogo("/512_512.png");
        }
        if (data.header_align) { setHeaderAlignment(data.header_align); setDraftHeaderAlignment(data.header_align); }
        if (data.header_name) { setHeaderName(data.header_name); setDraftHeaderName(data.header_name); }
        if (data.header_subtext) { setHeaderSubtext(data.header_subtext); setDraftHeaderSubtext(data.header_subtext); }
        if (data.agent_label) { setAgentLabel(data.agent_label); setDraftAgentLabel(data.agent_label); }
        if (data.bot_avatar) { setBotAvatar(data.bot_avatar); setDraftBotAvatar(data.bot_avatar); }
        if (data.chat_type) { setChatType(data.chat_type); setDraftChatType(data.chat_type); }
        if (data.position) { setPosition(data.position); setDraftPosition(data.position); }
        if (data.placeholder_text) { setPlaceholderText(data.placeholder_text); setDraftPlaceholderText(data.placeholder_text); }
        if (data.button_icon) { setButtonIcon(data.button_icon); setDraftButtonIcon(data.button_icon); }
        if (data.button_align) { setButtonAlignment(data.button_align); setDraftButtonAlignment(data.button_align); }
        if (typeof data.show_button_text === "boolean") { setShowButtonText(data.show_button_text); setDraftShowButtonText(data.show_button_text); }
        if (data.button_text) { setButtonText(data.button_text); setDraftButtonText(data.button_text); }
        if (data.initial_message) { setInitialMessage(data.initial_message); setDraftInitialMessage(data.initial_message); }
        if (typeof data.display_sources === "boolean") { setDisplaySources(data.display_sources); setDraftDisplaySources(data.display_sources); }
        if (typeof data.allow_downloads === "boolean") { setAllowDownloads(data.allow_downloads); setDraftAllowDownloads(data.allow_downloads); }
        if (typeof data.display_copy === "boolean") { setDisplayCopyBtn(data.display_copy); setDraftDisplayCopyBtn(data.display_copy); }
        if (typeof data.display_feedback === "boolean") { setDisplayFeedback(data.display_feedback); setDraftDisplayFeedback(data.display_feedback); }
        if (typeof data.link_safety === "boolean") { setLinkSafety(data.link_safety); setDraftLinkSafety(data.link_safety); }
        if (typeof data.lead_collection === "boolean") { setLeadCollection(data.lead_collection); setDraftLeadCollection(data.lead_collection); }
        if (data.lead_fields) {
          const formattedFields = Array.isArray(data.lead_fields) ? data.lead_fields.join(",") : data.lead_fields;
          setLeadFields(formattedFields);
          setDraftLeadFields(formattedFields);
        }
        if (data.lead_timing) { setLeadTiming(data.lead_timing); setDraftLeadTiming(data.lead_timing); }
        if (typeof data.escalation_enabled === "boolean") { setEscalationEnabled(data.escalation_enabled); setDraftEscalationEnabled(data.escalation_enabled); }
        if (data.escalation_link) { setEscalationLink(data.escalation_link); setDraftEscalationLink(data.escalation_link); }
        if (typeof data.show_in_header === "boolean") { setShowInHeader(data.show_in_header); setDraftShowInHeader(data.show_in_header); }
        if (typeof data.show_in_chat === "boolean") { setShowInChat(data.show_in_chat); setDraftShowInChat(data.show_in_chat); }
        if (typeof data.show_in_embed === "boolean") { setShowInEmbed(data.show_in_embed); setDraftShowInEmbed(data.show_in_embed); }
      } else {
        resetToDefaults();
        setExpectedVersion(1);
      }
    });
  }, [getWidgetConfig]);

  useEffect(() => {
    if (agent?.id) {
      fetchWidgetConfig(agent.id);
    } else {
      resetToDefaults();
    }
  }, [agent?.id, fetchWidgetConfig]);

  const [previewMessages, setPreviewMessages] = useState<any[]>([]);
  const [previewInput, setPreviewInput] = useState("");
  const [previewIsTyping, setPreviewIsTyping] = useState(false);
  const [previewIsOpen, setPreviewIsOpen] = useState(true);
  const [previewLeadFormSubmitted, setPreviewLeadFormSubmitted] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const chatContainer = document.getElementById("embed-sandbox-chat-messages");
    if (chatContainer) {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }, [previewMessages, previewIsTyping, previewIsOpen]);

  const isWideLayout = draftChatType === "search" && draftPosition === "center";

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

  useEffect(() => {
    setPreviewMessages([]);
    setPreviewIsOpen(false);
    setPreviewIsTyping(false);
    setPreviewInput("");
  }, [draftChatType, draftPosition]);

  const openCustomizer = () => {
    if (!agent?.id) {
      notification.warning({
        message: "Select an Agent",
        description: "Please select an agent before customizing the widget.",
      });
      return;
    }
    setDraftChatType(chatType);
    setDraftPosition(position);
    setDraftPlaceholderText(placeholderText);
    setDraftThemeColor(themeColor);
    setDraftThemeTextColor(themeTextColor);
    setDraftBtnBgColor(btnBgColor);
    setDraftBtnBorderColor(btnBorderColor);
    setDraftHeaderLogo(headerLogo);
    setDraftHeaderAlignment(headerAlignment);
    setDraftHeaderName(headerName);
    setDraftHeaderSubtext(headerSubtext);
    setDraftBotAvatar(botAvatar);
    setDraftAgentLabel(agentLabel);
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

 
  const handleApply = async () => {
    if (!agent?.id) {
      notification.warning({
        message: "Select an Agent",
        description: "Please select an agent before applying widget configuration.",
      });
      return;
    }

    const leadFieldsArray = draftLeadFields.split(",").map(f => f.trim()).filter(Boolean);
    const savePayload = {
      agent_id: agent.id,
      expected_version: expectedVersion,
      change_reason: "Dashboard customizer apply",
      theme_color: draftThemeColor,
      theme_text_color: draftThemeTextColor,
      btn_bg_color: draftBtnBgColor,
      btn_border_color: draftBtnBorderColor,
      header_logo: draftHeaderLogo,
      header_align: draftHeaderAlignment,
      header_name: draftHeaderName,
      header_subtext: draftHeaderSubtext,
      agent_label: draftAgentLabel,
      bot_avatar: draftBotAvatar,
      chat_type: draftChatType,
      position: draftPosition,
      placeholder_text: draftPlaceholderText,
      button_icon: draftButtonIcon,
      button_align: draftButtonAlignment,
      show_button_text: draftShowButtonText,
      button_text: draftButtonText,
      initial_message: draftInitialMessage,
      display_sources: draftDisplaySources,
      allow_downloads: draftAllowDownloads,
      display_copy: draftDisplayCopyBtn,
      display_feedback: draftDisplayFeedback,
      link_safety: draftLinkSafety,
      lead_collection: draftLeadCollection,
      lead_fields: leadFieldsArray,
      lead_timing: draftLeadTiming,
      escalation_enabled: draftEscalationEnabled,
      escalation_link: draftEscalationLink,
      show_in_header: draftShowInHeader,
      show_in_chat: draftShowInChat,
      show_in_embed: draftShowInEmbed
    };

    saveWidgetConfig({ data: savePayload }, (responsePayload) => {
      if (responsePayload?.success) {
        setChatType(draftChatType);
        setPosition(draftPosition);
        setPlaceholderText(draftPlaceholderText);
        setThemeColor(draftThemeColor);
        setThemeTextColor(draftThemeTextColor);
        setBtnBgColor(draftBtnBgColor);
        setBtnBorderColor(draftBtnBorderColor);
        setHeaderLogo(draftHeaderLogo);
        setHeaderAlignment(draftHeaderAlignment);
        setHeaderName(draftHeaderName);
        setHeaderSubtext(draftHeaderSubtext);
        setBotAvatar(draftBotAvatar);
        setAgentLabel(draftAgentLabel);
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

        setIsCustomizerOpen(false);
        notification.success({
          message: "Widget Configuration Saved",
          description: "All style and branding attributes have been updated successfully.",
          placement: "topRight",
        });

        // Trigger GET API call to refresh settings
        fetchWidgetConfig(agent.id);
      }
    });
  };

  const handleCancel = () => {
    setDraftChatType(chatType);
    setDraftPosition(position);
    setDraftPlaceholderText(placeholderText);
    setDraftThemeColor(themeColor);
    setDraftThemeTextColor(themeTextColor);
    setDraftBtnBgColor(btnBgColor);
    setDraftBtnBorderColor(btnBorderColor);
    setDraftHeaderLogo(headerLogo);
    setDraftHeaderAlignment(headerAlignment);
    setDraftHeaderName(headerName);
    setDraftHeaderSubtext(headerSubtext);
    setDraftBotAvatar(botAvatar);
    setDraftAgentLabel(agentLabel);
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

  const scriptCode = `<script src='${process.env.NEXT_PUBLIC_API_BASES_URL || "http://grag.gramopro.ai"}/chat.js'
  data-agent-id="${agent?.id || "YOUR_AGENT_ID"}"
  data-tenant-id="${agentresp?.[0]?.tenant_id || "YOUR_TENANT_ID"}"
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

  
  const botAvatarPresets = [
    { id: "chat", icon: <MessageOutlined className="text-lg text-slate-500" /> },
    { id: "robot", icon: <CustomRobotIcon size={18} color="#64748b" /> },
    { id: "setting", icon: <SettingOutlined className="text-lg text-slate-500" /> },
    { id: "info", icon: <InfoCircleOutlined className="text-lg text-slate-500" /> },
    { id: "book", icon: <BookOutlined className="text-lg text-slate-500" /> },
  ];

  const buttonIconPresets = [
    { id: "chat", icon: <MessageOutlined className="text-lg text-slate-500" /> },
    { id: "robot", icon: <CustomRobotIcon size={18} color="#64748b" /> },
    { id: "setting", icon: <SettingOutlined className="text-lg text-slate-500" /> },
    { id: "question", icon: <QuestionCircleOutlined className="text-lg text-slate-500" /> },
    { id: "book", icon: <BookOutlined className="text-lg text-slate-500" /> },
  ];

  return (
    <Flex vertical gap={40}>
      
      <div className="space-y-3 max-w-3xl">
        <Title level={1} className="!m-0 !text-[var(--app-text)] !font-extrabold !text-3xl md:!text-5xl tracking-tight">
          Omnichannel Integrations
        </Title>
        <Text className="text-[var(--app-text-muted)] text-base md:text-lg block leading-relaxed">
          Deploy your cognitive AI agents across every customer touchpoint with seamless integration hooks.
        </Text>
      </div>

      
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
                {"\n"}
                <span className="text-[#0fb5a1] opacity-80">{">"}</span>
                <span className="text-[#0fb5a1] opacity-80">{"</script>"}</span>
              </code>
            </pre>
          </div>
        </Flex>
      </Card>

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
          
          <div className="lg:col-span-6 flex flex-col gap-4">
            <Tabs
              defaultActiveKey="header"
              type="card"
              className="custom-widget-tabs"
              items={[
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
                          Select Theme Color (Background)
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

                      <div className="space-y-2 pt-1">
                        <label className="text-xs font-bold uppercase tracking-wider text-slate-400 block">
                          Select Button Background Color (Inner Color)
                        </label>
                        <div className="flex items-center gap-2.5">
                          {COLOR_PRESETS.map((color) => (
                            <button
                              key={color.hex}
                              onClick={() => setDraftBtnBgColor(color.hex)}
                              style={{ background: color.hex }}
                              className={`w-7 h-7 rounded-full border-2 transition-transform duration-200 active:scale-90 relative cursor-pointer ${draftBtnBgColor.toLowerCase() === color.hex.toLowerCase()
                                ? "border-slate-800 scale-110 shadow-md"
                                : "border-transparent hover:scale-105"
                                }`}
                              title={color.name}
                            >
                              {draftBtnBgColor.toLowerCase() === color.hex.toLowerCase() && (
                                <span className="absolute inset-0 flex items-center justify-center text-white text-[10px]">
                                  ✓
                                </span>
                              )}
                            </button>
                          ))}
                          <div className="flex items-center gap-1.5 border border-slate-200 dark:border-slate-800 rounded-lg p-1 bg-white dark:bg-slate-950 ml-1">
                            <input
                              type="color"
                              value={draftBtnBgColor}
                              onChange={(e) => setDraftBtnBgColor(e.target.value)}
                              className="w-6 h-6 rounded-md border-0 cursor-pointer p-0 bg-transparent shrink-0 outline-none"
                              title="Custom hex color"
                            />
                            <span className="text-[10px] font-mono text-slate-500 font-bold select-all uppercase">
                              {draftBtnBgColor}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="space-y-2 pt-1">
                        <label className="text-xs font-bold uppercase tracking-wider text-slate-400 block">
                          Select Button Border Color (Outer Border Color)
                        </label>
                        <div className="flex items-center gap-2.5">
                          {COLOR_PRESETS.map((color) => (
                            <button
                              key={color.hex}
                              onClick={() => setDraftBtnBorderColor(color.hex)}
                              style={{ background: color.hex }}
                              className={`w-7 h-7 rounded-full border-2 transition-transform duration-200 active:scale-90 relative cursor-pointer ${draftBtnBorderColor.toLowerCase() === color.hex.toLowerCase()
                                ? "border-slate-800 scale-110 shadow-md"
                                : "border-transparent hover:scale-105"
                                }`}
                              title={color.name}
                            >
                              {draftBtnBorderColor.toLowerCase() === color.hex.toLowerCase() && (
                                <span className="absolute inset-0 flex items-center justify-center text-white text-[10px]">
                                  ✓
                                </span>
                              )}
                            </button>
                          ))}
                          <div className="flex items-center gap-1.5 border border-slate-200 dark:border-slate-800 rounded-lg p-1 bg-white dark:bg-slate-950 ml-1">
                            <input
                              type="color"
                              value={draftBtnBorderColor}
                              onChange={(e) => setDraftBtnBorderColor(e.target.value)}
                              className="w-6 h-6 rounded-md border-0 cursor-pointer p-0 bg-transparent shrink-0 outline-none"
                              title="Custom hex color"
                            />
                            <span className="text-[10px] font-mono text-slate-500 font-bold select-all uppercase">
                              {draftBtnBorderColor}
                            </span>
                          </div>
                          <Button
                            size="small"
                            type="dashed"
                            onClick={() => setDraftBtnBorderColor(draftBtnBgColor)}
                            className="text-[10px] h-8 rounded-lg !border-slate-300 hover:!border-[#0fb5a1] hover:!text-[#0fb5a1]"
                          >
                            Match Background
                          </Button>
                        </div>
                      </div>

                      <div className="space-y-2 pt-1">
                        <label className="text-xs font-bold uppercase tracking-wider text-slate-400 block">
                          Select Text & Icon Color
                        </label>
                        <div className="flex items-center gap-2.5">
                          {[
                            { name: "White", hex: "#ffffff" },
                            { name: "Black", hex: "#000000" }
                          ].map((color) => (
                            <button
                              key={color.hex}
                              onClick={() => setDraftThemeTextColor(color.hex)}
                              style={{ background: color.hex, border: "1px solid #cbd5e1" }}
                              className={`w-7 h-7 rounded-full border-2 transition-transform duration-200 active:scale-90 relative cursor-pointer ${draftThemeTextColor.toLowerCase() === color.hex.toLowerCase()
                                ? "border-slate-800 scale-110 shadow-md"
                                : "border-transparent hover:scale-105"
                                }`}
                              title={color.name}
                            >
                              {draftThemeTextColor.toLowerCase() === color.hex.toLowerCase() && (
                                <span className="absolute inset-0 flex items-center justify-center text-slate-800 text-[10px]">
                                  ✓
                                </span>
                              )}
                            </button>
                          ))}
                          <div className="flex items-center gap-1.5 border border-slate-200 dark:border-slate-800 rounded-lg p-1 bg-white dark:bg-slate-950 ml-1">
                            <input
                              type="color"
                              value={draftThemeTextColor}
                              onChange={(e) => setDraftThemeTextColor(e.target.value)}
                              className="w-6 h-6 rounded-md border-0 cursor-pointer p-0 bg-transparent shrink-0 outline-none"
                              title="Custom hex color"
                            />
                            <span className="text-[10px] font-mono text-slate-500 font-bold select-all uppercase">
                              {draftThemeTextColor}
                            </span>
                          </div>
                        </div>
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
                     
                      <div>
                        <label className="font-bold text-xs text-slate-800 dark:text-slate-200 block mb-0.5">
                          Agent Chat Label
                        </label>
                        <p className="text-[10px] text-slate-400 m-0 mb-1.5 leading-normal">
                          This label will appear above all responses sent by the agent in the chat feed.
                        </p>
                        <Input
                          value={draftAgentLabel}
                          onChange={(e) => setDraftAgentLabel(e.target.value)}
                          placeholder="Agent"
                          className="rounded-lg h-9 text-xs border-slate-300 dark:border-slate-700 dark:bg-slate-950 focus:border-[#0fb5a1]"
                        />
                      </div>

                      
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

                      
                      <div className="space-y-2 pt-1">
                        
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

                      
                      <div className="border-t border-slate-200 dark:border-slate-800 my-4" />

                     
                      <div className="space-y-3.5 pb-2">
                        {/* <div>
                          <h4 className="font-bold text-xs text-slate-800 dark:text-slate-200 m-0">Lead & Support Escalation</h4>
                          <p className="text-[10px] text-slate-400 m-0">Configure lead collection forms and support escalation links.</p>
                        </div> */}

                        {/* Lead Collection Toggle */}
                        {/* <div className="p-2.5 rounded-xl bg-white dark:bg-slate-950 border border-slate-200/80 dark:border-slate-800 flex items-center justify-between gap-3 shadow-xs">
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
                        </div> */}

                        {/* {draftLeadCollection && (
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
                        )} */}

                        
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
                                placeholder="e.g. https://example.ai/"
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

                     
                      <div>
                        <label className="text-xs font-semibold text-slate-500 block mb-1.5">Header Title</label>
                        <Input
                          value={draftHeaderName}
                          onChange={(e) => setDraftHeaderName(e.target.value)}
                          placeholder="Gsearch AI"
                          className="rounded-lg h-9 text-xs border-slate-300 dark:border-slate-700 dark:bg-slate-950 focus:border-[#0fb5a1]"
                        />
                      </div>

                      
                      <div>
                        <label className="text-xs font-semibold text-slate-500 block mb-1.5">Header Subtext</label>
                        <Input
                          value={draftHeaderSubtext}
                          onChange={(e) => setDraftHeaderSubtext(e.target.value)}
                          placeholder="The team can also help"
                          className="rounded-lg h-9 text-xs border-slate-300 dark:border-slate-700 dark:bg-slate-950 focus:border-[#0fb5a1]"
                        />
                      </div>

                      
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
                
                
              ]}
            />
          </div>


          
          <div className="lg:col-span-6 flex flex-col gap-3">
            <div className="flex justify-between items-center px-1">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <EyeOutlined /> Live Sandbox Preview
              </span>
              <span className="px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-emerald-500 bg-emerald-500/10 rounded-full">
                Interactive
              </span>
            </div>

            
            <div
              style={{
                backgroundColor: isDarkTheme ? "#0f172a" : "#ffffff",
                borderColor: isDarkTheme ? "#1e293b" : "#e2e8f0",
              }}
              className="border rounded-2xl overflow-hidden shadow-xl w-full flex-1 flex flex-col relative min-h-[520px] h-[520px]"
            >
              
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

                
                {draftChatType === "icon" && (
                  <div
                    onClick={() => setPreviewIsOpen(!previewIsOpen)}
                    style={{
                      background: draftBtnBgColor || draftThemeColor,
                      border: `2px solid ${draftBtnBorderColor || draftBtnBgColor || draftThemeColor}`,
                      color: draftThemeTextColor,
                    }}
                    className={`absolute bottom-5 z-30 px-3.5 py-2.5 rounded-full shadow-xl flex items-center gap-2 cursor-pointer hover:scale-105 transition-all duration-200 animate-bounce [animation-duration:3s] ${draftButtonAlignment === "left" ? "left-5" : "right-5"
                      }`}
                  >
                   
                    {draftButtonIcon.startsWith("http") || draftButtonIcon.startsWith("blob:") || draftButtonIcon.startsWith("data:") ? (
                      <img src={draftButtonIcon} alt="Icon" className="w-5 h-5 rounded-full object-contain" />
                    ) : draftButtonIcon === "robot" ? (
                      <CustomRobotIcon size={18} color={draftThemeTextColor} />
                    ) : draftButtonIcon === "setting" ? (
                      <SettingOutlined className="text-lg" style={{ color: draftThemeTextColor }} />
                    ) : draftButtonIcon === "question" ? (
                      <QuestionCircleOutlined className="text-lg" style={{ color: draftThemeTextColor }} />
                    ) : draftButtonIcon === "book" ? (
                      <BookOutlined className="text-lg" style={{ color: draftThemeTextColor }} />
                    ) : draftButtonIcon === "chat2" ? (
                      <CommentOutlined className="text-lg" style={{ color: draftThemeTextColor }} />
                    ) : (
                      <MessageOutlined className="text-lg" style={{ color: draftThemeTextColor }} />
                    )}

                   
                    {draftShowButtonText && (
                      <span className="text-xs font-bold pr-0.5 select-none" style={{ color: draftThemeTextColor }}>{draftButtonText || "Help"}</span>
                    )}
                  </div>
                )}

                
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
                            {draftHeaderLogo.startsWith("http") || draftHeaderLogo.startsWith("blob:") || draftHeaderLogo.startsWith("data:") || draftHeaderLogo.startsWith("/") ? (
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
                            {draftHeaderName !== undefined && draftHeaderName !== null ? draftHeaderName : (agent?.name || "Gsearch AI")}
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                          </div>
                        </div>
                      </div>

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
                                     
                                      {!isUser && draftBotAvatar !== "none" && (
                                        <div
                                          className="w-6 h-6 rounded-full flex items-center justify-center overflow-hidden shrink-0 mt-1"
                                          style={{ background: draftThemeColor }}
                                        >
                                          {draftBotAvatar.startsWith("http") || draftBotAvatar.startsWith("blob:") || draftBotAvatar.startsWith("data:") ? (
                                            <img src={draftBotAvatar} alt="Bot" className="w-full h-full object-cover" />
                                          ) : draftBotAvatar === "robot" ? (
                                            <CustomRobotIcon size={14} color="#fff" />
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
                                        <span className="text-[8px] text-slate-400 mb-0.5">{isUser ? "You" : draftAgentLabel !== undefined && draftAgentLabel !== null ? draftAgentLabel : (agent?.name || "Agent")}</span>
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
                                              <div className="text-[11px] text-[#000000] font-bold flex items-center gap-1 cursor-pointer ml-25">
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
