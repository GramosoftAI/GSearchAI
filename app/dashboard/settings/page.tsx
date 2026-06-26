"use client";

import { 
  Flex, Typography, Card, Input, Switch, Button, 
  App, Row, Col 
} from "antd";
import { 
  KeyOutlined, SaveOutlined, TeamOutlined,
  SafetyCertificateOutlined, MailOutlined, LineChartOutlined, NodeIndexOutlined
} from "@ant-design/icons";
import { useState } from "react";

const { Title, Text } = Typography;

interface SettingsSectionProps {
  title: string;
  description: string;
  children: React.ReactNode;
  icon: React.ComponentType;
}

function SettingsSection({ title, description, children, icon: Icon }: SettingsSectionProps) {
  return (
    <Card 
      className="bg-[var(--app-surface)] border border-[var(--app-border)] rounded-2xl shadow-sm overflow-hidden"
      styles={{ body: { padding: "24px" } }}
    >
      <Row gutter={[24, 24]}>
        {/* Descriptive Section Heading Column - Stacked on Mobile, 1/3 Width on Desktop */}
        <Col xs={24} md={8}>
          <Flex vertical gap={8} className="md:sticky md:top-6">
            <Flex align="center" gap={12}>
              <div className="w-9 h-9 rounded-lg bg-[#285d91]/10 text-[#285d91] flex items-center justify-center text-base shrink-0">
                <Icon />
              </div>
              <Title level={4} className="!m-0 !text-[var(--app-text)] !text-base !font-bold tracking-tight">
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
          <div className="bg-[var(--app-surface-muted)] p-4 sm:p-6 rounded-xl border border-[var(--app-border)]/50 space-y-6">
            {children}
          </div>
        </Col>
      </Row>
    </Card>
  );
}

export default function SettingsPage() {
  const { notification } = App.useApp();
  const [loading, setLoading] = useState(false);
  
  const handleSave = () => {
    setLoading(true);
    setTimeout(() => {
      setLoading(false);
      notification.success({
        message: 'Settings Synchronized',
        description: 'Your profile preferences have been successfully updated.',
        className: "custom-toast-success"
      });
    }, 1500);
  };

  return (
    <div className="w-full max-w-5xl pt-10 pb-20 px-4 md:px-10 animate-in fade-in duration-500">
      <Flex vertical gap={32}>
        
        {/* Header Section */}
        <Flex vertical gap={6} className="border-b border-[var(--app-border)] pb-6">
          <Title level={2} className="!m-0 !text-[var(--app-text)] !font-black !text-2xl tracking-tight">
            Account Settings
          </Title>
          <Text className="text-[var(--app-text-muted)] text-sm max-w-xl">
            Configure system configurations, security endpoints, and automated neural response patterns.
          </Text>
        </Flex>

        <Flex vertical gap={24}>
          
          {/* Profile Section */}
          <SettingsSection 
            title="Organization Profile" 
            description="Manage identity details and root API parameters utilized across client processes."
            icon={TeamOutlined}
          >
            <Flex vertical gap={20}>
              <Flex vertical gap={6}>
                <Text className="font-bold text-xs text-[var(--app-text-soft)]">Organization Name</Text>
                <Input 
                  variant="filled"
                  placeholder="Acme Corp" 
                  defaultValue="Gsearch AI"
                  className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#285d91]/50 focus:border-[#285d91]" 
                  prefix={<TeamOutlined className="text-[var(--app-text-soft)] mr-1" />}
                />
              </Flex>
              
              <Flex vertical gap={6}>
                <Text className="font-bold text-xs text-[var(--app-text-soft)]">Master API Key</Text>
                <Input.Password 
                  variant="filled"
                  defaultValue="gm_sk_4928f37454b04c9dba4e9eb10285786e"
                  className="h-10 !rounded-lg !bg-[var(--app-surface)] !text-[var(--app-text)] !text-sm border border-[var(--app-border)] hover:border-[#285d91]/50 focus:border-[#285d91]" 
                  prefix={<KeyOutlined className="text-[var(--app-text-soft)] mr-1" />}
                />
              </Flex>
            </Flex>
          </SettingsSection>

          {/* Preferences Section */}
          <SettingsSection 
            title="Intelligence Preferences" 
            description="Control how information and updates are handled across your platform loops."
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
                  <Switch defaultChecked className="bg-neutral-300 custom-switch" style={{ '--antd-wave-shadow-color': '#285d91' } as React.CSSProperties} />
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
                  <Switch defaultChecked className="bg-neutral-300 custom-switch" />
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
                  <Switch className="bg-neutral-300 custom-switch" />
                </div>
              </div>
              
            </Flex>
          </SettingsSection>

          {/* Save Action - Full width button on mobile, auto width on desktop */}
          <Flex justify="flex-end" className="mt-2">
            <Button 
              type="primary" 
              loading={loading}
              icon={<SaveOutlined />}
              onClick={handleSave}
              className="h-11 w-full sm:w-auto px-6 rounded-lg !bg-[#285d91] border-none font-bold text-sm tracking-wide shadow-sm hover:opacity-90 active:scale-[0.98] transition-all"
            >
              Save Configuration
            </Button>
          </Flex>

        </Flex>
      </Flex>
    </div>
  );
}


// "use client";

// import { 
//   Flex, Typography, Card, Input, Switch, Button, 
//   App, Space, Divider, Row, Col 
// } from "antd";
// import { 
//   UserOutlined, KeyOutlined, BellOutlined, 
//   BarChartOutlined, SaveOutlined, TeamOutlined,
//   SafetyCertificateOutlined
// } from "@ant-design/icons";
// import { useState, useEffect } from "react";

// const { Title, Text } = Typography;

// // ─── Settings Section Component ───────────────────────────────────────────────

// function SettingsSection({ title, children, icon: Icon }: { title: string; children: React.ReactNode; icon: any }) {
//   return (
//     <Card 
//       className="bg-[var(--app-surface)] border border-[var(--app-border)] rounded-[32px] shadow-[0_10px_30px_rgba(40,93,145,0.03)] overflow-hidden"
//       styles={{ body: { padding: 32 } }}
//     >
//       <Flex vertical gap={24}>
//         <Flex align="center" gap={12}>
//           <div className="w-10 h-10 rounded-xl bg-[#285d91]/5 text-[#285d91] flex items-center justify-center text-lg shadow-inner">
//             <Icon />
//           </div>
//           <Title level={4} className="!m-0 !text-[var(--app-text)] !font-black tracking-tight">
//             {title}
//           </Title>
//         </Flex>
//         {children}
//       </Flex>
//     </Card>
//   );
// }

// // ─── Main Page ────────────────────────────────────────────────────────────────

// export default function SettingsPage() {
//   const { notification } = App.useApp();
//   const [loading, setLoading] = useState(false);
  
//   const handleSave = () => {
//     setLoading(true);
//     setTimeout(() => {
//       setLoading(false);
//       notification.success({
//         title: 'Settings Synchronized',
//         description: 'Your profile preferences have been successfully updated.',
//         className: "custom-toast-success"
//       });
//     }, 1500);
//   };

//   return (
//     <div className="w-full pb-20 animate-in fade-in duration-1000">
//       <Flex vertical gap={40}>
        
//         {/* Header Section */}
//         <Flex vertical gap={8}>
//           <Title level={2} className="!m-0 !text-[var(--app-text)] !font-black !text-3xl tracking-tighter">
//             Account Settings
//           </Title>
//           <Text className="text-[var(--app-text-muted)] font-semibold text-sm max-w-xl leading-relaxed">
//             Manage your organization profile, security protocols, and system-wide preferences.
//           </Text>
//         </Flex>

//         <Flex vertical gap={24} className="max-w-4xl">
          
//           {/* Profile Section */}
//           <SettingsSection title="Organization Profile" icon={TeamOutlined}>
//             <Row gutter={[24, 24]}>
//               <Col xs={24}>
//                 <Flex vertical gap={6}>
//                   <Text className="font-black text-[9px] uppercase tracking-widest text-[var(--app-text-soft)]">Organization Name</Text>
//                   <Input 
//                     placeholder="Acme Corp" 
//                     defaultValue="Grag AI"
//                     className="h-12 !rounded-xl !bg-[var(--app-surface-muted)] !border-none !font-bold !text-[var(--app-text)] !text-sm focus:!ring-2 focus:!ring-[#285d91]/10" 
//                     prefix={<TeamOutlined className="text-[var(--app-text-soft)] mr-2" />}
//                   />
//                 </Flex>
//               </Col>
//               <Col xs={24}>
//                 <Flex vertical gap={6}>
//                   <Text className="font-black text-[9px] uppercase tracking-widest text-[var(--app-text-soft)]">Master API Key</Text>
//                   <Input.Password 
//                     defaultValue="gm_sk_4928f37454b04c9dba4e9eb10285786e"
//                     className="h-12 !rounded-xl !bg-[var(--app-surface-muted)] !border-none !font-bold !text-[var(--app-text)] !text-sm focus:!ring-2 focus:!ring-[#285d91]/10" 
//                     prefix={<KeyOutlined className="text-[var(--app-text-soft)] mr-2" />}
//                   />
//                 </Flex>
//               </Col>
//             </Row>
//           </SettingsSection>

//           {/* Preferences Section */}
//           <SettingsSection title="Intelligence Preferences" icon={SafetyCertificateOutlined}>
//             <div className="space-y-4">
//               <Flex align="center" justify="space-between" className="p-4 bg-[var(--app-surface-muted)] rounded-[20px] border border-[var(--app-border)]/30">
//                 <Flex vertical gap={2}>
//                   <Title level={5} className="!m-0 !text-[var(--app-text)] !font-black !text-sm">Email Notifications</Title>
//                   <Text className="text-[var(--app-text-soft)] font-bold text-[10px]">Get notified about unanswered questions and critical gaps.</Text>
//                 </Flex>
//                 <Switch defaultChecked size="small" className="bg-[#285d91]" />
//               </Flex>

//               <Flex align="center" justify="space-between" className="p-4 bg-[var(--app-surface-muted)] rounded-[20px] border border-[var(--app-border)]/30">
//                 <Flex vertical gap={2}>
//                   <Title level={5} className="!m-0 !text-[var(--app-text)] !font-black !text-sm">Analytics Reports</Title>
//                   <Text className="text-[var(--app-text-soft)] font-bold text-[10px]">Receive weekly performance summaries and cognitive insights.</Text>
//                 </Flex>
//                 <Switch defaultChecked size="small" className="bg-[#285d91]" />
//               </Flex>

//               <Flex align="center" justify="space-between" className="p-4 bg-[var(--app-surface-muted)] rounded-[20px] border border-[var(--app-border)]/30">
//                 <Flex vertical gap={2}>
//                   <Title level={5} className="!m-0 !text-[var(--app-text)] !font-black !text-sm">Neural Feedback Loop</Title>
//                   <Text className="text-[var(--app-text-soft)] font-bold text-[10px]">Allow the system to learn from user corrections automatically.</Text>
//                 </Flex>
//                 <Switch size="small" className="bg-[#285d91]" />
//               </Flex>
//             </div>
//           </SettingsSection>

//           {/* Save Action */}
//           <Flex justify="flex-end" className="mt-4">
//             <Button 
//               type="primary" 
//               size="large" 
//               loading={loading}
//               icon={<SaveOutlined />}
//               onClick={handleSave}
//               className="!h-14 !px-10 !rounded-2xl !bg-[#285d91] !border-none !font-black !text-sm !uppercase !tracking-widest shadow-xl shadow-blue-900/10 hover:!scale-[1.02] transition-all"
//             >
//               Save Configuration
//             </Button>
//           </Flex>

//         </Flex>
//       </Flex>
//     </div>
//   );
// }
