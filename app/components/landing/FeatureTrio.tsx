"use client";
import { Row, Col, Card, Typography } from "antd";

const { Title, Paragraph } = Typography;

const features = [
  {
    icon: "◉",
    title: "Get the full picture, fast",
    body: "Gsearch pulls from every tool your team uses, connects the dots across them, and gives you answers grounded in your actual data.",
  },
  {
    icon: "🧠",
    title: "It remembers, so you don't have to",
    body: "Ask a question, explore an idea, or work through a problem. Gsearch recalls your context — your projects, your terms, your history — not just your keywords.",
  },
  {
    icon: "🔒",
    title: "Your data never leaves",
    body: "Answers are pulled in real time from the source. Sensitive data stays where it is, with no copies stored and no waiting for a sync to finish.",
  },
];

export default function FeatureTrio() {
  return (
    <section className="gs-block" id="product">
      <div className="wrap">
        <div className="gs-sec-center">
          <div className="gs-eyebrow">One place for everything</div>
          <Title level={1} className="gs-sec-h" style={{color:"var(--ink)",lineHeight:1.12,fontWeight:800}}>What does Gsearch actually do?</Title>
          <Paragraph className="gs-sec-lede" style={{fontSize:"16px",paddingBottom:30,color:"var(--muted)"}}>
            Gsearch brings every tool your company uses into one searchable brain. It reads your documents, tickets, chats, and files where they already live, understands how they relate, and returns a single cited answer instead of a list of links you still have to read.
          </Paragraph>
        </div>
        <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
          {features.map((f) => {
            return (
              <Col xs={24} md={8} key={f.title}>
                <Card
                  className="gs-fcard"
                  style={{ height: "100%", border: "1px solid var(--line)", borderRadius: 16 }}
                  styles={{ body: { padding: 30 } }}
                >
                  <div className="ic" style={{ width: 48, height: 48, borderRadius: 13, display: "grid", placeItems: "center", marginBottom: 18, background: "var(--teal-soft)", color: "var(--teal-deep)" }}>
                    {f.icon}
                  </div>
                  <Title level={3} style={{ fontSize: 19, marginBottom: 10 }}>{f.title}</Title>
                  <Paragraph style={{ fontSize:"15px", color: "var(--muted)", margin: 0 }}>{f.body}</Paragraph>
                </Card>
              </Col>
            );
          })}
        </Row>
        {/* DIAGRAM 1: Central Brain Diagram */}
        <figure className="illus" aria-labelledby="illus1-cap">
          <svg viewBox="0 0 820 300" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Diagram showing scattered workplace tools connecting into one central Gsearch brain that returns a single cited answer">
            <defs>
              <linearGradient id="gA" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#0FB5A1"/>
                <stop offset="50%" stopColor="#7C6CF0"/>
                <stop offset="100%" stopColor="#F4C24B"/>
              </linearGradient>
              <linearGradient id="pulseGrad" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#0FB5A1" stopOpacity="0.1"/>
                <stop offset="50%" stopColor="#0FB5A1" stopOpacity="1"/>
                <stop offset="100%" stopColor="#7C6CF0" stopOpacity="0.3"/>
              </linearGradient>
              <filter id="glowBrain" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="5" result="blur" />
                <feComposite in="SourceGraphic" in2="blur" operator="over" />
              </filter>
              <filter id="glowCard" x="-10%" y="-10%" width="120%" height="120%">
                <feDropShadow dx="0" dy="6" stdDeviation="10" floodColor="#0FB5A1" floodOpacity="0.12"/>
              </filter>
            </defs>

            {/* Base connecting lines cleanly touching node edges and brain edge */}
            <g stroke="#E2E8F0" strokeWidth="1.8" fill="none">
              <path d="M198 60 L350 150"/>
              <path d="M168 150 L350 150"/>
              <path d="M198 240 L350 150"/>
              <path d="M280 46 L350 150"/>
              <path d="M280 254 L350 150"/>
            </g>

            {/* Glowing animated flow pulses */}
            <g stroke="url(#pulseGrad)" strokeWidth="2.5" fill="none" strokeLinecap="round">
              <path d="M198 60 L350 150" className="illus-flow illus-flow-1"/>
              <path d="M168 150 L350 150" className="illus-flow illus-flow-2"/>
              <path d="M198 240 L350 150" className="illus-flow illus-flow-3"/>
              <path d="M280 46 L350 150" className="illus-flow illus-flow-4"/>
              <path d="M280 254 L350 150" className="illus-flow illus-flow-5"/>
            </g>

            {/* Source Tool Nodes */}
            <g fontFamily="Plus Jakarta Sans,sans-serif" fontSize="12" fontWeight="600" fill="#475569" textAnchor="middle">
              <g className="illus-node illus-node-1"><rect x="86" y="42" width="112" height="36" rx="10" fill="#fff" stroke="#E2E8F0" className="illus-rect"/><text x="142" y="65">Documents</text></g>
              <g className="illus-node illus-node-2"><rect x="56" y="132" width="112" height="36" rx="10" fill="#fff" stroke="#E2E8F0" className="illus-rect"/><text x="112" y="155">Chat threads</text></g>
              <g className="illus-node illus-node-3"><rect x="86" y="222" width="112" height="36" rx="10" fill="#fff" stroke="#E2E8F0" className="illus-rect"/><text x="142" y="245">Tickets</text></g>
              <g className="illus-node illus-node-4"><rect x="205" y="12" width="100" height="34" rx="10" fill="#fff" stroke="#E2E8F0" className="illus-rect"/><text x="255" y="34">Wikis</text></g>
              <g className="illus-node illus-node-5"><rect x="205" y="240" width="100" height="34" rx="10" fill="#fff" stroke="#E2E8F0" className="illus-rect"/><text x="255" y="262">CRM</text></g>
            </g>

            {/* Central Brain Node - Perfect Alignment & Pure Opacity Pulse */}
            <g className="illus-brain-group">
              <circle cx="400" cy="150" r="62" fill="#0FB5A1" className="illus-brain-outer-ring" />
              <circle cx="400" cy="150" r="50" fill="#E3F7F3" stroke="#0FB5A1" strokeWidth="2.5" className="illus-brain-core" filter="url(#glowBrain)" />
              <g className="illus-brain-icon">
                <path d="M378 150c0-14 10-24 22-24s22 10 22 24-10 24-22 24-22-10-22-24z" fill="none" stroke="#0FB5A1" strokeWidth="2"/>
                <path d="M400 126v48M382 138h36M382 162h36" stroke="#0FB5A1" strokeWidth="1.6" opacity=".75"/>
              </g>
              <text x="400" y="224" fontFamily="Plus Jakarta Sans,sans-serif" fontSize="13" fontWeight="800" fill="#0F172A" textAnchor="middle" className="illus-brain-text">Gsearch</text>
            </g>

            {/* Arrow Stream to Answer */}
            <g className="illus-arrow-group">
              <path d="M450 150 L520 150" stroke="url(#gA)" strokeWidth="3.5" fill="none" strokeLinecap="round" className="illus-arrow-line"/>
              <polygon points="518,143 534,150 518,157" fill="#F4C24B" className="illus-arrow-head"/>
            </g>

            {/* Answer Output Card */}
            <g className="illus-answer-card" filter="url(#glowCard)">
              <rect x="546" y="86" width="248" height="128" rx="16" fill="#ffffff" stroke="#CBD5E1" strokeWidth="1.5" className="illus-answer-bg"/>
              <rect x="566" y="106" width="64" height="22" rx="7" fill="#0FB5A1" className="illus-answer-tag"/>
              <text x="598" y="121" fontFamily="Plus Jakarta Sans,sans-serif" fontSize="11" fontWeight="700" fill="#ffffff" textAnchor="middle">Answer</text>
              
              {/* Skeleton lines */}
              <rect x="566" y="140" width="208" height="9" rx="4.5" fill="#E2E8F0" className="illus-line illus-line-1"/>
              <rect x="566" y="156" width="170" height="9" rx="4.5" fill="#E2E8F0" className="illus-line illus-line-2"/>
              
              {/* Citations */}
              <g className="illus-citations">
                <rect x="566" y="178" width="58" height="20" rx="7" fill="#E3F7F3" stroke="#0FB5A1" strokeWidth="1" className="illus-cit illus-cit-1"/>
                <rect x="630" y="178" width="58" height="20" rx="7" fill="#F0FDF4" stroke="#22C55E" strokeWidth="1" className="illus-cit illus-cit-2"/>
                <rect x="694" y="178" width="58" height="20" rx="7" fill="#F5F3FF" stroke="#7C6CF0" strokeWidth="1" className="illus-cit illus-cit-3"/>
              </g>
            </g>
          </svg>
          <figcaption id="illus1-cap">Scattered tools become one connected brain — and one cited answer.</figcaption>
        </figure>
      </div>
    </section>
  );
}
