import React from "react";

export default function BrandGlyph() {
  return (
  <svg className="glyph" viewBox="0 0 32 32" fill="none" width={28} height={28}>
    <circle cx="9" cy="10" r="3.6" fill="#E3F7F3" stroke="#0FB5A1" strokeWidth="1.8" />
    <circle cx="23" cy="8" r="3" fill="#fff" stroke="#7C6CF0" strokeWidth="1.8" />
    <circle cx="22" cy="23" r="4.2" fill="#F4C24B" stroke="#E0A92E" strokeWidth="1.6" />
    <circle cx="10" cy="23" r="2.8" fill="#fff" stroke="#0FB5A1" strokeWidth="1.8" />
    <path
      d="M12 11 L20 9 M23 11 L22 19 M12 22 L18 23 M11 21 L20 11"
      stroke="#C9D2DC"
      strokeWidth="1.4"
    />
  </svg>
  );
}
