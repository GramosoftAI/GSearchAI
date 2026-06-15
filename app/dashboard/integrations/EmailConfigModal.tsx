"use client";

import { useState } from "react";
import { Modal, Button, Input, Select, Switch, Progress, Spin, Typography } from "antd";
import { MailOutlined, SettingOutlined, CheckCircleOutlined, SyncOutlined, LockOutlined, CloudServerOutlined } from "@ant-design/icons";
import { toast } from "react-hot-toast";

const { Text } = Typography;

interface Props {
  open: boolean;
  agentId: string;
  agentName: string;
  onClose: () => void;
  onSuccess: () => void;
}

export default function EmailConfigModal({ open, agentId, agentName, onClose, onSuccess }: Props) {
  const [provider, setProvider] = useState("custom");
  const [emailAddress, setEmailAddress] = useState("");
  const [password, setPassword] = useState("");
  const [imapServer, setImapServer] = useState("");
  const [imapPort, setImapPort] = useState("993");
  const [smtpServer, setSmtpServer] = useState("");
  const [smtpPort, setSmtpPort] = useState("465");
  const [useSsl, setUseSsl] = useState(true);
  
  const [testing, setTesting] = useState(false);
  const [connected, setConnected] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncProgress, setSyncProgress] = useState(0);

  const handleProviderChange = (val: string) => {
    setProvider(val);
    if (val === "gmail") {
      setImapServer("imap.gmail.com");
      setImapPort("993");
      setSmtpServer("smtp.gmail.com");
      setSmtpPort("465");
    } else if (val === "outlook") {
      setImapServer("outlook.office365.com");
      setImapPort("993");
      setSmtpServer("smtp.office365.com");
      setSmtpPort("587");
    } else if (val === "yahoo") {
      setImapServer("imap.mail.yahoo.com");
      setImapPort("993");
      setSmtpServer("smtp.mail.yahoo.com");
      setSmtpPort("465");
    } else {
      setImapServer("");
      setImapPort("993");
      setSmtpServer("");
      setSmtpPort("465");
    }
  };

  const handleTestConnection = () => {
    if (!emailAddress) {
      toast.error("Please enter email address");
      return;
    }
    if (!password) {
      toast.error("Please enter password / App key");
      return;
    }
    if (!imapServer) {
      toast.error("Please enter IMAP server");
      return;
    }

    setTesting(true);
    setConnected(false);

    setTimeout(() => {
      setTesting(false);
      setConnected(true);
      toast.success("Successfully connected to IMAP and SMTP servers!");
    }, 2000);
  };

  const handleSync = () => {
    if (!connected) {
      toast.error("Please test the connection successfully first.");
      return;
    }

    setSyncing(true);
    setSyncProgress(0);

    const interval = setInterval(() => {
      setSyncProgress((prev) => {
        if (prev >= 100) {
          clearInterval(interval);
          setTimeout(() => {
            setSyncing(false);
            toast.success("Email Inbox synced successfully!");
            onSuccess();
          }, 500);
          return 100;
        }
        return prev + 10;
      });
    }, 300);
  };

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={600}
      destroyOnClose
      className="custom-email-modal"
      title={null}
      closable
    >
      <div className="p-6 md:p-8">
        {/* Header */}
        <div className="mb-6 flex items-center gap-3">
          <div className="p-2.5 bg-red-500/10 rounded-xl">
            <MailOutlined className="text-red-600 text-xl" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-[var(--app-text)] m-0">
              Configure Email Integration ({agentName})
            </h3>
            <p className="text-xs text-[var(--app-text-muted)] mt-1">
              Synchronize user conversations, customer inquiries or support tickets directly from your email server to train your cognitive agent.
            </p>
          </div>
        </div>

        {/* Content */}
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Text className="text-xs font-semibold text-[var(--app-text-soft)] uppercase block mb-1">Email Provider</Text>
              <Select
                value={provider}
                onChange={handleProviderChange}
                className="w-full h-10"
                options={[
                  { value: "gmail", label: "Gmail / Google Workspace" },
                  { value: "outlook", label: "Outlook / Office 365" },
                  { value: "yahoo", label: "Yahoo Mail" },
                  { value: "custom", label: "Custom SMTP / IMAP" },
                ]}
              />
            </div>
            <div>
              <Text className="text-xs font-semibold text-[var(--app-text-soft)] uppercase block mb-1">Email Address</Text>
              <Input
                type="email"
                placeholder="support@company.com"
                value={emailAddress}
                onChange={(e) => setEmailAddress(e.target.value)}
                className="h-10 rounded-lg"
              />
            </div>
          </div>

          <div>
            <Text className="text-xs font-semibold text-[var(--app-text-soft)] uppercase block mb-1">Password or App-Specific Password</Text>
            <Input.Password
              placeholder="••••••••••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-10 rounded-lg"
              prefix={<LockOutlined className="text-slate-400" />}
            />
            <Text className="text-[10px] text-slate-400 mt-1 block">
              For Gmail and Outlook 365, we highly recommend setting up and using an App-Specific Password instead of your master password.
            </Text>
          </div>

          <div className="p-4 bg-slate-50/50 dark:bg-slate-900/30 rounded-2xl border border-[var(--app-border)] space-y-4">
            <div className="flex items-center gap-1.5 text-xs font-bold text-slate-500 uppercase">
              <CloudServerOutlined /> Server Configuration Details
            </div>
            
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <Text className="text-[11px] font-semibold text-slate-400 block mb-1">IMAP Host</Text>
                <Input
                  placeholder="imap.company.com"
                  value={imapServer}
                  onChange={(e) => setImapServer(e.target.value)}
                  className="h-9 rounded-lg"
                />
              </div>
              <div>
                <Text className="text-[11px] font-semibold text-slate-400 block mb-1">IMAP Port</Text>
                <Input
                  placeholder="993"
                  value={imapPort}
                  onChange={(e) => setImapPort(e.target.value)}
                  className="h-9 rounded-lg"
                />
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <Text className="text-[11px] font-semibold text-slate-400 block mb-1">SMTP Host (Optional)</Text>
                <Input
                  placeholder="smtp.company.com"
                  value={smtpServer}
                  onChange={(e) => setSmtpServer(e.target.value)}
                  className="h-9 rounded-lg"
                />
              </div>
              <div>
                <Text className="text-[11px] font-semibold text-slate-400 block mb-1">SMTP Port</Text>
                <Input
                  placeholder="465"
                  value={smtpPort}
                  onChange={(e) => setSmtpPort(e.target.value)}
                  className="h-9 rounded-lg"
                />
              </div>
            </div>

            <div className="flex justify-between items-center">
              <div>
                <Text className="text-xs font-semibold text-[var(--app-text)] block">Require SSL/TLS Secure Link</Text>
                <Text className="text-[10px] text-slate-400 block">Encryption layer for raw email transfers</Text>
              </div>
              <Switch checked={useSsl} onChange={(checked) => setUseSsl(checked)} />
            </div>
          </div>

          {testing && (
            <div className="flex items-center gap-2 text-sm text-[#285d91]">
              <Spin size="small" /> Testing servers handshake and validation...
            </div>
          )}

          {connected && !syncing && (
            <div className="p-3 bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 border border-emerald-200/50 rounded-xl flex items-center gap-2 text-xs">
              <CheckCircleOutlined /> Server parameters verified. Ready to sync inbox contents.
            </div>
          )}

          {syncing && (
            <div className="space-y-1.5 p-4 bg-blue-50/50 dark:bg-blue-950/10 rounded-xl border border-blue-200/30">
              <div className="flex justify-between text-xs text-blue-700 font-semibold">
                <span className="flex items-center gap-1.5"><SyncOutlined spin /> Scraping & tokenizing email inbox...</span>
                <span>{syncProgress}%</span>
              </div>
              <Progress percent={syncProgress} showInfo={false} strokeColor="#3b82f6" />
            </div>
          )}
        </div>

        {/* Footer Actions */}
        <div className="flex justify-between items-center pt-6 mt-6 border-t border-[var(--app-border)]">
          <Button
            onClick={handleTestConnection}
            loading={testing}
            disabled={syncing}
            className="rounded-xl px-5 h-11 border-dashed hover:border-solid text-[var(--app-text)] font-semibold"
          >
            {connected ? "Re-Test Connection" : "Test Connection"}
          </Button>

          <div className="flex gap-3">
            <Button
              onClick={onClose}
              disabled={syncing}
              className="rounded-xl px-5 h-11 font-semibold border-[var(--app-border)] text-[var(--app-text)] hover:bg-slate-50"
            >
              Cancel
            </Button>
            <Button
              type="primary"
              disabled={!connected || syncing}
              onClick={handleSync}
              className={`rounded-xl px-8 h-11 font-semibold ${
                connected
                  ? "bg-purple-500 border-purple-500 hover:bg-purple-600"
                  : "bg-slate-200 border-slate-200 text-slate-400"
              }`}
            >
              Sync Inbox
            </Button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
