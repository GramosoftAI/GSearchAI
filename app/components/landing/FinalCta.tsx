import React from "react";
import { Button, Space, Typography } from "antd";

const { Title, Paragraph } = Typography;

export default function FinalCta() {
  return (
  <section className="gs-final" id="cta">
    <div className="wrap">
      <Title level={1} style={{ fontSize: "clamp(30px,4vw,46px)", fontWeight: 800, letterSpacing: "-0.03em", maxWidth: 680, margin: "0 auto", textAlign: "center",color:"var(--ink)" }}>
        Give your company a second brain.
      </Title>
      <Paragraph style={{ fontSize: 18, color: "var(--muted)", margin: "18px auto 30px", maxWidth: 500, textAlign: "center" }}>
        See Gsearch connect your own tools in a demo tailored to your team. Stop searching. Start knowing.
      </Paragraph>
      <Space size={14} wrap style={{ justifyContent: "center", display: "flex" }}>
        <Button
          type="primary"
          size="large"
          href="#"
          style={{ background: "var(--teal)", borderColor: "var(--teal)", fontWeight: 700, borderRadius: 11, boxShadow: "0 6px 18px -6px rgba(15,181,161,0.5)",padding:25 }}
        >
          Book a demo
        </Button>
        <Button
          size="large"
          href="#"
          style={{ borderColor: "var(--line-2)", color: "var(--ink)", fontWeight: 700, borderRadius: 11,padding:25 }}
        >
          Start for free
        </Button>
      </Space>
    </div>
  </section>
  );
}
