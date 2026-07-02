import React from "react";
import { Collapse, Typography } from "antd";
import type { CollapseProps } from "antd";
import { faqItems } from "../lib/content";

const { Title, Paragraph } = Typography;

const items: CollapseProps["items"] = faqItems.map((item, i) => ({
  key: String(i),
  label: item.question,
  children: (
    <Paragraph style={{ margin: 0, color: "var(--muted)", fontSize: 15 }}>
      {item.answer}
    </Paragraph>
  ),
}));

export default function Faq() {
  return (
  <section className="gs-block alt">
    <div className="wrap">
      <div className="gs-sec-center">
        <div className="gs-eyebrow">Good to know</div>
        <Title level={2} className="gs-sec-h" style={{color:"var(--ink)",fontWeight:800}}>Questions teams ask before they start.</Title>
      </div>
      <div style={{ maxWidth: 780, margin: "46px auto 0" }}>
        <Collapse
          items={items}
          defaultActiveKey={["0"]}
          bordered={false}
          className="gs-faq-collapse"
          expandIconPosition="end"
          expandIcon={() => (
            <span className="plus" style={{ color: "var(--teal)", fontSize: 22, fontWeight: 600 }}>
              +
            </span>
          )}
        />
      </div>
    </div>
  </section>
  );
}
