"""Email service - handles sending system emails (auth, alerts, notifications)"""

import logging
from typing import Optional
from pydantic import EmailStr
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class EmailService:
    """
    Service for sending emails.
    Uses SMTP server configured in settings.
    """

    @staticmethod
    async def send_email(
        to_email: str,
        subject: str,
        body: str,
        html_body: Optional[str] = None
    ) -> bool:
        """
        Send an email to a single recipient using configured SMTP.
        """
        if not settings.email_host or not settings.email_username or not settings.email_password:
            logger.error("SMTP credentials not fully configured in settings.")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.email_from or settings.email_username
            msg["To"] = to_email

            part1 = MIMEText(body, "plain")
            msg.attach(part1)
            
            if html_body:
                part2 = MIMEText(html_body, "html")
                msg.attach(part2)

            # Connect to SMTP Server (assumes SSL for port 465, STARTTLS otherwise)
            if settings.email_port == 465:
                server = smtplib.SMTP_SSL(settings.email_host, settings.email_port)
            else:
                server = smtplib.SMTP(settings.email_host, settings.email_port)
                server.starttls()
            
            server.login(settings.email_username, settings.email_password)
            server.sendmail(msg["From"], to_email, msg.as_string())
            server.quit()
            logger.info("Email sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    @staticmethod
    async def send_password_reset_email(email: str, token: str, first_name: str = None) -> bool:
        """Send password reset link to user"""
        reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        greeting = f"Hello {first_name}," if first_name else "Hello,"
        
        subject = "GraphMind - Reset Your Password"
        body = f"Click the link below to reset your password. This link expires in 1 hour.\n\n{reset_link}"
        html_body = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; background-color: #f9f9fb; padding: 20px;">
            <div style="background: linear-gradient(to right, #6b46c1, #805ad5); padding: 30px; border-radius: 10px 10px 0 0; text-align: center; color: white;">
                <h1 style="margin: 0; font-size: 24px;">🔒 Password Reset Request</h1>
            </div>
            <div style="background-color: white; padding: 40px; border-radius: 0 0 10px 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
                <h2 style="color: #2d3748; margin-top: 0;">{greeting}</h2>
                <p style="color: #4a5568; line-height: 1.6;">We received a request to reset your password. Please click the button below to set a new password:</p>
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_link}" style="background-color: #805ad5; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block; font-size: 16px;">Reset Password</a>
                </div>
                <div style="background-color: #fefcbf; border-left: 4px solid #ecc94b; padding: 15px; border-radius: 4px; margin-bottom: 20px;">
                    <p style="margin: 0; color: #975a16; font-size: 14px;">⏰ <strong>Important:</strong> This link is valid for <strong>1 hour</strong> only.</p>
                </div>
                <p style="color: #4a5568; line-height: 1.6;">If the button doesn't work, you can copy and paste this link into your browser:</p>
                <p style="color: #4a5568; line-height: 1.6; word-break: break-all; font-size: 14px;"><a href="{reset_link}" style="color: #6b46c1;">{reset_link}</a></p>
                <p style="color: #4a5568; line-height: 1.6;">If you didn't request a password reset, you can safely ignore this email.</p>
            </div>
            <div style="text-align: center; margin-top: 30px; color: #a0aec0; font-size: 12px;">
                <p>This is an automated email. Please do not reply.</p>
                <p>© 2026 GsearchAi. All rights reserved.</p>
            </div>
        </div>
        """
        
        return await EmailService.send_email(to_email=email, subject=subject, body=body, html_body=html_body)

    @staticmethod
    async def send_sitemap_monitor_alert(
        email: str,
        user_name: str,
        sitemap_url: str,
        total_urls: int,
        new_urls: list,
        modified_urls: list,
        auto_crawled: bool = True
    ) -> bool:
        """
        Send scheduled website monitor alert email detailing newly added and modified URLs.
        Matches the GCrawl alert layout.
        """
        greeting = f"Hello {user_name}," if user_name else "Hello,"
        change_summary = f"Sitemap changed: +{len(new_urls)} new URLs added, ~{len(modified_urls)} existing URLs modified. (Total: {total_urls})"

        # Build list items for new URLs
        new_urls_html = ""
        if new_urls:
            new_urls_html = """
            <div style="margin-top: 20px;">
                <h4 style="color: #27ae60; margin-bottom: 8px; font-size: 15px;">+ Newly Added URLs ({count}):</h4>
                <ul style="padding-left: 20px; margin: 0; line-height: 1.8;">
                    {items}
                </ul>
            </div>
            """.format(
                count=len(new_urls),
                items="\n".join([f'<li><a href="{u}" style="color: #2b6cb0; text-decoration: underline;" target="_blank">{u}</a></li>' for u in new_urls[:50]])
            )
            if len(new_urls) > 50:
                new_urls_html += f'<p style="color: #718096; font-size: 13px; margin-top: 5px;">...and {len(new_urls) - 50} more URLs</p>'

        # Build list items for modified URLs
        modified_urls_html = ""
        if modified_urls:
            modified_urls_html = """
            <div style="margin-top: 20px;">
                <h4 style="color: #d69e2e; margin-bottom: 8px; font-size: 15px;">~ Modified Existing URLs ({count}):</h4>
                <ul style="padding-left: 20px; margin: 0; line-height: 1.8;">
                    {items}
                </ul>
            </div>
            """.format(
                count=len(modified_urls),
                items="\n".join([f'<li><a href="{u}" style="color: #2b6cb0; text-decoration: underline;" target="_blank">{u}</a></li>' for u in modified_urls[:30]])
            )
            if len(modified_urls) > 30:
                modified_urls_html += f'<p style="color: #718096; font-size: 13px; margin-top: 5px;">...and {len(modified_urls) - 30} more URLs</p>'

        crawl_notice = ""
        if auto_crawled:
            crawl_notice = """
            <div style="background-color: #ebf8ff; border-left: 4px solid #3182ce; padding: 12px 16px; border-radius: 4px; margin-top: 25px;">
                <p style="margin: 0; color: #2b6cb0; font-size: 13px; font-weight: 500;">
                    🤖 <strong>Automatic Ingestion Active:</strong> These new URLs have been automatically queued and indexed into your Knowledge Base vector index.
                </p>
            </div>
            """

        subject = f"Website Monitor Alert: Changes detected in {sitemap_url}"
        body = f"""{greeting}\n\nYour scheduled website monitor has completed its periodic check for:\n{sitemap_url}\n\n{change_summary}\n\nNewly Added ({len(new_urls)}):\n""" + "\n".join(new_urls[:20])

        html_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 650px; margin: 0 auto; background-color: #f7fafc; padding: 25px;">
            <div style="background: white; border-radius: 12px; padding: 35px; box-shadow: 0 4px 12px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;">
                <p style="font-size: 16px; color: #2d3748; font-weight: 600; margin-top: 0;">{greeting}</p>
                <p style="color: #4a5568; font-size: 14px; margin-bottom: 20px;">Your scheduled website monitor has completed its periodic check for:</p>
                
                <div style="border-left: 4px solid #3182ce; background-color: #f7fafc; padding: 15px 18px; border-radius: 0 8px 8px 0; margin-bottom: 24px;">
                    <div style="font-size: 11px; text-transform: uppercase; color: #718096; font-weight: bold; letter-spacing: 0.5px;">MONITORED URL</div>
                    <div style="font-size: 15px; color: #2b6cb0; word-break: break-all; font-weight: 600; margin-top: 4px;">{sitemap_url}</div>
                </div>

                <div style="display: flex; align-items: center; background-color: #fefcbf; border-radius: 8px; padding: 12px 16px; margin-bottom: 25px;">
                    <span style="background-color: #ecc94b; color: #744210; font-size: 11px; font-weight: 800; padding: 3px 8px; border-radius: 12px; margin-right: 12px; text-transform: uppercase;">CHANGES DETECTED</span>
                    <span style="color: #744210; font-size: 13px; font-weight: 500;">{change_summary}</span>
                </div>

                <div style="font-size: 15px; font-weight: 700; color: #2d3748; margin-bottom: 12px;">
                    Total Sitemap URLs: {total_urls}
                </div>

                {new_urls_html}
                {modified_urls_html}
                {crawl_notice}

                <div style="margin-top: 35px; padding-top: 20px; border-top: 1px solid #edf2f7; text-align: center; color: #a0aec0; font-size: 12px;">
                    <p style="margin: 0;">Automated alert generated by GSearchAI Website Monitor.</p>
                </div>
            </div>
        </div>
        """

        return await EmailService.send_email(to_email=email, subject=subject, body=body, html_body=html_body)


    @staticmethod
    async def send_registration_otp_email(email: str, otp: str, first_name: str = None) -> bool:
        """Send registration OTP to user"""
        subject = "GsearchAi - Registration Verification Code"
        greeting = f"Hello {first_name}," if first_name else "Hello,"
        body = f"Your registration verification code is: {otp}\n\nThis code will expire in 5 minutes."
        html_body = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; background-color: #f9f9fb; padding: 20px;">
            <div style="background: linear-gradient(to right, #6b46c1, #805ad5); padding: 30px; border-radius: 10px 10px 0 0; text-align: center; color: white;">
                <h1 style="margin: 0; font-size: 24px;">🔒 Email Verification</h1>
            </div>
            <div style="background-color: white; padding: 40px; border-radius: 0 0 10px 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
                <h2 style="color: #2d3748; margin-top: 0;">{greeting}</h2>
                <p style="color: #4a5568; line-height: 1.6;">Thank you for signing up! To complete your registration, please use the following One-Time Password (OTP):</p>
                <div style="border: 2px dashed #805ad5; border-radius: 8px; padding: 20px; text-align: center; margin: 30px 0;">
                    <h1 style="color: #6b46c1; font-size: 36px; letter-spacing: 10px; margin: 0;">{otp}</h1>
                </div>
                <div style="background-color: #fefcbf; border-left: 4px solid #ecc94b; padding: 15px; border-radius: 4px; margin-bottom: 20px;">
                    <p style="margin: 0; color: #975a16; font-size: 14px;">⏰ <strong>Important:</strong> This OTP is valid for <strong>5 minutes</strong> only.</p>
                </div>
                <p style="color: #4a5568; line-height: 1.6;">Enter this code in the verification page to activate your account.</p>
                <p style="color: #4a5568; line-height: 1.6;">If you didn't request this verification, please ignore this email.</p>
                <div style="background-color: #fed7d7; border-left: 4px solid #e53e3e; padding: 15px; border-radius: 4px; margin-top: 30px;">
                    <p style="margin: 0; color: #9b2c2c; font-size: 14px;">🔒 <strong>Security Notice:</strong> Never share this OTP with anyone. Our team will never ask for your OTP.</p>
                </div>
            </div>
            <div style="text-align: center; margin-top: 30px; color: #a0aec0; font-size: 12px;">
                <p>This is an automated email. Please do not reply.</p>
                <p>© 2026 GSearchAi. All rights reserved.</p>
            </div>
        </div>
        """
        
        return await EmailService.send_email(to_email=email, subject=subject, body=body, html_body=html_body)

    @staticmethod
    async def send_sitemap_monitor_alert(
        email: str,
        user_name: str,
        sitemap_url: str,
        total_urls: int,
        new_urls: list,
        modified_urls: list,
        auto_crawled: bool = True
    ) -> bool:
        """
        Send scheduled website monitor alert email detailing newly added and modified URLs.
        Matches the GCrawl alert layout.
        """
        greeting = f"Hello {user_name}," if user_name else "Hello,"
        change_summary = f"Sitemap changed: +{len(new_urls)} new URLs added, ~{len(modified_urls)} existing URLs modified. (Total: {total_urls})"

        # Build list items for new URLs
        new_urls_html = ""
        if new_urls:
            new_urls_html = """
            <div style="margin-top: 20px;">
                <h4 style="color: #27ae60; margin-bottom: 8px; font-size: 15px;">+ Newly Added URLs ({count}):</h4>
                <ul style="padding-left: 20px; margin: 0; line-height: 1.8;">
                    {items}
                </ul>
            </div>
            """.format(
                count=len(new_urls),
                items="\n".join([f'<li><a href="{u}" style="color: #2b6cb0; text-decoration: underline;" target="_blank">{u}</a></li>' for u in new_urls[:50]])
            )
            if len(new_urls) > 50:
                new_urls_html += f'<p style="color: #718096; font-size: 13px; margin-top: 5px;">...and {len(new_urls) - 50} more URLs</p>'

        # Build list items for modified URLs
        modified_urls_html = ""
        if modified_urls:
            modified_urls_html = """
            <div style="margin-top: 20px;">
                <h4 style="color: #d69e2e; margin-bottom: 8px; font-size: 15px;">~ Modified Existing URLs ({count}):</h4>
                <ul style="padding-left: 20px; margin: 0; line-height: 1.8;">
                    {items}
                </ul>
            </div>
            """.format(
                count=len(modified_urls),
                items="\n".join([f'<li><a href="{u}" style="color: #2b6cb0; text-decoration: underline;" target="_blank">{u}</a></li>' for u in modified_urls[:30]])
            )
            if len(modified_urls) > 30:
                modified_urls_html += f'<p style="color: #718096; font-size: 13px; margin-top: 5px;">...and {len(modified_urls) - 30} more URLs</p>'

        crawl_notice = ""
        if auto_crawled:
            crawl_notice = """
            <div style="background-color: #ebf8ff; border-left: 4px solid #3182ce; padding: 12px 16px; border-radius: 4px; margin-top: 25px;">
                <p style="margin: 0; color: #2b6cb0; font-size: 13px; font-weight: 500;">
                    🤖 <strong>Automatic Ingestion Active:</strong> These new URLs have been automatically queued and indexed into your Knowledge Base vector index.
                </p>
            </div>
            """

        subject = f"Website Monitor Alert: Changes detected in {sitemap_url}"
        body = f"""{greeting}\n\nYour scheduled website monitor has completed its periodic check for:\n{sitemap_url}\n\n{change_summary}\n\nNewly Added ({len(new_urls)}):\n""" + "\n".join(new_urls[:20])

        html_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 650px; margin: 0 auto; background-color: #f7fafc; padding: 25px;">
            <div style="background: white; border-radius: 12px; padding: 35px; box-shadow: 0 4px 12px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;">
                <p style="font-size: 16px; color: #2d3748; font-weight: 600; margin-top: 0;">{greeting}</p>
                <p style="color: #4a5568; font-size: 14px; margin-bottom: 20px;">Your scheduled website monitor has completed its periodic check for:</p>
                
                <div style="border-left: 4px solid #3182ce; background-color: #f7fafc; padding: 15px 18px; border-radius: 0 8px 8px 0; margin-bottom: 24px;">
                    <div style="font-size: 11px; text-transform: uppercase; color: #718096; font-weight: bold; letter-spacing: 0.5px;">MONITORED URL</div>
                    <div style="font-size: 15px; color: #2b6cb0; word-break: break-all; font-weight: 600; margin-top: 4px;">{sitemap_url}</div>
                </div>

                <div style="display: flex; align-items: center; background-color: #fefcbf; border-radius: 8px; padding: 12px 16px; margin-bottom: 25px;">
                    <span style="background-color: #ecc94b; color: #744210; font-size: 11px; font-weight: 800; padding: 3px 8px; border-radius: 12px; margin-right: 12px; text-transform: uppercase;">CHANGES DETECTED</span>
                    <span style="color: #744210; font-size: 13px; font-weight: 500;">{change_summary}</span>
                </div>

                <div style="font-size: 15px; font-weight: 700; color: #2d3748; margin-bottom: 12px;">
                    Total Sitemap URLs: {total_urls}
                </div>

                {new_urls_html}
                {modified_urls_html}
                {crawl_notice}

                <div style="margin-top: 35px; padding-top: 20px; border-top: 1px solid #edf2f7; text-align: center; color: #a0aec0; font-size: 12px;">
                    <p style="margin: 0;">Automated alert generated by GSearchAI Website Monitor.</p>
                </div>
            </div>
        </div>
        """

        return await EmailService.send_email(to_email=email, subject=subject, body=body, html_body=html_body)


    @staticmethod
    async def send_welcome_email(email: str, first_name: str) -> bool:
        """Send welcome email to user after successful registration"""
        subject = "Welcome to GSearchAI! 🎉"
        body = f"Hello {first_name},\n\nWelcome to our platform! We're thrilled to have you join our community.\n\nYour account has been successfully created! You can now access all features and start using the platform.\n\nThank you for choosing us!\n\nBest regards,\nThe GSearchAi Team"
        
        html_body = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; background-color: #f9f9fb; padding: 20px;">
            <div style="background: linear-gradient(to right, #6b46c1, #805ad5); padding: 40px 30px; border-radius: 10px 10px 0 0; text-align: center; color: white;">
                <div style="font-size: 40px; margin-bottom: 15px;">🎉</div>
                <h1 style="margin: 0; font-size: 28px;">Welcome Aboard!</h1>
            </div>
            <div style="background-color: white; padding: 40px; border-radius: 0 0 10px 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
                <h2 style="color: #2d3748; margin-top: 0;">Hello {first_name},</h2>
                <p style="color: #4a5568; line-height: 1.6;">Welcome to our platform! We're thrilled to have you join our community.</p>
                
                <div style="border-left: 4px solid #6b46c1; background-color: #faf5ff; padding: 20px; border-radius: 0 8px 8px 0; margin: 30px 0;">
                    <p style="margin: 0 0 10px 0; color: #2d3748; font-weight: bold;">✓ Your account has been successfully created!</p>
                    <p style="margin: 0; color: #4a5568; font-size: 14px;">You can now access all features and start using the platform.</p>
                </div>
                
                <p style="color: #4a5568; line-height: 1.6;">Thank you for choosing us!</p>
                
                <div style="margin-top: 40px;">
                    <p style="color: #4a5568; margin: 0;">Best regards,</p>
                    <p style="color: #6b46c1; font-weight: bold; margin: 5px 0 0 0;">The GSearchAi Team</p>
                </div>
            </div>
            <div style="text-align: center; margin-top: 30px; color: #a0aec0; font-size: 12px;">
                <p>This is an automated email. Please do not reply.</p>
                <p>© 2026 GSearchAi. All rights reserved.</p>
            </div>
        </div>
        """
        
        return await EmailService.send_email(to_email=email, subject=subject, body=body, html_body=html_body)

    @staticmethod
    async def send_sitemap_monitor_alert(
        email: str,
        user_name: str,
        sitemap_url: str,
        total_urls: int,
        new_urls: list,
        modified_urls: list,
        auto_crawled: bool = True
    ) -> bool:
        """
        Send scheduled website monitor alert email detailing newly added and modified URLs.
        Matches the GCrawl alert layout.
        """
        greeting = f"Hello {user_name}," if user_name else "Hello,"
        change_summary = f"Sitemap changed: +{len(new_urls)} new URLs added, ~{len(modified_urls)} existing URLs modified. (Total: {total_urls})"

        # Build list items for new URLs
        new_urls_html = ""
        if new_urls:
            new_urls_html = """
            <div style="margin-top: 20px;">
                <h4 style="color: #27ae60; margin-bottom: 8px; font-size: 15px;">+ Newly Added URLs ({count}):</h4>
                <ul style="padding-left: 20px; margin: 0; line-height: 1.8;">
                    {items}
                </ul>
            </div>
            """.format(
                count=len(new_urls),
                items="\n".join([f'<li><a href="{u}" style="color: #2b6cb0; text-decoration: underline;" target="_blank">{u}</a></li>' for u in new_urls[:50]])
            )
            if len(new_urls) > 50:
                new_urls_html += f'<p style="color: #718096; font-size: 13px; margin-top: 5px;">...and {len(new_urls) - 50} more URLs</p>'

        # Build list items for modified URLs
        modified_urls_html = ""
        if modified_urls:
            modified_urls_html = """
            <div style="margin-top: 20px;">
                <h4 style="color: #d69e2e; margin-bottom: 8px; font-size: 15px;">~ Modified Existing URLs ({count}):</h4>
                <ul style="padding-left: 20px; margin: 0; line-height: 1.8;">
                    {items}
                </ul>
            </div>
            """.format(
                count=len(modified_urls),
                items="\n".join([f'<li><a href="{u}" style="color: #2b6cb0; text-decoration: underline;" target="_blank">{u}</a></li>' for u in modified_urls[:30]])
            )
            if len(modified_urls) > 30:
                modified_urls_html += f'<p style="color: #718096; font-size: 13px; margin-top: 5px;">...and {len(modified_urls) - 30} more URLs</p>'

        crawl_notice = ""
        if auto_crawled:
            crawl_notice = """
            <div style="background-color: #ebf8ff; border-left: 4px solid #3182ce; padding: 12px 16px; border-radius: 4px; margin-top: 25px;">
                <p style="margin: 0; color: #2b6cb0; font-size: 13px; font-weight: 500;">
                    🤖 <strong>Automatic Ingestion Active:</strong> These new URLs have been automatically queued and indexed into your Knowledge Base vector index.
                </p>
            </div>
            """

        subject = f"Website Monitor Alert: Changes detected in {sitemap_url}"
        body = f"""{greeting}\n\nYour scheduled website monitor has completed its periodic check for:\n{sitemap_url}\n\n{change_summary}\n\nNewly Added ({len(new_urls)}):\n""" + "\n".join(new_urls[:20])

        html_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 650px; margin: 0 auto; background-color: #f7fafc; padding: 25px;">
            <div style="background: white; border-radius: 12px; padding: 35px; box-shadow: 0 4px 12px rgba(0,0,0,0.06); border: 1px solid #e2e8f0;">
                <p style="font-size: 16px; color: #2d3748; font-weight: 600; margin-top: 0;">{greeting}</p>
                <p style="color: #4a5568; font-size: 14px; margin-bottom: 20px;">Your scheduled website monitor has completed its periodic check for:</p>
                
                <div style="border-left: 4px solid #3182ce; background-color: #f7fafc; padding: 15px 18px; border-radius: 0 8px 8px 0; margin-bottom: 24px;">
                    <div style="font-size: 11px; text-transform: uppercase; color: #718096; font-weight: bold; letter-spacing: 0.5px;">MONITORED URL</div>
                    <div style="font-size: 15px; color: #2b6cb0; word-break: break-all; font-weight: 600; margin-top: 4px;">{sitemap_url}</div>
                </div>

                <div style="display: flex; align-items: center; background-color: #fefcbf; border-radius: 8px; padding: 12px 16px; margin-bottom: 25px;">
                    <span style="background-color: #ecc94b; color: #744210; font-size: 11px; font-weight: 800; padding: 3px 8px; border-radius: 12px; margin-right: 12px; text-transform: uppercase;">CHANGES DETECTED</span>
                    <span style="color: #744210; font-size: 13px; font-weight: 500;">{change_summary}</span>
                </div>

                <div style="font-size: 15px; font-weight: 700; color: #2d3748; margin-bottom: 12px;">
                    Total Sitemap URLs: {total_urls}
                </div>

                {new_urls_html}
                {modified_urls_html}
                {crawl_notice}

                <div style="margin-top: 35px; padding-top: 20px; border-top: 1px solid #edf2f7; text-align: center; color: #a0aec0; font-size: 12px;">
                    <p style="margin: 0;">Automated alert generated by GSearchAI Website Monitor.</p>
                </div>
            </div>
        </div>
        """

        return await EmailService.send_email(to_email=email, subject=subject, body=body, html_body=html_body)

