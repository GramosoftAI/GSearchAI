"""Email service - handles sending system emails (auth, alerts, notifications)"""

import asyncio
import io
import logging
import math
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Optional

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BRAND = "GSearchAI"
LOGO_URL = "https://gsearchai.com/512_512.png"

# ---------------------------------------------------------------------------
# Dynamic AI Neural Core Looping GIF Generator & In-Memory Cache
# Email clients (notably Gmail & Outlook) strip CSS @keyframes and raw <svg>,
# but reliably render animated GIFs embedded directly via MIME inline (cid:).
# ---------------------------------------------------------------------------
_CACHED_NEURAL_CORE_GIF: Optional[bytes] = None


def _generate_neural_core_gif(size: int = 140, num_frames: int = 30) -> bytes:
    """
    Generates a looping 30-frame AI Neural Core GIF (~48KB).
    Renders smoothly at 20fps in Gmail, mobile clients, and webmail:
    - Obsidian dark core background (#050c12)
    - Expanding radar energy pulse wave
    - Rotating outer synapse ring (12 arcs)
    - 3 orbiting synapse satellite nodes with bright flare centers
    - Counter-rotating inner neural network web with interconnected nodes
    - Pulsing central quantum intelligence core
    """
    try:
        from PIL import Image, ImageDraw

        frames = []
        center = size / 2.0
        r_outer = size * 0.44
        r_mid = size * 0.33
        r_inner = size * 0.22
        r_core = size * 0.14

        for i in range(num_frames):
            t = i / float(num_frames)
            angle_cw = t * 2 * math.pi
            angle_ccw = -t * 2 * math.pi

            img = Image.new("RGBA", (size, size), (5, 12, 18, 255))
            draw = ImageDraw.Draw(img)

            # 1. Background radial glow
            for glow_r, alpha in [(55, 15), (42, 28), (28, 45)]:
                draw.ellipse(
                    [center - glow_r, center - glow_r, center + glow_r, center + glow_r],
                    fill=(15, 181, 161, alpha)
                )

            # 2. Expanding radar pulse wave
            for wave_offset in [0.0, 0.5]:
                w_prog = (t + wave_offset) % 1.0
                wave_r = r_core + w_prog * (r_outer - r_core + 8)
                wave_alpha = int(180 * (1.0 - w_prog))
                if wave_alpha > 10:
                    draw.ellipse(
                        [center - wave_r, center - wave_r, center + wave_r, center + wave_r],
                        outline=(34, 211, 238, wave_alpha),
                        width=1
                    )

            # 3. Outer Synapse Ring (12 arcs rotating clockwise)
            num_dashes = 12
            for d in range(num_dashes):
                arc_start = angle_cw + (d / float(num_dashes)) * 2 * math.pi
                arc_end = arc_start + (math.pi / num_dashes) * 0.75
                pts = []
                steps = 4
                for s in range(steps + 1):
                    cur_a = arc_start + (arc_end - arc_start) * (s / float(steps))
                    pts.append((center + r_outer * math.cos(cur_a), center + r_outer * math.sin(cur_a)))
                draw.line(pts, fill=(15, 181, 161, 160), width=2)

            # 4. 3 Orbiting Synapse Nodes
            for n in range(3):
                n_angle = angle_cw + (n * 2 * math.pi / 3.0)
                nx = center + r_outer * math.cos(n_angle)
                ny = center + r_outer * math.sin(n_angle)
                draw.ellipse([nx - 5, ny - 5, nx + 5, ny + 5], fill=(34, 211, 238, 120))
                draw.ellipse([nx - 3, ny - 3, nx + 3, ny + 3], fill=(94, 234, 212, 230))
                draw.ellipse([nx - 1.5, ny - 1.5, nx + 1.5, ny + 1.5], fill=(255, 255, 255, 255))

            # 5. Middle Neural Web (Hexagon counter-rotating)
            hex_pts = []
            for h in range(6):
                h_angle = angle_ccw + (h * math.pi / 3.0)
                hx = center + r_mid * math.cos(h_angle)
                hy = center + r_mid * math.sin(h_angle)
                hex_pts.append((hx, hy))

            for h in range(6):
                p1 = hex_pts[h]
                p2 = hex_pts[(h + 1) % 6]
                draw.line([p1, p2], fill=(34, 211, 238, 80), width=1)
                if h % 2 == 0:
                    draw.line([p1, (center, center)], fill=(15, 181, 161, 50), width=1)
                draw.ellipse([p1[0] - 2.5, p1[1] - 2.5, p1[0] + 2.5, p1[1] + 2.5], fill=(34, 211, 238, 200))

            # 6. Inner Orbit Ring
            draw.ellipse(
                [center - r_inner, center - r_inner, center + r_inner, center + r_inner],
                outline=(15, 181, 161, 90),
                width=1
            )

            # 7. Central Intelligence Core
            pulse = 1.0 + 0.12 * math.sin(t * 2 * math.pi)
            c_r = r_core * pulse

            draw.ellipse([center - c_r - 4, center - c_r - 4, center + c_r + 4, center + c_r + 4], fill=(15, 181, 161, 70))
            draw.ellipse([center - c_r, center - c_r, center + c_r, center + c_r], fill=(15, 181, 161, 220))
            c_r_inner = c_r * 0.65
            draw.ellipse([center - c_r_inner, center - c_r_inner, center + c_r_inner, center + c_r_inner], fill=(34, 211, 238, 255))
            spark_r = 3.5 * pulse
            draw.ellipse([center - spark_r, center - spark_r, center + spark_r, center + spark_r], fill=(255, 255, 255, 255))

            frames.append(img.convert("RGB"))

        buf = io.BytesIO()
        frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=50, loop=0, optimize=True)
        return buf.getvalue()
    except Exception as exc:
        logger.warning(f"Could not generate neural core animated GIF: {exc}")
        return b""


def get_neural_core_gif() -> bytes:
    """Returns cached animated neural core GIF bytes."""
    global _CACHED_NEURAL_CORE_GIF
    if _CACHED_NEURAL_CORE_GIF is None:
        _CACHED_NEURAL_CORE_GIF = _generate_neural_core_gif()
    return _CACHED_NEURAL_CORE_GIF


# ---------------------------------------------------------------------------
# Progressive CSS Enhancement for modern clients (Apple Mail, Thunderbird)
# Table layouts and inline styles provide 100% universal rendering on Gmail.
# ---------------------------------------------------------------------------
_CSS = """
@keyframes buttonShimmer {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}
@keyframes cyberGlow {
  0%, 100% { box-shadow: 0 0 16px rgba(15,181,161,0.4); }
  50% { box-shadow: 0 0 28px rgba(34,211,238,0.7); }
}
.ai-btn-glow {
  background: linear-gradient(135deg, #0fb5a1 0%, #0d9488 40%, #0891b2 70%, #22d3ee 100%) !important;
  background-size: 200% 200% !important;
  animation: buttonShimmer 4s ease infinite, cyberGlow 3s ease-in-out infinite !important;
}
.pulse-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: #22d3ee;
  box-shadow: 0 0 8px #22d3ee;
}
@media (max-width: 520px) {
  .email-inner-pad { padding-left: 20px !important; padding-right: 20px !important; }
}
"""

_STYLE_CARD_BG = "background-color:#ffffff;border-radius:24px;overflow:hidden;box-shadow:0 20px 55px rgba(2,16,23,0.14);border:1px solid #e2e8f0;"
_STYLE_P = "color:#475569;line-height:1.75;font-size:15px;margin:0 0 18px;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
_STYLE_H2 = "color:#0f172a;margin:0 0 14px;font-size:22px;font-weight:800;letter-spacing:-0.02em;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"


def _render_neural_hero(title: str, subtitle_chip: str, badge_icon: str) -> str:
    """Renders the high-tech AI Cockpit Hero Section with embedded animated neural core."""
    return f"""
    <!-- Hero Header Table -->
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:linear-gradient(175deg, #050c12 0%, #081721 50%, #0d2330 100%);border-top-left-radius:24px;border-top-right-radius:24px;overflow:hidden;">
      <tr>
        <td align="center" style="padding:36px 20px 32px;">
          <!-- High-Tech Brand Status Chip -->
          <table cellpadding="0" cellspacing="0" border="0" style="margin-bottom:16px;">
            <tr>
              <td style="background:rgba(15,181,161,0.15);border:1px solid rgba(45,212,191,0.35);padding:5px 14px;border-radius:999px;">
                <span class="pulse-dot" style="display:inline-block;width:7px;height:7px;border-radius:50%;background-color:#22d3ee;vertical-align:middle;margin-right:6px;"></span>
                <span style="font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:11px;font-weight:700;letter-spacing:0.12em;color:#5eead4;text-transform:uppercase;vertical-align:middle;">
                  {subtitle_chip}
                </span>
              </td>
            </tr>
          </table>

          <!-- Animated AI Neural Core Hero Image (Embedded via CID) -->
          <table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto 18px;">
            <tr>
              <td align="center" style="position:relative;">
                <img src="cid:ai_neural_core" width="130" height="130" alt="{BRAND} Neural Core" style="display:block;border:0;outline:none;border-radius:50%;box-shadow:0 0 35px rgba(34,211,238,0.35);" />
              </td>
            </tr>
          </table>

          <!-- Hero Title -->
          <table cellpadding="0" cellspacing="0" border="0" style="max-width:480px;width:100%;">
            <tr>
              <td align="center" style="font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:24px;line-height:1.3;font-weight:800;color:#ffffff;letter-spacing:-0.02em;">
                {title}
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    """


def _render_page_wrapper(hero_html: str, body_html: str, preheader: str) -> str:
    """Wraps body and hero in standard, bulletproof table-based HTML email shell."""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{BRAND}</title>
  <style>{_CSS}</style>
</head>
<body style="margin:0;padding:24px 10px;background-color:#eef6f5;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">{preheader}</div>
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr>
      <td align="center">
        <!-- Main Card Container -->
        <table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;{_STYLE_CARD_BG}">
          <tr>
            <td>
              {hero_html}
            </td>
          </tr>
          <tr>
            <td class="email-inner-pad" style="padding:36px 36px 24px;background-color:#ffffff;">
              {body_html}
            </td>
          </tr>
          <tr>
            <td style="background:linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);padding:24px 30px;text-align:center;border-top:1px solid #e2e8f0;font-size:12px;color:#64748b;line-height:1.7;">
              <div style="margin-bottom:6px;font-weight:700;letter-spacing:0.06em;color:#0f766e;text-transform:uppercase;font-size:11px;">
                ⚡ Powered by {BRAND} Enterprise Neural Architecture
              </div>
              <div>This is an automated security transmission. Please do not reply directly to this message.</div>
              <div style="margin-top:6px;color:#94a3b8;">&copy; 2026 <strong style="color:#0fb5a1;">{BRAND}</strong>. All rights reserved.</div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def render(template_type: str, **kwargs) -> str:
    """
    Renders dynamic, high-tech animated HTML email templates ('otp', 'reset', or 'welcome').
    """
    first_name = escape(str(kwargs.get("first_name") or "there"))
    cta_url = escape(str(kwargs.get("cta_url") or settings.FRONTEND_URL))
    expiry = escape(str(kwargs.get("expiry") or "5 minutes"))
    otp = escape(str(kwargs.get("otp") or ""))

    if template_type == "otp":
        hero = _render_neural_hero(
            title="Identity Verification Required",
            subtitle_chip="Neural Security Protocol",
            badge_icon="🔐"
        )

        # Build individual OTP digit table cells with spacer cells for bulletproof table alignment
        otp_cells = []
        for char in otp:
            otp_cells.append(f"""
            <td align="center" valign="middle" width="46" height="58" style="background:#061118;border:2px solid #0fb5a1;border-radius:12px;color:#22d3ee;font-family:'Courier New',Consolas,monospace;font-size:32px;font-weight:900;text-align:center;box-shadow:0 0 14px rgba(15,181,161,0.25);">
              {char}
            </td>
            """)
        digit_row = '<td width="6"></td>'.join(otp_cells) if otp_cells else f'<td style="color:#22d3ee;font-size:32px;font-weight:900;">{otp}</td>'

        body = f"""
        <h2 style="{_STYLE_H2}">Hello {first_name},</h2>
        <p style="{_STYLE_P}">
          A request was initiated to verify your identity for your <strong>{BRAND}</strong> account. Please input the following One-Time Security Passkey to finalize verification:
        </p>

        <!-- Futuristic Holographic Code Vault -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:linear-gradient(135deg, #061118 0%, #0a1f2c 100%);border-radius:18px;padding:26px 16px;margin:26px 0;border:1px solid rgba(45,212,191,0.4);box-shadow:0 12px 30px rgba(6,17,24,0.3);">
          <tr>
            <td align="center">
              <div style="font-size:11px;font-weight:800;letter-spacing:0.18em;text-transform:uppercase;color:#5eead4;margin-bottom:16px;">
                🔒 One-Time Security Passkey
              </div>

              <!-- Centered Digits Table -->
              <table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto 16px;">
                <tr>
                  {digit_row}
                </tr>
              </table>

              <table cellpadding="0" cellspacing="0" border="0" style="margin:0 auto;">
                <tr>
                  <td align="center" style="font-size:12px;color:#94a3b8;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
                    <span style="color:#fde047;">⏳</span> Passkey expires in <strong style="color:#ffffff;">{expiry}</strong>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>

        <!-- Security Advisory Card -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f0fdfa;border-left:4px solid #0fb5a1;border-radius:8px;margin:22px 0;">
          <tr>
            <td style="padding:14px 18px;">
              <div style="font-size:13px;font-weight:700;color:#0f766e;margin-bottom:4px;">
                🛡️ Enterprise Shield Active
              </div>
              <div style="font-size:13px;color:#334155;line-height:1.6;">
                Do not disclose this security passkey to anyone. {BRAND} staff will never request your verification credentials over email or phone.
              </div>
            </td>
          </tr>
        </table>

        <p style="{_STYLE_P};font-size:13px;color:#64748b;">
          If you did not authorize this authentication request, someone may be attempting unauthorized access. You can safely discard this transmission.
        </p>
        """

        return _render_page_wrapper(
            hero_html=hero,
            body_html=body,
            preheader=f"Your {BRAND} verification passkey is {otp}. Valid for {expiry}."
        )

    elif template_type == "reset":
        hero = _render_neural_hero(
            title="Password Recovery Protocol",
            subtitle_chip="Security Override Access",
            badge_icon="🛡️"
        )

        body = f"""
        <h2 style="{_STYLE_H2}">Hello {first_name},</h2>
        <p style="{_STYLE_P}">
          We received a security dispatch to reset the credential authentication key for your <strong>{BRAND}</strong> profile. Click the button below to initiate authorization:
        </p>

        <!-- Quantum Recovery CTA -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:30px 0 34px;">
          <tr>
            <td align="center">
              <table cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td align="center" style="background:linear-gradient(135deg, #0fb5a1 0%, #0d9488 40%, #0891b2 70%, #22d3ee 100%);border-radius:14px;box-shadow:0 0 24px rgba(15,181,161,0.45);">
                    <a href="{cta_url}" target="_blank" class="ai-btn-glow" style="display:inline-block;padding:16px 36px;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:16px;font-weight:800;color:#ffffff;text-decoration:none;letter-spacing:0.02em;">
                      Authorize Password Reset ➔
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>

        <!-- Time Validity Card -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#fefce8;border-left:4px solid #eab308;border-radius:8px;margin:20px 0 24px;">
          <tr>
            <td style="padding:14px 18px;font-size:13px;color:#854d0e;font-weight:700;">
              <span>⏰</span> Action Required: This link expires in <strong>{expiry}</strong>
            </td>
          </tr>
        </table>

        <!-- Terminal Direct Link -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#0b151e;border:1px solid #1e293b;border-radius:12px;margin-bottom:24px;">
          <tr>
            <td style="padding:14px 18px;">
              <div style="font-size:11px;font-weight:700;color:#94a3b8;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.08em;">
                Manual Override Link:
              </div>
              <div style="font-family:'Courier New',Consolas,monospace;font-size:12px;word-break:break-all;color:#22d3ee;line-height:1.5;">
                <a href="{cta_url}" style="color:#22d3ee;text-decoration:none;">{cta_url}</a>
              </div>
            </td>
          </tr>
        </table>

        <p style="{_STYLE_P};font-size:13px;color:#64748b;">
          If you did not request a credential reset, please disregard this automated notification. Your existing authentication keys remain secure.
        </p>
        """

        return _render_page_wrapper(
            hero_html=hero,
            body_html=body,
            preheader=f"Reset your {BRAND} password. Security link valid for {expiry}."
        )

    elif template_type == "welcome":
        hero = _render_neural_hero(
            title="Neural Core Initialized",
            subtitle_chip="Autonomous Agent Active",
            badge_icon="🚀"
        )

        steps = [
            ("🧠", "01. Knowledge Ingestion", "Upload unstructured documents, databases, or API streams into multi-tenant vector & graph nodes."),
            ("⚡", "02. Graph RAG Synthesis", "Run conversational queries with sub-second hybrid semantic reranking and deep knowledge retrieval."),
            ("🚀", "03. Autonomous Workflows", "Empower intelligent AI agents with live reasoning, memory synthesis, and automated actions.")
        ]

        steps_rows = "".join(f"""
        <tr>
          <td style="padding-bottom:12px;">
            <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;">
              <tr>
                <td width="48" align="center" valign="middle" style="padding:14px 12px 14px 16px;">
                  <div style="width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg, #0fb5a1, #22d3ee);text-align:center;line-height:38px;font-size:18px;color:#ffffff;box-shadow:0 4px 10px rgba(15,181,161,0.25);">
                    {icon}
                  </div>
                </td>
                <td valign="middle" style="padding:14px 16px 14px 4px;">
                  <div style="font-weight:800;font-size:14px;color:#0f172a;margin-bottom:2px;">{stitle}</div>
                  <div style="font-size:13px;color:#64748b;line-height:1.5;">{sdesc}</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        """ for icon, stitle, sdesc in steps)

        body = f"""
        <h2 style="{_STYLE_H2}">Welcome Aboard, {first_name}! 🎉</h2>
        <p style="{_STYLE_P}">
          Your <strong>{BRAND}</strong> intelligent intelligence node is officially provisioned and operational. You are now equipped with full enterprise Graph RAG and cognitive reasoning capabilities.
        </p>

        <!-- Access Banner -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:linear-gradient(135deg, #f0fdfa 0%, #ecfeff 100%);border:1px solid #99f6e4;border-radius:14px;margin:20px 0 26px;">
          <tr>
            <td style="padding:18px 20px;">
              <div style="font-weight:800;color:#0f766e;font-size:15px;margin-bottom:4px;">
                ✨ Enterprise Access Level: Activated
              </div>
              <div style="font-size:13px;color:#334155;line-height:1.6;">
                All neural indices, multi-agent workspaces, and real-time knowledge graphs are ready for immediate deployment.
              </div>
            </td>
          </tr>
        </table>

        <div style="font-size:13px;font-weight:800;color:#0f172a;margin-bottom:14px;text-transform:uppercase;letter-spacing:0.06em;">
          Fast-Track Roadmap:
        </div>

        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          {steps_rows}
        </table>

        <!-- Launch CTA -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:28px 0;">
          <tr>
            <td align="center">
              <table cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td align="center" style="background:linear-gradient(135deg, #0fb5a1 0%, #0d9488 40%, #0891b2 70%, #22d3ee 100%);border-radius:14px;box-shadow:0 0 24px rgba(15,181,161,0.45);">
                    <a href="{cta_url}" target="_blank" class="ai-btn-glow" style="display:inline-block;padding:16px 38px;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:16px;font-weight:800;color:#ffffff;text-decoration:none;letter-spacing:0.02em;">
                      Launch Knowledge Workspace ➔
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>

        <p style="{_STYLE_P}">
          If you have questions or require advanced architectural configurations, our engineering team is available 24/7.
        </p>
        <p style="margin:0 0 10px;color:#475569;font-size:14px;">
          Best regards,<br>
          <strong style="color:#0fb5a1;">The {BRAND} Architecture Team</strong>
        </p>
        """

        return _render_page_wrapper(
            hero_html=hero,
            body_html=body,
            preheader=f"Your {BRAND} intelligent workspace is active. Let's get started."
        )

    return ""


class EmailService:
    """
    Service for sending emails.
    Uses SMTP server configured in settings with full support for
    inlined GIF MIME attachments (cid:) for universal cross-client animations.
    """

    @staticmethod
    def _smtp_send(msg: MIMEMultipart, to_email: str) -> None:
        if settings.email_port == 465:
            server = smtplib.SMTP_SSL(settings.email_host, settings.email_port, timeout=30)
        else:
            server = smtplib.SMTP(settings.email_host, settings.email_port, timeout=30)
            server.starttls()
        try:
            server.login(settings.email_username, settings.email_password)
            server.sendmail(msg["From"], to_email, msg.as_string())
        finally:
            server.quit()

    @staticmethod
    async def send_email(
        to_email: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None
    ) -> bool:
        """Send an email to a single recipient using configured SMTP and inlined CID animations."""
        if not settings.email_host or not settings.email_username or not settings.email_password:
            logger.error("SMTP credentials not fully configured in settings.")
            return False

        try:
            # Check if template references the neural core animation
            has_cid_gif = bool(html_body and "cid:ai_neural_core" in html_body)

            if has_cid_gif:
                # RFC 2387 multipart/related root for inline media
                msg = MIMEMultipart("related")
                msg["Subject"] = subject
                msg["From"] = settings.email_from or settings.email_username
                msg["To"] = to_email

                # Alternative container for plain text vs HTML
                msg_alt = MIMEMultipart("alternative")
                msg.attach(msg_alt)

                msg_alt.attach(MIMEText(body, "plain", "utf-8"))
                if html_body:
                    msg_alt.attach(MIMEText(html_body, "html", "utf-8"))

                # Attach inline animated GIF
                gif_bytes = get_neural_core_gif()
                if gif_bytes:
                    img_part = MIMEImage(gif_bytes, "gif")
                    img_part.add_header("Content-ID", "<ai_neural_core>")
                    img_part.add_header("Content-Disposition", "inline", filename="ai_neural_core.gif")
                    msg.attach(img_part)
            else:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = settings.email_from or settings.email_username
                msg["To"] = to_email
                msg.attach(MIMEText(body, "plain", "utf-8"))
                if html_body:
                    msg.attach(MIMEText(html_body, "html", "utf-8"))

            # smtplib is blocking, so run it off the event loop
            await asyncio.to_thread(EmailService._smtp_send, msg, to_email)
            logger.info("Email sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    @staticmethod
    async def send_password_reset_email(email: str, token: str, first_name: str = None) -> bool:
        """Send password reset link to user"""
        reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token}"

        subject = "GSearchAI - Reset Your Password"
        body = (
            "Click the link below to reset your password. This link expires in 1 hour.\n\n"
            f"{reset_link}\n\n"
            "If you didn't request a password reset, you can safely ignore this email."
        )
        html_body = render("reset", first_name=first_name or "there", cta_url=reset_link, expiry="1 hour")
        return await EmailService.send_email(to_email=email, subject=subject, body=body, html_body=html_body)

    @staticmethod
    async def send_registration_otp_email(email: str, otp: str, first_name: str = None) -> bool:
        """Send registration OTP to user"""
        subject = "GSearchAI - Registration Verification Code"
        body = (
            f"Your registration verification code is: {otp}\n\n"
            "This code will expire in 5 minutes.\n\n"
            "Never share this code with anyone. Our team will never ask for it."
        )
        html_body = render("otp", first_name=first_name or "there", otp=otp, expiry="5 minutes")
        return await EmailService.send_email(to_email=email, subject=subject, body=body, html_body=html_body)

    @staticmethod
    async def send_welcome_email(email: str, first_name: str) -> bool:
        """Send welcome email to user after successful registration"""
        subject = "Welcome to GSearchAI! 🎉"
        body = (
            f"Hello {first_name},\n\n"
            "Welcome to GSearchAI! We're thrilled to have you join our community.\n\n"
            "Your account has been successfully created! You can now access all features "
            "and start using the platform.\n\n"
            "Thank you for choosing us!\n\n"
            "Best regards,\nThe GSearchAI Team"
        )
        html_body = render("welcome", first_name=first_name or "there", cta_url=settings.FRONTEND_URL)
        return await EmailService.send_email(to_email=email, subject=subject, body=body, html_body=html_body)
