

const logos = [
  { name: "Aviation", icon: "✈️"},
  { name: "Automotive", icon: "🚗" },
  { name: "Insurance", icon: "🛡️" },
  { name: "Manufacturing", icon: "🏭"},
];

export default function LogoStrip() {
  return (
  <div className="gs-logos">
    <div className="wrap">
      <p style={{ textAlign: "center", fontSize: 13, fontWeight: 700, color: "var(--faint)", letterSpacing: "0.04em", textTransform: "uppercase", marginBottom: 26 }}>
       Trusted by enterprise teams across
      </p>
      <div className="gs-logo-row">
        {logos.map((logo) => (
          <span key={logo.name} style={{ fontWeight: 800, fontSize: 18, color: "#aeb6c2", letterSpacing: "-0.01em",display:"flex", gap:"6px"}}>
           {logo.icon}
           <span style={{paddingTop:2}}>{logo.name}</span>
          </span>
        ))}
      </div>
    </div>
  </div>
  );
}
