"use client";

import { 
  Flex, Typography, Card, Input, Switch, Button, 
  App, Row, Col, Modal, Spin, Tag, Tooltip, Divider
} from "antd";
import { 
  KeyOutlined, SaveOutlined, TeamOutlined,
  SafetyCertificateOutlined, MailOutlined, LineChartOutlined, 
  NodeIndexOutlined, UserOutlined, DeleteOutlined, 
  ExclamationCircleOutlined, GlobalOutlined, PhoneOutlined, 
  IdcardOutlined, CheckCircleOutlined, CopyOutlined,
  AppstoreOutlined, LockOutlined
} from "@ant-design/icons";
import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { API_BASE_URL, AUTH_COOKIE_KEY } from "@/app/config/config";
import { getCookie, deleteCookie } from "@/app/config/cookies";

const { Title, Text, Paragraph } = Typography;

interface SettingsSectionProps {
  title: string;
  description: string;
  children: React.ReactNode;
  icon: React.ComponentType;
  danger?: boolean;
}

function SettingsSection({ title, description, children, icon: Icon, danger }: SettingsSectionProps) {
  return (
    <Card 
      className={`bg-[var(--app-surface)] border ${danger ? "border-red-500/30 dark:border-red-500/20" : "border-[var(--app-border)]"} rounded-2xl shadow-sm overflow-hidden transition-all`}
      styles={{ body: { padding: "24px" } }}
    >
      <Row gutter={[24, 24]}>
        {/* Descriptive Section Heading Column - Stacked on Mobile, 1/3 Width on Desktop */}
        <Col xs={24} md={8}>
          <Flex vertical gap={8} className="md:sticky md:top-6">
            <Flex align="center" gap={12}>
              <div className={`w-9 h-9 rounded-lg ${danger ? "bg-red-500/10 text-red-500" : "bg-[#0fb5a1]/10 text-[#0fb5a1]"} flex items-center justify-center text-base shrink-0`}>
                <Icon />
              </div>
              <Title level={4} className={`!m-0 ${danger ? "!text-red-500" : "!text-[var(--app-text)]"} !text-base !font-bold tracking-tight`}>
                {title}
              </Title>
            </Flex>
            <Text className="text-[var(--app-text-muted)] text-xs leading-relaxed max-w-xs">
              {description}
            </Text>
          </Flex>
        </Col>

        {/* Inputs & Interaction Workspace Column - Stacked on Mobile, 2/3 Width on Desktop */}
        <Col xs={24} md={16}>
          <div className={`${danger ? "bg-red-50/40 dark:bg-red-950/10 border-red-200 dark:border-red-900/30" : "bg-[var(--app-surface-muted)] border-[var(--app-border)]/50"} p-4 sm:p-6 rounded-xl border space-y-6`}>
            {children}
          </div>
        </Col>
      </Row>
    </Card>
  );
}

interface ResourceSummary {
  agents_count: number;
  knowledge_bases_count: number;
  database_knowledgebases_count: number;
  chat_sessions_count: number;
  chat_messages_count: number;
  episodic_memories_count: number;
  user_preferences_count: number;
  api_keys_count: number;
  files_count: number;
  total_resources: number;
}

interface ProfileState {
  id: string;
  user_id: string;
  tenant_id: string;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  display_name: string;
  phone_number: string;
  avatar_url: string;
  bio: string;
  job_title: string;
  department: string;
  organization: string;
  country: string;
  timezone: string;
  language: string;
  theme: string;
  role: string;
  is_admin: boolean;
  notification_preferences: {
    email_notifications: boolean;
    analytics_reports: boolean;
    neural_feedback_loop: boolean;
  };
  resource_summary?: ResourceSummary;
}

export default function SettingsPage() {
  const { notification } = App.useApp();
  const router = useRouter();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteConfirmAcknowledged, setDeleteConfirmAcknowledged] = useState(false);
  const [deleteReason, setDeleteReason] = useState("");

  const [profile, setProfile] = useState<ProfileState>({
    id: "",
    user_id: "",
    tenant_id: "",
    username: "",
    email: "",
    first_name: "",
    last_name: "",
    display_name: "",
    phone_number: "",
    avatar_url: "",
    bio: "",
    job_title: "",
    department: "",
    organization: "",
    country: "",
    timezone: "UTC",
    language: "en",
    theme: "system",
    role: "user",
    is_admin: false,
    notification_preferences: {
      email_notifications: true,
      analytics_reports: true,
      neural_feedback_loop: false,
    },
  });

  const [summary, setSummary] = useState<ResourceSummary | null>(null);

  const getAuthToken = useCallback(() => {
    if (typeof window === "undefined") return null;
    return (
      getCookie(AUTH_COOKIE_KEY) ||
      getCookie("AUTH_TOKEN") ||
      localStorage.getItem("AUTH_TOKEN") ||
      localStorage.getItem("token")
    );
  }, []);

  const getProfileApiUrl = useCallback(() => {
    const raw = (API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:4915/api/v1").replace(/\/+$/, "");
    return raw.endsWith("/api/v1") ? `${raw}/profile` : `${raw}/api/v1/profile`;
  }, []);

  // 1. Fetch Profile and Summary on mount
  const fetchProfileData = useCallback(async () => {
    try {
      setLoading(true);
      const token = getAuthToken();
      if (!token) {
        setLoading(false);
        return;
      }

      const apiUrl = getProfileApiUrl();
      const res = await fetch(`${apiUrl}/me`, {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });

      if (res.ok) {
        const data = await res.json();
        setProfile({
          id: data.id || "",
          user_id: data.user_id || "",
          tenant_id: data.tenant_id || "",
          username: data.username || "",
          email: data.email || "",
          first_name: data.first_name || "",
          last_name: data.last_name || "",
          display_name: data.display_name || "",
          phone_number: data.phone_number || "",
          avatar_url: data.avatar_url || "",
          bio: data.bio || "",
          job_title: data.job_title || "",
          department: data.department || "",
          organization: data.organization || "Gsearch AI",
          country: data.country || "",
          timezone: data.timezone || "UTC",
          language: data.language || "en",
          theme: data.theme || "system",
          role: data.role || (data.is_admin ? "admin" : "user"),
          is_admin: !!data.is_admin,
          notification_preferences: {
            email_notifications: data.notification_preferences?.email_notifications ?? true,
            analytics_reports: data.notification_preferences?.analytics_reports ?? true,
            neural_feedback_loop: data.notification_preferences?.neural_feedback_loop ?? false,
          },
          resource_summary: data.resource_summary,
        });

        if (data.resource_summary) {
          setSummary(data.resource_summary);
        }
      } else {
        console.warn("Failed to load profile from API, status:", res.status);
      }
    } catch (err) {
      console.error("Error loading user profile:", err);
    } finally {
      setLoading(false);
    }
  }, [getAuthToken, getProfileApiUrl]);

  useEffect(() => {
    fetchProfileData();
  }, [fetchProfileData]);

  // 2. Save Updated Profile
  const handleSave = async () => {
    try {
      setSaving(true);
      const token = getAuthToken();
      if (!token) {
        notification.error({
          message: "Authentication Required",
          description: "Please log in to update your profile preferences.",
        });
        return;
      }

      const apiUrl = getProfileApiUrl();
      const payload = {
        username: profile.username || undefined,
        first_name: profile.first_name || undefined,
        last_name: profile.last_name || undefined,
        display_name: profile.display_name || undefined,
        phone_number: profile.phone_number || undefined,
        bio: profile.bio || undefined,
        job_title: profile.job_title || undefined,
        department: profile.department || undefined,
        organization: profile.organization || undefined,
        country: profile.country || undefined,
        timezone: profile.timezone || undefined,
        theme: profile.theme || undefined,
        notification_preferences: profile.notification_preferences,
      };

      const res = await fetch(`${apiUrl}/me`, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        const updated = await res.json();
        notification.success({
          message: "Settings Synchronized",
          description: "Your profile information and platform preferences have been successfully updated.",
          className: "custom-toast-success",
        });

        // Keep local display name synced
        if (updated.display_name) {
          localStorage.setItem("userName", updated.display_name);
        }
      } else {
        const errJson = await res.json().catch(() => ({}));
        notification.error({
          message: "Update Failed",
          description: errJson.detail || "Unable to update profile. Please check the values provided.",
        });
      }
    } catch (err: any) {
      notification.error({
        message: "Network Error",
        description: err.message || "An unexpected error occurred while saving configuration.",
      });
    } finally {
      setSaving(false);
    }
  };

  // 3. Complete Permanent Account Deletion
  const handleCompleteAccountDeletion = async () => {
    if (!deleteConfirmAcknowledged) {
      notification.warning({
        message: "Confirmation Required",
        description: "Please check the confirmation box to authorize permanent deletion.",
      });
      return;
    }

    try {
      setDeleteLoading(true);
      const token = getAuthToken();
      if (!token) {
        notification.error({
          message: "Session Expired",
          description: "Your session has expired. Please re-authenticate.",
        });
        return;
      }

      const apiUrl = getProfileApiUrl();
      const res = await fetch(`${apiUrl}/me`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          confirm: true,
          password: deletePassword || undefined,
          reason: deleteReason || undefined,
        }),
      });

      if (res.ok) {
        const result = await res.json();
        notification.success({
          message: "Account Deleted",
          description: result.message || "Your account and all associated resources have been permanently purged.",
          duration: 4,
        });

        setDeleteModalOpen(false);

        // Wipe client credentials and redirect to login
        deleteCookie(AUTH_COOKIE_KEY);
        deleteCookie("AUTH_TOKEN");
        localStorage.clear();

        setTimeout(() => {
          router.push("/login");
        }, 1200);
      } else {
        const errJson = await res.json().catch(() => ({}));
        notification.error({
          message: "Deletion Failed",
          description: errJson.detail || "Failed to purge account. Please verify your password and try again.",
        });
      }
    } catch (err: any) {
      notification.error({
        message: "Deletion Error",
        description: err.message || "A network error occurred during account deletion.",
      });
    } finally {
      setDeleteLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="w-full max-w-5xl pt-20 pb-20 px-4 md:px-10 flex flex-col items-center justify-center gap-4">
        <Spin size="large" />
        <Text className="text-xs text-[var(--app-text-muted)] font-semibold">
          Loading profile & account settings...
        </Text>
      </div>
    );
  }

  return (
    <div className="w-full max-w-5xl pt-10 pb-20 px-4 md:px-10 animate-in fade-in duration-500">
      <Flex vertical gap={32}>
        
        {/* Header Section */}
        <Flex vertical gap={6} className="border-b border-[var(--app-border)] pb-6">
          <Flex align="center" justify="space-between" wrap="wrap" gap={12}>
            <Title level={2} className="!m-0 !text-[var(--app-text)] !font-black !text-2xl tracking-tight">
              Account Settings & Profile
            </Title>
            <div className="flex items-center gap-2">
              <Tag color={profile.is_admin ? "purple" : "cyan"} className="font-bold uppercase tracking-wider text-[11px] px-2.5 py-0.5 rounded-full">
                {profile.role || (profile.is_admin ? "Admin" : "User")}
              </Tag>
              {profile.email && (
                <Tag color="green" className="font-semibold text-[11px] px-2 py-0.5 rounded-full flex items-center gap-1">
                  <CheckCircleOutlined /> Verified
                </Tag>
              )}
            </div>
          </Flex>
          <Text className="text-[var(--app-text-muted)] text-sm max-w-xl">
            Manage your personal profile, registered login identity, system configurations, and platform-wide resources.
          </Text>
        </Flex>

        <Flex vertical gap={24}>
          
          {/* Section 1: User Profile & Login Identity */}
          <SettingsSection 
            title="User Profile & Identity" 
            description="Manage your registered login details, personal name, and public display preferences."
            icon={UserOutlined}
          >
            <Flex vertical gap={20}>
              <Row gutter={[16, 16]}>
                <Col xs={24} sm={12}>
                  <Flex vertical gap={6}>
                    <Text className="font-bold text-xs text-[var(--app-text-soft)]">Registered Email (Login ID)</Text>
                    <Input 
                      variant="filled"
                      disabled
                      value={profile.email}
                      className="h-10 !rounded-lg !bg-[var(--app-surface)]/60 !text-[var(--app-text)] !text-sm border border-[var(--app-border)] cursor-not-allowed" 
                      prefix={<MailOutlined className="text-[var(--app-text-soft)] mr-1" />}
                    />
                  </Flex>
                </Col>

                <Col xs={24} sm={12}>
                  <Flex vertical gap={6}>
                    <Text className="font-bold text-xs text-[var(--app-text-soft)]">Unique Username</Text>
                    <Input 
                      variant="filled"
                      placeholder="username"
                      value={profile.username}
                      onChange={(e) => setProfile(prev => ({ ...prev, username: e.target.value }))}
                      className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#0fb5a1]/50 focus:border-[#0fb5a1]" 
                      prefix={<span className="text-[var(--app-text-soft)] font-mono font-bold mr-1">@</span>}
                    />
                  </Flex>
                </Col>
              </Row>

              <Row gutter={[16, 16]}>
                <Col xs={24} sm={12}>
                  <Flex vertical gap={6}>
                    <Text className="font-bold text-xs text-[var(--app-text-soft)]">First Name</Text>
                    <Input 
                      variant="filled"
                      placeholder="First Name" 
                      value={profile.first_name}
                      onChange={(e) => setProfile(prev => ({ ...prev, first_name: e.target.value }))}
                      className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#0fb5a1]/50 focus:border-[#0fb5a1]" 
                      prefix={<IdcardOutlined className="text-[var(--app-text-soft)] mr-1" />}
                    />
                  </Flex>
                </Col>

                <Col xs={24} sm={12}>
                  <Flex vertical gap={6}>
                    <Text className="font-bold text-xs text-[var(--app-text-soft)]">Last Name</Text>
                    <Input 
                      variant="filled"
                      placeholder="Last Name" 
                      value={profile.last_name}
                      onChange={(e) => setProfile(prev => ({ ...prev, last_name: e.target.value }))}
                      className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#0fb5a1]/50 focus:border-[#0fb5a1]" 
                      prefix={<IdcardOutlined className="text-[var(--app-text-soft)] mr-1" />}
                    />
                  </Flex>
                </Col>
              </Row>

              <Flex vertical gap={6}>
                <Text className="font-bold text-xs text-[var(--app-text-soft)]">Display Name</Text>
                <Input 
                  variant="filled"
                  placeholder="How you appear across the workspace" 
                  value={profile.display_name}
                  onChange={(e) => setProfile(prev => ({ ...prev, display_name: e.target.value }))}
                  className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#0fb5a1]/50 focus:border-[#0fb5a1]" 
                  prefix={<UserOutlined className="text-[var(--app-text-soft)] mr-1" />}
                />
              </Flex>

              <Flex vertical gap={6}>
                <Text className="font-bold text-xs text-[var(--app-text-soft)]">Bio & Summary</Text>
                <Input.TextArea 
                  rows={3}
                  placeholder="Tell your team about yourself or your focus areas..." 
                  value={profile.bio}
                  onChange={(e) => setProfile(prev => ({ ...prev, bio: e.target.value }))}
                  className="!rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#0fb5a1]/50 focus:border-[#0fb5a1]" 
                />
              </Flex>
            </Flex>
          </SettingsSection>

          {/* Section 2: Organization & Work Profile */}
          <SettingsSection 
            title="Organization & Credentials" 
            description="Manage organization affiliations, professional details, and programmatic credentials."
            icon={TeamOutlined}
          >
            <Flex vertical gap={20}>
              <Row gutter={[16, 16]}>
                <Col xs={24} sm={12}>
                  <Flex vertical gap={6}>
                    <Text className="font-bold text-xs text-[var(--app-text-soft)]">Organization Name</Text>
                    <Input 
                      variant="filled"
                      placeholder="Organization Name" 
                      value={profile.organization}
                      onChange={(e) => setProfile(prev => ({ ...prev, organization: e.target.value }))}
                      className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#0fb5a1]/50 focus:border-[#0fb5a1]" 
                      prefix={<TeamOutlined className="text-[var(--app-text-soft)] mr-1" />}
                    />
                  </Flex>
                </Col>

                <Col xs={24} sm={12}>
                  <Flex vertical gap={6}>
                    <Text className="font-bold text-xs text-[var(--app-text-soft)]">Job Title</Text>
                    <Input 
                      variant="filled"
                      placeholder="e.g. Lead Architect, Data Scientist" 
                      value={profile.job_title}
                      onChange={(e) => setProfile(prev => ({ ...prev, job_title: e.target.value }))}
                      className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#0fb5a1]/50 focus:border-[#0fb5a1]" 
                    />
                  </Flex>
                </Col>
              </Row>

              <Row gutter={[16, 16]}>
                <Col xs={24} sm={12}>
                  <Flex vertical gap={6}>
                    <Text className="font-bold text-xs text-[var(--app-text-soft)]">Department / Team</Text>
                    <Input 
                      variant="filled"
                      placeholder="e.g. Core Engineering" 
                      value={profile.department}
                      onChange={(e) => setProfile(prev => ({ ...prev, department: e.target.value }))}
                      className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#0fb5a1]/50 focus:border-[#0fb5a1]" 
                    />
                  </Flex>
                </Col>

                <Col xs={24} sm={12}>
                  <Flex vertical gap={6}>
                    <Text className="font-bold text-xs text-[var(--app-text-soft)]">Phone Number</Text>
                    <Input 
                      variant="filled"
                      placeholder="+1 (555) 000-0000" 
                      value={profile.phone_number}
                      onChange={(e) => setProfile(prev => ({ ...prev, phone_number: e.target.value }))}
                      className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#0fb5a1]/50 focus:border-[#0fb5a1]" 
                      prefix={<PhoneOutlined className="text-[var(--app-text-soft)] mr-1" />}
                    />
                  </Flex>
                </Col>
              </Row>

              <Row gutter={[16, 16]}>
                <Col xs={24} sm={12}>
                  <Flex vertical gap={6}>
                    <Text className="font-bold text-xs text-[var(--app-text-soft)]">Country</Text>
                    <Input 
                      variant="filled"
                      placeholder="Country" 
                      value={profile.country}
                      onChange={(e) => setProfile(prev => ({ ...prev, country: e.target.value }))}
                      className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#0fb5a1]/50 focus:border-[#0fb5a1]" 
                      prefix={<GlobalOutlined className="text-[var(--app-text-soft)] mr-1" />}
                    />
                  </Flex>
                </Col>

                <Col xs={24} sm={12}>
                  <Flex vertical gap={6}>
                    <Text className="font-bold text-xs text-[var(--app-text-soft)]">Timezone</Text>
                    <Input 
                      variant="filled"
                      placeholder="UTC" 
                      value={profile.timezone}
                      onChange={(e) => setProfile(prev => ({ ...prev, timezone: e.target.value }))}
                      className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#0fb5a1]/50 focus:border-[#0fb5a1]" 
                    />
                  </Flex>
                </Col>
              </Row>
              
              <Flex vertical gap={6}>
                <Text className="font-bold text-xs text-[var(--app-text-soft)]">Master Programmatic API Key</Text>
                <Input.Password 
                  variant="filled"
                  readOnly
                  value="gm_sk_4928f37454b04c9dba4e9eb10285786e"
                  className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#0fb5a1]/50 focus:border-[#0fb5a1]" 
                  prefix={<KeyOutlined className="text-[var(--app-text-soft)] mr-1" />}
                  suffix={
                    <Tooltip title="Copy API Key">
                      <Button 
                        type="text" 
                        size="small" 
                        icon={<CopyOutlined />} 
                        onClick={() => {
                          navigator.clipboard.writeText("gm_sk_4928f37454b04c9dba4e9eb10285786e");
                          notification.success({ message: "API Key copied to clipboard" });
                        }} 
                      />
                    </Tooltip>
                  }
                />
              </Flex>
            </Flex>
          </SettingsSection>

          {/* Section 3: Intelligence & System Preferences */}
          <SettingsSection 
            title="Intelligence Preferences" 
            description="Control how notifications, automated learning loops, and analytics are handled."
            icon={SafetyCertificateOutlined}
          >
            <Flex vertical className="divide-y divide-[var(--app-border)]/40">
              
              {/* Email Notifications */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 py-4 first:pt-0 last:pb-0">
                <Flex align="start" gap={12} className="w-full">
                  <MailOutlined className="text-[var(--app-text-soft)] mt-1 text-base shrink-0" />
                  <Flex vertical gap={2}>
                    <Text className="text-[var(--app-text)] font-semibold text-sm">Email Notifications</Text>
                    <Text className="text-[var(--app-text-soft)] text-xs leading-relaxed">
                      Get notified about unanswered questions and critical gaps.
                    </Text>
                  </Flex>
                </Flex>
                <div className="flex justify-end shrink-0 sm:ml-4">
                  <Switch 
                    checked={profile.notification_preferences.email_notifications}
                    onChange={(checked) => setProfile(prev => ({
                      ...prev,
                      notification_preferences: {
                        ...prev.notification_preferences,
                        email_notifications: checked,
                      }
                    }))}
                    className="custom-switch" 
                  />
                </div>
              </div>

              {/* Analytics Reports */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 py-4 first:pt-0 last:pb-0">
                <Flex align="start" gap={12} className="w-full">
                  <LineChartOutlined className="text-[var(--app-text-soft)] mt-1 text-base shrink-0" />
                  <Flex vertical gap={2}>
                    <Text className="text-[var(--app-text)] font-semibold text-sm">Analytics Reports</Text>
                    <Text className="text-[var(--app-text-soft)] text-xs leading-relaxed">
                      Receive weekly performance summaries and cognitive insights.
                    </Text>
                  </Flex>
                </Flex>
                <div className="flex justify-end shrink-0 sm:ml-4">
                  <Switch 
                    checked={profile.notification_preferences.analytics_reports}
                    onChange={(checked) => setProfile(prev => ({
                      ...prev,
                      notification_preferences: {
                        ...prev.notification_preferences,
                        analytics_reports: checked,
                      }
                    }))}
                    className="custom-switch" 
                  />
                </div>
              </div>

              {/* Neural Feedback Loop */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 py-4 first:pt-0 last:pb-0">
                <Flex align="start" gap={12} className="w-full">
                  <NodeIndexOutlined className="text-[var(--app-text-soft)] mt-1 text-base shrink-0" />
                  <Flex vertical gap={2}>
                    <Text className="text-[var(--app-text)] font-semibold text-sm">Neural Feedback Loop</Text>
                    <Text className="text-[var(--app-text-soft)] text-xs leading-relaxed">
                      Allow the system to learn from user corrections automatically.
                    </Text>
                  </Flex>
                </Flex>
                <div className="flex justify-end shrink-0 sm:ml-4">
                  <Switch 
                    checked={profile.notification_preferences.neural_feedback_loop}
                    onChange={(checked) => setProfile(prev => ({
                      ...prev,
                      notification_preferences: {
                        ...prev.notification_preferences,
                        neural_feedback_loop: checked,
                      }
                    }))}
                    className="custom-switch" 
                  />
                </div>
              </div>
              
            </Flex>
          </SettingsSection>

          {/* Section 4: Resource Usage & Platform Summary */}
          {summary && (
            <SettingsSection
              title="Platform Resource Inventory"
              description="Overview of autonomous agents, knowledge bases, and memories associated with your account."
              icon={AppstoreOutlined}
            >
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="bg-[var(--app-surface)] p-3 rounded-xl border border-[var(--app-border)]/60 text-center">
                  <div className="text-xl font-black text-[#0fb5a1]">{summary.agents_count}</div>
                  <div className="text-[11px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mt-0.5">Agents</div>
                </div>

                <div className="bg-[var(--app-surface)] p-3 rounded-xl border border-[var(--app-border)]/60 text-center">
                  <div className="text-xl font-black text-[#0fb5a1]">{summary.knowledge_bases_count}</div>
                  <div className="text-[11px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mt-0.5">Knowledge Bases</div>
                </div>

                <div className="bg-[var(--app-surface)] p-3 rounded-xl border border-[var(--app-border)]/60 text-center">
                  <div className="text-xl font-black text-[#0fb5a1]">{summary.chat_sessions_count}</div>
                  <div className="text-[11px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mt-0.5">Sessions</div>
                </div>

                <div className="bg-[var(--app-surface)] p-3 rounded-xl border border-[var(--app-border)]/60 text-center">
                  <div className="text-xl font-black text-[#0fb5a1]">{summary.total_resources}</div>
                  <div className="text-[11px] font-bold text-[var(--app-text-soft)] uppercase tracking-wider mt-0.5">Total Assets</div>
                </div>
              </div>
            </SettingsSection>
          )}

          {/* Save Action Bar */}
          <Flex justify="flex-end" className="mt-2">
            <Button 
              type="primary" 
              loading={saving}
              icon={<SaveOutlined />}
              onClick={handleSave}
              className="h-11 w-full sm:w-auto px-8 rounded-lg !bg-[#0fb5a1] border-none font-bold text-sm tracking-wide shadow-sm hover:opacity-90 active:scale-[0.98] transition-all"
            >
              Save Configuration
            </Button>
          </Flex>

          <Divider className="!my-2 !border-[var(--app-border)]/50" />

          {/* Section 5: Danger Zone - Complete Account Deletion */}
          <SettingsSection
            title="Danger Zone: Account Deletion"
            description="Permanently delete your profile and all associated data across the platform."
            icon={DeleteOutlined}
            danger={true}
          >
            <Flex vertical gap={16}>
              <div className="flex items-start gap-3">
                <ExclamationCircleOutlined className="text-red-500 text-lg mt-0.5 shrink-0" />
                <Flex vertical gap={4}>
                  <Text className="text-red-600 dark:text-red-400 font-bold text-sm">
                    Irreversible Platform-Wide Data Purge
                  </Text>
                  <Text className="text-[var(--app-text-soft)] text-xs leading-relaxed">
                    Deleting your account permanently removes your profile, registered agents, Neo4j graph nodes, 
                    uploaded documents, S3 files, Parquet datasets, chat histories, and episodic memories. 
                    This action cannot be undone.
                  </Text>
                </Flex>
              </div>

              <div className="flex justify-start">
                <Button
                  danger
                  type="primary"
                  icon={<DeleteOutlined />}
                  onClick={() => setDeleteModalOpen(true)}
                  className="h-10 px-5 rounded-lg font-bold text-xs uppercase tracking-wider shadow-sm hover:opacity-90"
                >
                  Delete Account & Purge Data
                </Button>
              </div>
            </Flex>
          </SettingsSection>

        </Flex>
      </Flex>

      {/* Confirmation Modal for Complete Account Deletion */}
      <Modal
        title={
          <Flex align="center" gap={8} className="text-red-600 font-bold">
            <ExclamationCircleOutlined />
            <span>Confirm Permanent Account Deletion</span>
          </Flex>
        }
        open={deleteModalOpen}
        onCancel={() => {
          setDeleteModalOpen(false);
          setDeletePassword("");
          setDeleteConfirmAcknowledged(false);
          setDeleteReason("");
        }}
        footer={[
          <Button 
            key="cancel" 
            onClick={() => setDeleteModalOpen(false)}
            disabled={deleteLoading}
          >
            Cancel
          </Button>,
          <Button
            key="delete"
            danger
            type="primary"
            loading={deleteLoading}
            disabled={!deleteConfirmAcknowledged}
            onClick={handleCompleteAccountDeletion}
            className="font-bold"
          >
            Permanently Delete Everything
          </Button>,
        ]}
      >
        <Flex vertical gap={16} className="py-4">
          <Paragraph className="text-xs text-[var(--app-text-soft)] !mb-0 leading-relaxed">
            You are about to permanently delete your account (<strong>{profile.email}</strong>). 
            All of the following items will be immediately and irreversibly purged:
          </Paragraph>

          <div className="bg-[var(--app-surface-muted)] p-3 rounded-xl border border-[var(--app-border)]/60 text-xs space-y-1.5 font-medium text-[var(--app-text-soft)]">
            <div>• All created agents & Neo4j knowledge graph nodes</div>
            <div>• All uploaded knowledge base files & S3 object storage</div>
            <div>• All chat sessions, messages, and feedback history</div>
            <div>• All episodic memories and user preference profiles</div>
            <div>• Your login account and authentication credentials</div>
          </div>

          <Flex vertical gap={6}>
            <Text className="font-bold text-xs text-[var(--app-text-soft)]">Enter Account Password (Optional for Verification)</Text>
            <Input.Password
              placeholder="Enter your password"
              value={deletePassword}
              onChange={(e) => setDeletePassword(e.target.value)}
              prefix={<LockOutlined className="text-[var(--app-text-soft)] mr-1" />}
            />
          </Flex>

          <Flex vertical gap={6}>
            <Text className="font-bold text-xs text-[var(--app-text-soft)]">Reason for Leaving (Optional)</Text>
            <Input
              placeholder="Optional feedback"
              value={deleteReason}
              onChange={(e) => setDeleteReason(e.target.value)}
            />
          </Flex>

          <div 
            onClick={() => setDeleteConfirmAcknowledged(prev => !prev)}
            className="flex items-center gap-2 p-2.5 rounded-lg border border-red-300/50 dark:border-red-900/40 bg-red-500/5 cursor-pointer select-none"
          >
            <input 
              type="checkbox" 
              checked={deleteConfirmAcknowledged}
              onChange={(e) => setDeleteConfirmAcknowledged(e.target.checked)}
              className="accent-red-600 w-4 h-4 rounded cursor-pointer"
            />
            <span className="text-xs font-bold text-red-600 dark:text-red-400">
              I understand this action is permanent and cannot be recovered.
            </span>
          </div>
        </Flex>
      </Modal>

    </div>
  );
}
