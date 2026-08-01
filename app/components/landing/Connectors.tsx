"use client";
import React from "react";
import { Typography } from "antd";
import { connectorApps } from "../lib/content";
import { 
  SiSlack, 
  SiGoogledrive, 
  SiGoogledocs,
  SiJira, 
  SiNotion, 
  SiGmail, 
  SiSalesforce, 
  SiClickup,
  SiGithub, 
  SiHubspot, 
  SiBox, 
  SiAirtable 
} from "react-icons/si";
import { TbBrandTeams } from "react-icons/tb";
import { LuCloud } from "react-icons/lu";

const { Title, Paragraph, Link } = Typography;

const AssemblyAILogo = ({ size = 32, ...props }: any) => (
  <svg viewBox="0 0 32 32" width={size} height={size} fill="none" {...props}>
    <circle cx="16" cy="16" r="15" fill="#f3ebff" />
    <circle cx="16" cy="16" r="12" fill="#7C3AED" />
    <rect x="9" y="11" width="14" height="2" rx="1" fill="#FFFFFF" />
    <rect x="7" y="15" width="18" height="2" rx="1" fill="#FFFFFF" />
    <rect x="10" y="19" width="12" height="2" rx="1" fill="#FFFFFF" />
  </svg>
);

const MicrosoftFabricLogo = ({ size = 32, ...props }: any) => (
  <svg viewBox="0 0 32 32" width={size} height={size} fill="none" {...props}>
    <rect x="4" y="4" width="10" height="10" rx="2.5" fill="#0078d4" />
    <rect x="18" y="4" width="10" height="10" rx="2.5" fill="#40a9ff" />
    <rect x="4" y="18" width="10" height="10" rx="2.5" fill="#096dd9" />
    <rect x="18" y="18" width="10" height="10" rx="2.5" fill="#0050b3" />
  </svg>
);

const appIcons: Record<string, React.ComponentType<any>> = {
  Slack: SiSlack,
  Drive: SiGoogledrive,
  "Google Docs": SiGoogledocs,
  Jira: SiJira,
  Notion: SiNotion,
  Gmail: SiGmail,
  Salesforce: SiSalesforce,
  HubSpot: SiHubspot,
  ClickUp: SiClickup,
  GitHub: SiGithub,
  Teams: TbBrandTeams,
  Box: SiBox,
  Airtable: SiAirtable,
  AssemblyAI: AssemblyAILogo,
  "Microsoft Fabric": MicrosoftFabricLogo,
  "Azure Blob Storage": LuCloud,
};

export default function Connectors() {
  return (
  <section className="gs-block alt" id="connectors">
    <div className="wrap">
      <div className="gs-sec-center">
        <div className="gs-eyebrow">100+ integrations</div>
        <Title level={1} className="gs-sec-h" style={{color:"var(--ink)",fontWeight:900}}>Which tools does Gsearch connect to?</Title>
        <Paragraph className="gs-sec-lede" style={{fontSize:"16px"}}>
          Gsearch connects to more than 100 workplace apps, including document stores, chat platforms, ticketing systems, CRMs, and wikis. Setup takes minutes per tool, content stays current automatically, and the permissions already configured in each app carry over unchanged.
        </Paragraph>
      </div>
      <div className="gs-conn-grid" aria-hidden="true">
        {connectorApps.map((app) => {
          const Icon = appIcons[app.name];
          return (
            <div className="gs-conn" key={app.name} title={app.name}>
              {Icon ? (
                <Icon size={32} style={{ color: app.color }} />
              ) : (
                <span className="mark" style={{ background: app.color }}>
                  {app.name.charAt(0)}
                </span>
              )}
            </div>
          );
        })}
      </div>
      <div className="gs-conn-more">
        <Link href="#" style={{ color: "var(--teal-deep)", fontWeight: 700, fontSize: 14.5 }}>
          Explore all connectors →
        </Link>
      </div>
    </div>
  </section>
  );
}
