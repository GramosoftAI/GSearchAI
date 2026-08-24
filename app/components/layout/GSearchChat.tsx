"use client";

import { usePathname } from "next/navigation";
import Script from "next/script";

export default function GSearchChat() {
  const pathname = usePathname();

  // Do not load the chat widget on the widget page itself, or on the dashboard
  if (pathname?.startsWith("/widget")) {
    return null;
  }

  return (
    <Script
      src="https://gsearchai.com/chat.js"
      strategy="afterInteractive"
      data-agent-id="7c3035aa-bfdf-4ca8-befb-284e9b1eb333"
      data-tenant-id="31d899ec-b896-46d5-b963-0d5b62d4cca2"
      data-chat-type="icon"
      data-theme-color="#0fb5a1"
      data-theme-text-color="#000000"
      data-btn-bg-color="#0fb5a1"
      data-btn-border-color="#0fb5a1"
      data-header-logo="https://gsearchai.com/api/v1/embed/logo/render/31d899ec-b896-46d5-b963-0d5b62d4cca2/logo_5ab7fb3c.png"
      data-header-align="center"
      data-header-name="GSearch Catalyst"
      data-agent-label="GSearch Catalyst"
      data-bot-avatar="chat"
      data-button-icon="chat"
      data-button-align="right"
      data-show-button-text="true"
      data-button-text="AskMe"
      data-initial-message="Hi there! I'm your GSearchAI Assistant. I can walk you through what GSearchAI does, how it works, or help you get started. What would you like to know?"
      data-display-sources="false"
      data-allow-downloads="false"
      data-display-copy="false"
      data-display-feedback="true"
      data-link-safety="false"
      data-lead-collection="false"
      data-lead-fields='["name","email"]'
      data-lead-timing="pre-chat"
      data-escalation-enabled="false"
      data-escalation-link=""
      data-button-bottom="55px"
    />
  );
}
