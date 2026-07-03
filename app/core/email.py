"""Email service - handles sending system emails (auth, alerts, notifications)"""

import logging
from typing import Optional
from pydantic import EmailStr
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from .config import get_settings

from datetime import datetime

logger = logging.getLogger(__name__)
settings = get_settings()

last_alert_sent = {}


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
                <p>© 2026 GRAG. All rights reserved.</p>
            </div>
        </div>
        """
        
        return await EmailService.send_email(to_email=email, subject=subject, body=body, html_body=html_body)

    @staticmethod
    async def send_registration_otp_email(email: str, otp: str, first_name: str = None) -> bool:
        """Send registration OTP to user"""
        subject = "GRAG - Registration Verification Code"
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
                <p>© 2026 GRAG. All rights reserved.</p>
            </div>
        </div>
        """
        
        return await EmailService.send_email(to_email=email, subject=subject, body=body, html_body=html_body)

    @staticmethod
    async def send_welcome_email(email: str, first_name: str) -> bool:
        """Send welcome email to user after successful registration"""
        subject = "Welcome to GRAG! 🎉"
        body = f"Hello {first_name},\n\nWelcome to our platform! We're thrilled to have you join our community.\n\nYour account has been successfully created! You can now access all features and start using the platform.\n\nThank you for choosing us!\n\nBest regards,\nThe GRAG Team"
        
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
                    <p style="color: #6b46c1; font-weight: bold; margin: 5px 0 0 0;">The GRAG Team</p>
                </div>
            </div>
            <div style="text-align: center; margin-top: 30px; color: #a0aec0; font-size: 12px;">
                <p>This is an automated email. Please do not reply.</p>
                <p>© 2026 GRAG. All rights reserved.</p>
            </div>
        </div>
        """
        
        return await EmailService.send_email(to_email=email, subject=subject, body=body, html_body=html_body)

    @staticmethod
    async def send_admin_alert_email(error_type: str, details: dict) -> bool:
        """
        Send a production-grade alert to the admin email with rate limiting.
        """
        global last_alert_sent
        admin_email = getattr(settings, "admin_alert_email", None)
        if not admin_email:
            logger.warning(f"Admin alert suppressed: no admin_alert_email configured. Error: {error_type}")
            return False

        now = datetime.now().timestamp()
        if now - last_alert_sent.get(error_type, 0) < 300:
            logger.info(f"Admin alert throttled for {error_type}. Sent within last 5 minutes.")
            return False

        last_alert_sent[error_type] = now
        
        subject = f"[GraphMind Alert] AI Service Disruption: {error_type}"
        
        # Build HTML Body
        html_details = "".join(f"<tr><td style='padding:8px; border-bottom: 1px solid #e2e8f0; font-weight:bold; color:#4a5568;'>{k}</td><td style='padding:8px; border-bottom: 1px solid #e2e8f0; color:#2d3748;'>{v}</td></tr>" for k, v in details.items())
        
        html_body = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 700px; margin: 0 auto; background-color: #fff5f5; border: 1px solid #feb2b2; border-radius: 8px; overflow: hidden;">
            <div style="background-color: #e53e3e; padding: 20px; text-align: center; color: white;">
                <h1 style="margin: 0; font-size: 22px;">⚠️ Critical System Alert</h1>
            </div>
            <div style="padding: 30px;">
                <p style="color: #c53030; font-size: 16px; font-weight: bold;">An AI Service Disruption was detected.</p>
                
                <table style="width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 14px; background-color: white; border: 1px solid #e2e8f0; border-radius: 6px;">
                    {html_details}
                </table>
                
                <div style="margin-top: 30px; padding: 15px; background-color: #ebf8ff; border-left: 4px solid #3182ce; color: #2b6cb0; font-size: 13px;">
                    This alert is rate-limited and will not be triggered again for this specific error type for the next 5 minutes.
                </div>
            </div>
            <div style="text-align: center; padding: 15px; background-color: #f7fafc; color: #a0aec0; font-size: 12px; border-top: 1px solid #e2e8f0;">
                <p style="margin: 0;">Automated Alert • GraphMind Production System</p>
            </div>
        </div>
        """
        
        # Fallback text
        body = f"AI Service Disruption: {error_type}\n\nDetails:\n" + "\n".join(f"{k}: {v}" for k, v in details.items())
        
        logger.info(f"Sending admin alert to {admin_email} for {error_type}")
        return await EmailService.send_email(to_email=admin_email, subject=subject, body=body, html_body=html_body)
