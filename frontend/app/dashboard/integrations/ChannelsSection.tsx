"use client";

import { useState, useEffect } from "react";
import { Card, Flex, Button, Typography, Modal, Spin } from "antd";
import Image from "next/image";
import { signIn, useSession } from "next-auth/react";
import { getCookie } from "../../config/cookies";
import GoogleDriveFolderModal from "./GoogleDriveFolderModal";
import SharePointFolderModal from "./SharePointFolderModal";
import IntegrationConnectModal from "./IntegrationConnectModal";
import { toast } from "react-hot-toast";

const { Title } = Typography;

export default function ChannelsSection() {
  const { data: session } = useSession() as any;
  const [googleModal, setGoogleModal] = useState(false);
  const [sharePointModal, setSharePointModal] = useState(false);
  
  // The selected agent's info when opening the folder/site selection modal
  const [agentkbres, setagentkbres] = useState("");
  const [selectedAgent, setSelectedAgent] = useState<{ id: string; name: string } | null>(null);

  // States to orchestrate the new IntegrationConnectModal
  const [connectModalType, setConnectModalType] = useState<"google" | "sharepoint" | "email" | "outlook" | null>(null);
  const [support, setSupport] = useState<string | null>(null);

  const [syncingGmail, setSyncingGmail] = useState(false);
  const [syncingOutlook, setSyncingOutlook] = useState(false);

  // OAuth Registration effects (running after NextAuth callback redirect)
  useEffect(() => {
    if (!session?.refreshToken) return;
    if (!agentkbres) return;

    const sendGoogleData = async () => {
      const token = getCookie("AUTH_TOKEN");
      const client = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
      const secret = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_SECRET;
      try {
        const response = await fetch(
          `${process.env.NEXT_PUBLIC_API_BASE_URL}/knowledge-bases/${agentkbres}/google-drive/register`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({
              credentials: {
                client_id: client,
                client_secret: secret,
                refresh_token: session?.refreshToken,
                token_uri: "https://oauth2.googleapis.com/token",
                primary_admin_email: session?.user?.email,
              },
              folder_urls: [],
            }),
          }
        );

        if (response.ok) {
          setGoogleModal(true);
          setSupport(null);
        }
      } catch (error) {
        console.error("Error registering Google Drive:", error);
      }
    };

    if (agentkbres && support === "google") {
      sendGoogleData();
    }
  }, [session, agentkbres, support]);

  useEffect(() => {
    if (!session?.refreshToken) return;
    if (!agentkbres) return;

    const registerSharePoint = async () => {
      const token = getCookie("AUTH_TOKEN");
      try {
        const response = await fetch(
          `${process.env.NEXT_PUBLIC_API_BASE_URL}/knowledge-bases/${agentkbres}/sharepoint/register`,
          {
            method: "POST",
            headers: {
              Authorization: `Bearer ${token}`,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              credentials: {
                client_id: process.env.NEXT_PUBLIC_MS_CLIENT_ID,
                client_secret: process.env.NEXT_PUBLIC_MS_CLIENT_SECRET,
                tenant_id: session.tenantId,
              },
              site_urls: ["https://graph.microsoft.com/v1.0/sites/root"],
            }),
          }
        );

        if (response.ok) {
          setSharePointModal(true);
          setSupport(null);
        }
      } catch (error) {
        console.error("Error registering SharePoint:", error);
      }
    };

    if (agentkbres && support === "share") {
      registerSharePoint();
    }
  }, [session, agentkbres, support]);

  // Gmail OAuth Registration & Auto-Sync Effect
  useEffect(() => {
    if (!session?.refreshToken) return;
    if (!agentkbres) return;
    if (support !== "email") return;

    const registerAndSyncGmail = async () => {
      setSyncingGmail(true);
      const token = getCookie("AUTH_TOKEN");
      const client = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
      const secret = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_SECRET;
      try {
        // 1. Register Gmail
        const registerResponse = await fetch(
          `${process.env.NEXT_PUBLIC_API_BASE_URL}/knowledge-bases/${agentkbres}/gmail/register`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({
              credentials: {
                client_id: client,
                client_secret: secret,
                refresh_token: session?.refreshToken,
                token_uri: "https://oauth2.googleapis.com/token",
                primary_admin_email: session?.user?.email,
              },
            }),
          }
        );

        if (!registerResponse.ok) {
          throw new Error("Gmail registration failed");
        }

        // 2. Sync Gmail
        const syncPayload = {
          folder_ids: ["INBOX", "SENT"],
          email: session?.user?.email,
        };

        const syncResponse = await fetch(
          `${process.env.NEXT_PUBLIC_API_BASE_URL}/knowledge-bases/${agentkbres}/gmail/sync`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify(syncPayload),
          }
        );

        if (!syncResponse.ok) {
          throw new Error("Gmail sync failed");
        }

        // Save connection state locally (fallback)
        const agentId = selectedAgent?.id || localStorage.getItem("selected_agent_id_temp") || agentkbres;
        const existing = localStorage.getItem(`mock_connections_${agentId}`);
        const list = existing ? JSON.parse(existing) : [];
        if (!list.includes("email")) {
          list.push("email");
          localStorage.setItem(`mock_connections_${agentId}`, JSON.stringify(list));
        }

        toast.success("Gmail synced successfully!");
        setSupport(null);
      } catch (error) {
        console.error("Error with Gmail integration:", error);
        toast.error("Failed to complete Gmail integration sync.");
      } finally {
        setSyncingGmail(false);
      }
    };

    registerAndSyncGmail();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, agentkbres, support]);

  // Outlook OAuth Registration & Auto-Sync Effect
  useEffect(() => {
    if (!session?.refreshToken) return;
    if (!agentkbres) return;
    if (support !== "outlook") return;

    const registerAndSyncOutlook = async () => {
      setSyncingOutlook(true);
      const token = getCookie("AUTH_TOKEN");
      const client = process.env.AZURE_AD_CLIENT_ID || process.env.NEXT_PUBLIC_MS_CLIENT_ID;
      const secret = process.env.AZURE_AD_CLIENT_SECRET || process.env.NEXT_PUBLIC_MS_CLIENT_SECRET;
      const tenant = session.tenantId || process.env.AZURE_AD_TENANT_ID || "common";
      try {
        // 1. Register Outlook
        const registerResponse = await fetch(
          `${process.env.NEXT_PUBLIC_API_BASE_URL}/knowledge-bases/${agentkbres}/outlook/register`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify({
              credentials: {
                client_id: client,
                client_secret: secret,
                refresh_token: session?.refreshToken,
                token_uri: "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                tenant_id: tenant,
                primary_admin_email: session?.user?.email,
              },
            }),
          }
        );

        if (!registerResponse.ok) {
          throw new Error("Outlook registration failed");
        }

        // 2. Sync Outlook
        const syncPayload = {
          folder_ids: ["Inbox", "Sent Items"],
          email: session?.user?.email,
        };

        const syncResponse = await fetch(
          `${process.env.NEXT_PUBLIC_API_BASE_URL}/knowledge-bases/${agentkbres}/outlook/sync`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${token}`,
            },
            body: JSON.stringify(syncPayload),
          }
        );

        if (!syncResponse.ok) {
          throw new Error("Outlook sync failed");
        }

        // Save connection state locally (fallback)
        const agentId = selectedAgent?.id || localStorage.getItem("selected_agent_id_temp") || agentkbres;
        const existing = localStorage.getItem(`mock_connections_${agentId}`);
        const list = existing ? JSON.parse(existing) : [];
        if (!list.includes("outlook")) {
          list.push("outlook");
          localStorage.setItem(`mock_connections_${agentId}`, JSON.stringify(list));
        }

        toast.success("Outlook synced successfully!");
        setSupport(null);
      } catch (error) {
        console.error("Error registering Outlook:", error);
        toast.error("Failed to register Outlook integration.");
      } finally {
        setSyncingOutlook(false);
      }
    };

    registerAndSyncOutlook();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, agentkbres, support]);

  // Load saved OAuth parameters from local storage after page redirect
  useEffect(() => {
    const savedKbId = localStorage.getItem("my_saved_kb_id");
    const openType = localStorage.getItem("files");
    if (!savedKbId) return;

    localStorage.removeItem("my_saved_kb_id");
    localStorage.removeItem("files");
    setagentkbres(savedKbId);
    setSupport(openType);
  }, []);

  // Modal event: when the user clicks "Connect" on an unsynced agent
  const handleConnectAgent = (agent: { id: string; name: string }, kbId: string) => {
    setSelectedAgent(agent);
    setagentkbres(kbId);
    localStorage.setItem("selected_agent_id_temp", agent.id);
    
    const currentType = connectModalType;
    setConnectModalType(null); // Close modal
    
    if (currentType === "email") {
      localStorage.setItem("my_saved_kb_id", kbId);
      localStorage.setItem("files", "email");
      signIn("google");
    } else if (currentType === "outlook") {
      localStorage.setItem("my_saved_kb_id", kbId);
      localStorage.setItem("files", "outlook");
      signIn("azure-ad");
    } else {
      const providerKey = 
        currentType === "google" ? "google_drive" : "sharepoint";
        
      const existing = localStorage.getItem(`mock_connections_${agent.id}`);
      const list = existing ? JSON.parse(existing) : [];
      if (!list.includes(providerKey)) {
        list.push(providerKey);
        localStorage.setItem(`mock_connections_${agent.id}`, JSON.stringify(list));
      }

      // Save to local storage for retrieval post-OAuth redirect
      localStorage.setItem("my_saved_kb_id", kbId);
      localStorage.setItem("files", currentType === "google" ? "google" : "share");
      
      // Trigger OAuth
      if (currentType === "google") {
        signIn("google");
      } else {
        signIn("azure-ad");
      }
    }
  };

  // Modal event: when the user clicks "Add" on an already synced agent
  const handleAddFolders = (agent: { id: string; name: string }, kbId: string) => {
    setSelectedAgent(agent);
    setagentkbres(kbId);
    localStorage.setItem("selected_agent_id_temp", agent.id);
    
    const type = connectModalType;
    setConnectModalType(null); // Close select modal

    if (type === "email") {
      if (session?.refreshToken) {
        setSupport("email");
      } else {
        localStorage.setItem("my_saved_kb_id", kbId);
        localStorage.setItem("files", "email");
        signIn("google");
      }
    } else if (type === "outlook") {
      if (session?.refreshToken) {
        setSupport("outlook");
      } else {
        localStorage.setItem("my_saved_kb_id", kbId);
        localStorage.setItem("files", "outlook");
        signIn("azure-ad");
      }
    } else {
      if (session?.refreshToken) {
        // Session is active, set support to trigger the registration useEffect
        setSupport(type === "google" ? "google" : "share");
      } else {
        // Session is not active, redirect to sign in to obtain credentials
        localStorage.setItem("my_saved_kb_id", kbId);
        localStorage.setItem("files", type === "google" ? "google" : "share");
        if (type === "google") {
          signIn("google");
        } else {
          signIn("azure-ad");
        }
      }
    }
  };

  return (
    <>
      <Flex vertical gap={16}>
        <Title level={5} className="!m-0 !text-[var(--app-text-soft)] !font-bold uppercase tracking-widest text-xs">
          Available Channels
        </Title>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Google Drive Card */}
          <Card
            hoverable
            className="group relative overflow-hidden bg-[var(--app-surface)] border border-[var(--app-border)] rounded-3xl transition-all duration-300 hover:shadow-xl hover:shadow-blue-900/5 hover:-translate-y-1"
            styles={{ body: { padding: "24px sm:32px" } }}
          >
            <div className="p-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Image
                  src="https://cdn-icons-png.flaticon.com/512/2991/2991148.png"
                  alt="Google Drive"
                  width={40}
                  height={40}
                />
                <div>
                  <h2 className="font-semibold text-[var(--app-text)]">Google Drive</h2>
                  <p className="text-sm text-gray-500">Files, photos, shared documents</p>
                </div>
              </div>
              
              <Button
                type="primary"
                onClick={() => setConnectModalType("google")}
                className="bg-purple-500 hover:bg-purple-600 border-none text-white px-6 py-2 rounded-xl h-11 font-semibold transition-transform active:scale-95"
              >
                Connect
              </Button>
            </div>
          </Card>

          {/* SharePoint Card */}
          <Card
            hoverable
            className="group relative overflow-hidden bg-[var(--app-surface)] border border-[var(--app-border)] rounded-3xl transition-all duration-300 hover:shadow-xl hover:shadow-blue-900/5 hover:-translate-y-1"
            styles={{ body: { padding: "24px sm:32px" } }}
          >
            <div className="p-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Image
                  src="https://img.icons8.com/color/96/microsoft-sharepoint-2019.png"
                  alt="SharePoint"
                  width={40}
                  height={40}
                />
                <div>
                  <h2 className="font-semibold text-[var(--app-text)]">SharePoint</h2>
                  <p className="text-sm text-gray-500">Files, photos, shared documents</p>
                </div>
              </div>

              <Button
                type="primary"
                onClick={() => setConnectModalType("sharepoint")}
                className="bg-purple-500 hover:bg-purple-600 border-none text-white px-6 py-2 rounded-xl h-11 font-semibold transition-transform active:scale-95"
              >
                Connect
              </Button>
            </div>
          </Card>

          {/* Email Card */}
          <Card
            hoverable
            className="group relative overflow-hidden bg-[var(--app-surface)] border border-[var(--app-border)] rounded-3xl transition-all duration-300 hover:shadow-xl hover:shadow-blue-900/5 hover:-translate-y-1"
            styles={{ body: { padding: "24px sm:32px" } }}
          >
            <div className="p-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Image
                  src="https://img.icons8.com/color/96/gmail-new.png"
                  alt="Gmail"
                  width={40}
                  height={40}
                />
                <div>
                  <h2 className="font-semibold text-[var(--app-text)]">Email Inbox</h2>
                  <p className="text-sm text-gray-500">SMTP, IMAP support mailboxes</p>
                </div>
              </div>

              <Button
                type="primary"
                onClick={() => setConnectModalType("email")}
                className="bg-purple-500 hover:bg-purple-600 border-none text-white px-6 py-2 rounded-xl h-11 font-semibold transition-transform active:scale-95"
              >
                Connect
              </Button>
            </div>
          </Card>

          {/* Outlook Card */}
          <Card
            hoverable
            className="group relative overflow-hidden bg-[var(--app-surface)] border border-[var(--app-border)] rounded-3xl transition-all duration-300 hover:shadow-xl hover:shadow-blue-900/5 hover:-translate-y-1"
            styles={{ body: { padding: "24px sm:32px" } }}
          >
            <div className="p-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Image
                  src="https://img.icons8.com/color/96/microsoft-outlook-2019--v2.png"
                  alt="Outlook"
                  width={40}
                  height={40}
                />
                <div>
                  <h2 className="font-semibold text-[var(--app-text)]">Microsoft Outlook</h2>
                  <p className="text-sm text-gray-500">Outlook email, contact folders</p>
                </div>
              </div>

              <Button
                type="primary"
                onClick={() => setConnectModalType("outlook")}
                className="bg-purple-500 hover:bg-purple-600 border-none text-white px-6 py-2 rounded-xl h-11 font-semibold transition-transform active:scale-95"
              >
                Connect
              </Button>
            </div>
          </Card>
        </div>
      </Flex>

      {/* Integration Synced Agent Selector Modal */}
      {connectModalType && (
        <IntegrationConnectModal
          open={connectModalType !== null}
          type={connectModalType}
          onClose={() => setConnectModalType(null)}
          onConnect={handleConnectAgent}
          onAdd={handleAddFolders}
        />
      )}

      {/* Folder selector modals */}
      <GoogleDriveFolderModal
        open={googleModal}
        kbId={agentkbres}
        token={getCookie("AUTH_TOKEN") || ""}
        onClose={() => setGoogleModal(false)}
        onSuccess={() => {
          setGoogleModal(false);
        }}
        session={session?.user?.email}
      />
      
      <SharePointFolderModal
        open={sharePointModal}
        kbId={agentkbres}
        token={getCookie("AUTH_TOKEN") || ""}
        onClose={() => setSharePointModal(false)}
        onSuccess={() => {
          setSharePointModal(false);
        }}
        session={session?.user?.email}
      />



      {/* Auto-Syncing Loader Modal */}
      <Modal
        open={syncingGmail || syncingOutlook}
        footer={null}
        closable={false}
        centered
        width={400}
        className="sync-loading-modal"
      >
        <div className="flex flex-col items-center justify-center p-8 text-center">
          <Spin size="large" className="mb-6" />
          <h3 className="text-lg font-bold text-[var(--app-text)] mb-2">
            Synchronizing with {syncingGmail ? "Gmail" : "Outlook"}
          </h3>
          <p className="text-xs text-[var(--app-text-muted)] max-w-xs m-0">
            Establishing secure connection and indexing folders (INBOX, SENT). This may take a few moments...
          </p>
        </div>
      </Modal>


    </>
  );
}
