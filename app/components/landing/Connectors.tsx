import React from "react";
import { Typography } from "antd";
import { connectorApps } from "../lib/content";
import { 
  SiSlack, 
  SiGoogledrive, 
  SiJira, 
  SiNotion, 
  SiGmail, 
  SiSalesforce, 
  SiConfluence, 
  SiZendesk, 
  SiGithub, 
  SiAsana, 
  SiHubspot, 
  SiBox, 
  SiNow, 
  SiZoom, 
  SiAirtable 
} from "react-icons/si";
import { TbBrandTeams } from "react-icons/tb";

const { Title, Paragraph, Link } = Typography;

const appIcons: Record<string, React.ComponentType<any>> = {
  Slack: SiSlack,
  Drive: SiGoogledrive,
  Jira: SiJira,
  Notion: SiNotion,
  Gmail: SiGmail,
  Salesforce: SiSalesforce,
  Confluence: SiConfluence,
  Zendesk: SiZendesk,
  GitHub: SiGithub,
  Asana: SiAsana,
  HubSpot: SiHubspot,
  Teams: TbBrandTeams,
  Box: SiBox,
  ServiceNow: SiNow,
  Zoom: SiZoom,
  Airtable: SiAirtable,
};

export default function Connectors() {
  return (
  <section className="gs-block alt" id="connectors">
    <div className="wrap">
      <div className="gs-sec-center">
        <div className="gs-eyebrow">100+ integrations</div>
        <Title level={2} className="gs-sec-h">Gsearch connects to every tool your team uses.</Title>
        <Paragraph className="gs-sec-lede">
          Set up in minutes, always current, with permissions that carry over automatically.
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
