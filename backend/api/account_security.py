import re
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from . import models as m
from . import services as svc


def _code_hash(challenge_id, code):
    return salted_hmac("nexa.account-security", f"{challenge_id}:{code}", algorithm="sha256").hexdigest()


def _send_code(email, code):
    try:
        sent = svc._send_email(
            "Your Nexa security code",
            f"Your Nexa security code is {code}. It expires in 10 minutes.\n\n"
            "If you did not request this, do not share the code.",
            svc.settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False,
        )
        if sent != 1:
            raise OSError("Email backend did not confirm delivery.")
    except (OSError, svc.smtplib.SMTPException, ValueError) as error:
        svc.logger.exception("Could not send account security code")
        raise svc.ServiceError("The security code could not be sent. Try again later.", 503) from error


def _session(owner, token):
    session = m.ApiToken.objects.filter(
        user=owner, key_hash=svc._hash(token), expires_at__gt=timezone.now(),
    ).first()
    if not session:
        raise svc.ServiceError("Your session has expired. Sign in again.", 401)
    return session


def change_username(owner, username):
    username = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", username):
        raise svc.ServiceError("Username must be 3 to 30 ASCII letters, numbers, dots, dashes or underscores.")
    User = get_user_model()
    if User.objects.exclude(pk=owner.pk).filter(username__iexact=username).exists():
        raise svc.ServiceError("That username is already in use.", 409)
    try:
        with transaction.atomic():
            owner.username = username
            owner.save(update_fields=["username"])
    except IntegrityError:
        if User.objects.exclude(pk=owner.pk).filter(username__iexact=username).exists():
            raise svc.ServiceError("That username is already in use.", 409)
        raise
    return username


def request_code(owner, token, action, target):
    if action not in ("email", "password", "device"):
        raise svc.ServiceError("Choose a valid account action.")
    if not owner.email or not owner.preferences.email_verified:
        raise svc.ServiceError("Verify your current account email before using security codes.", 403)
    if not svc.email_delivery_configured():
        raise svc.ServiceError("Secure email delivery is not configured.", 503)
    session = _session(owner, token)
    if action == "email":
        target = target.strip().lower()
        try:
            validate_email(target)
        except ValidationError:
            raise svc.ServiceError("Enter a valid new email address.")
        if target == owner.email.strip().lower():
            raise svc.ServiceError("Enter a different email address.")
        if svc.users_with_email(target).exists():
            raise svc.ServiceError("That email address is already in use.", 409)
    elif action == "device":
        if not target.isascii() or not target.isdecimal():
            raise svc.ServiceError("Choose a valid session.")
        if not m.ApiToken.objects.filter(user=owner, pk=int(target), expires_at__gt=timezone.now()).exclude(pk=session.pk).exists():
            raise svc.ServiceError("That session is no longer available.", 404)
    else:
        target = ""
    if svc._rate_limit_hit(f"account-security:send:{owner.pk}", 5, 3600):
        raise svc.ServiceError("Too many security codes requested. Try again later.", 429)
    code = f"{secrets.randbelow(1000000):06d}"
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=owner.pk)
        m.AccountSecurityChallenge.objects.filter(owner=owner, session=session).delete()
        challenge = m.AccountSecurityChallenge.objects.create(
            owner=owner, session=session, action=action, target=target,
            email_snapshot=owner.email.strip().lower(), code_hash="",
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        challenge.code_hash = _code_hash(challenge.pk, code)
        challenge.save(update_fields=["code_hash"])
        _send_code(owner.email, code)


def confirm_code(owner, token, action, code, password="", password2=""):
    session = _session(owner, token)
    if not re.fullmatch(r"[0-9]{6}", code):
        raise svc.ServiceError("Enter the six-digit security code.")
    invalid = False
    result = None
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().get(pk=owner.pk)
        challenge = m.AccountSecurityChallenge.objects.select_for_update().filter(
            owner=user, session=session, action=action,
        ).first()
        if (
            not challenge or challenge.expires_at <= timezone.now() or challenge.attempts >= 5
            or challenge.email_snapshot != user.email.strip().lower()
        ):
            raise svc.ServiceError("This security code is invalid or expired. Request a new one.")
        if not constant_time_compare(challenge.code_hash, _code_hash(challenge.pk, code)):
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            invalid = True
        elif action == "email" and challenge.stage == "current":
            new_code = f"{secrets.randbelow(1000000):06d}"
            while constant_time_compare(challenge.code_hash, _code_hash(challenge.pk, new_code)):
                new_code = f"{secrets.randbelow(1000000):06d}"
            _send_code(challenge.target, new_code)
            challenge.stage = "new"
            challenge.code_hash = _code_hash(challenge.pk, new_code)
            challenge.expires_at = timezone.now() + timedelta(minutes=10)
            challenge.attempts = 0
            challenge.save(update_fields=["stage", "code_hash", "expires_at", "attempts"])
            result = "new_email"
        elif action == "email":
            if svc.users_with_email(challenge.target).exclude(pk=user.pk).exists():
                raise svc.ServiceError("That email address is already in use.", 409)
            old_email = user.email.strip().lower()
            try:
                with transaction.atomic():
                    user.email = challenge.target
                    user.save(update_fields=["email"])
            except IntegrityError:
                raise svc.ServiceError("That email address is already in use.", 409)
            m.MagicLink.objects.filter(email__in=[old_email, challenge.target], used_at__isnull=True).delete()
            m.PasswordResetToken.objects.filter(owner=user, used_at__isnull=True).update(used_at=timezone.now())
            m.AccountActionToken.objects.filter(owner=user, used_at__isnull=True).update(used_at=timezone.now())
            m.ApiToken.objects.filter(user=user).exclude(pk=session.pk).delete()
            m.AccountSecurityChallenge.objects.filter(owner=user).delete()
            result = "email_changed"
        elif action == "password":
            if not password or password != password2:
                raise svc.ServiceError("Enter matching new passwords.")
            try:
                validate_password(password, user)
            except ValidationError as error:
                raise svc.ServiceError(" ".join(error.messages))
            user.set_password(password)
            user.save(update_fields=["password"])
            m.PasswordResetToken.objects.filter(owner=user, used_at__isnull=True).update(used_at=timezone.now())
            m.AccountActionToken.objects.filter(owner=user, used_at__isnull=True).update(used_at=timezone.now())
            m.MagicLink.objects.filter(email__iexact=user.email.strip(), used_at__isnull=True).delete()
            m.ApiToken.objects.filter(user=user).delete()
            result = "password_changed"
        elif action == "device":
            deleted, _ = m.ApiToken.objects.filter(user=user, pk=int(challenge.target)).exclude(pk=session.pk).delete()
            if not deleted:
                raise svc.ServiceError("That session is no longer available.", 404)
            challenge.delete()
            result = "device_signed_out"
        else:
            raise svc.ServiceError("Choose a valid account action.")
    if invalid:
        raise svc.ServiceError("This security code is invalid or expired. Request a new one.")
    return result
