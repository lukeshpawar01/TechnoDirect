"""Email one-time passcode (second login step).

Flow: POST /auth/token/ with a correct password -> a 6-digit code is emailed and a challenge id returned;
POST /auth/otp/verify/ {challenge_id, code} -> {access, refresh}. Mail goes through Django's SMTP backend
(EMAIL_* settings, Gmail by default).
"""
import datetime as dt
import hashlib
import hmac
import logging
import secrets

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from django.utils.html import escape

from .models import LoginOtp

log = logging.getLogger(__name__)


class OtpError(Exception):
    def __init__(self, message, code="invalid", status=400, extra=None):
        super().__init__(message)
        self.message, self.code, self.status, self.extra = message, code, status, extra or {}


def _hash(challenge_id, code):
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, f"{challenge_id}:{code}".encode(), hashlib.sha256).hexdigest()


def _new_code():
    return f"{secrets.randbelow(10 ** 6):06d}"


def mask_email(email):
    name, _, domain = email.partition("@")
    shown = name[:2] if len(name) > 2 else name[:1]
    return f"{shown}{'*' * max(1, len(name) - len(shown))}@{domain}"


def _send(user, code):
    ttl = settings.LOGIN_OTP_TTL_MINUTES
    subject = f"{code} is your TechnoDirect Dashboard login code"
    text = (f"Hello {user.full_name or user.email},\n\n"
            f"Your TechnoDirect Dashboard login code is: {code}\n\n"
            f"It expires in {ttl} minutes. If you did not try to sign in, ignore this email and tell your admin.\n")
    html = (f"<div style=\"font-family:Arial,sans-serif;font-size:14px;color:#1f2937\">"
            f"<p>Hello {escape(user.full_name or user.email)},</p>"
            f"<p>Your TechnoDirect Dashboard login code is:</p>"
            f"<p style=\"font-size:28px;font-weight:bold;letter-spacing:6px;margin:16px 0\">{code}</p>"
            f"<p>It expires in {ttl} minutes. If you did not try to sign in, ignore this email and tell your admin.</p>"
            f"</div>")
    msg = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [user.email])
    msg.attach_alternative(html, "text/html")
    try:
        msg.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 - SMTP / network errors
        log.exception("Login OTP email to %s failed", user.email)
        raise OtpError("Could not send the login code email. Please try again or contact your admin.",
                       code="email_failed", status=503) from exc


def _public(otp):
    now = timezone.now()
    wait = settings.LOGIN_OTP_RESEND_SECONDS - (now - otp.last_sent_at).total_seconds()
    return {"otp_required": True, "challenge_id": otp.challenge_id, "email": mask_email(otp.user.email),
            "expires_in": max(0, int((otp.expires_at - now).total_seconds())),
            "resend_in": max(0, int(wait)),
            "resends_left": max(0, settings.LOGIN_OTP_MAX_SENDS - otp.sends)}


def start_challenge(user, ip=None):
    """Create a challenge for a user whose password was just verified, and email the code."""
    now = timezone.now()
    # one live challenge per user
    LoginOtp.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
    cid = secrets.token_urlsafe(32)
    code = _new_code()
    otp = LoginOtp.objects.create(
        challenge_id=cid, user=user, code_hash=_hash(cid, code), last_sent_at=now, ip=ip,
        expires_at=now + dt.timedelta(minutes=settings.LOGIN_OTP_TTL_MINUTES))
    _send(user, code)
    return _public(otp)


def _live(challenge_id):
    otp = LoginOtp.objects.select_related("user").filter(challenge_id=str(challenge_id or "")).first()
    if otp is None or otp.used_at is not None or not otp.user.is_active:
        raise OtpError("This sign-in request is no longer valid. Please sign in again.", code="restart")
    return otp


def resend(challenge_id):
    otp = _live(challenge_id)
    now = timezone.now()
    if otp.sends >= settings.LOGIN_OTP_MAX_SENDS:
        raise OtpError("Too many codes sent. Please sign in again.", code="restart")
    wait = settings.LOGIN_OTP_RESEND_SECONDS - (now - otp.last_sent_at).total_seconds()
    if wait > 0:
        raise OtpError(f"Please wait {int(wait) + 1} seconds before requesting a new code.", code="too_soon",
                       status=429, extra={"resend_in": int(wait) + 1})
    code = _new_code()
    otp.code_hash = _hash(otp.challenge_id, code)
    otp.attempts = 0
    otp.sends += 1
    otp.last_sent_at = now
    otp.expires_at = now + dt.timedelta(minutes=settings.LOGIN_OTP_TTL_MINUTES)
    otp.save(update_fields=["code_hash", "attempts", "sends", "last_sent_at", "expires_at"])
    _send(otp.user, code)
    return _public(otp)


def verify(challenge_id, code):
    """Return the user when the code is right; raise OtpError otherwise."""
    otp = _live(challenge_id)
    now = timezone.now()
    if now >= otp.expires_at:
        raise OtpError("This code has expired. Request a new one.", code="expired")
    if otp.attempts >= settings.LOGIN_OTP_MAX_ATTEMPTS:
        otp.used_at = now
        otp.save(update_fields=["used_at"])
        raise OtpError("Too many wrong codes. Please sign in again.", code="restart")
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(code) != 6 or not hmac.compare_digest(otp.code_hash, _hash(otp.challenge_id, code)):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        left = settings.LOGIN_OTP_MAX_ATTEMPTS - otp.attempts
        if left <= 0:
            otp.used_at = now
            otp.save(update_fields=["used_at"])
            raise OtpError("Too many wrong codes. Please sign in again.", code="restart")
        raise OtpError(f"Incorrect code. {left} attempt{'s' if left != 1 else ''} left.", code="invalid",
                       extra={"attempts_left": left})
    otp.used_at = now
    otp.save(update_fields=["used_at"])
    return otp.user
