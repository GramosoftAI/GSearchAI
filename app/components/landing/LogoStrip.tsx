import React from "react";
import { Typography } from "antd";

const { Title } = Typography;

const logos = ["Lion Air Group", "Batik Air", "Sundaram Motors", "KUN BMW", "Thai Lion Air"];

export default function LogoStrip() {
  return (
  <div className="gs-logos">
    <div className="wrap">
      <p style={{ textAlign: "center", fontSize: 13, fontWeight: 700, color: "var(--faint)", letterSpacing: "0.04em", textTransform: "uppercase", marginBottom: 26 }}>
        Trusted by teams at
      </p>
      <div className="gs-logo-row">
        {logos.map((logo) => (
          <span key={logo} style={{ fontWeight: 800, fontSize: 18, color: "#aeb6c2", letterSpacing: "-0.01em" }}>
            {logo}
          </span>
        ))}
      </div>
    </div>
  </div>
  );
}
