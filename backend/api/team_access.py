import re
import secrets
import smtplib
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

from . import models as m
from . import services as svc


def normalize_permissions(value):
    if not isinstance(value, dict) or set(value) - set(m.TEAM_PERMISSION_SCOPES):
        raise svc.ServiceError("Choose valid team permissions.")
    normalized = {}
    for scope in m.TEAM_PERMISSION_SCOPES:
        actions = value.get(scope, {})
        if not isinstance(actions, dict) or set(actions) - {"view", "edit"}:
            raise svc.ServiceError("Choose valid team permissions.")
        view = actions.get("view", False)
        edit = actions.get("edit", False)
        if not isinstance(view, bool) or not isinstance(edit, bool) or (edit and not view):
            raise svc.ServiceError("Edit access requires view access.")
        normalized[scope] = {"view": view, "edit": edit}
    return normalized


def has_permission(membership, scope, edit=False):
    if membership is None:
        return True
    actions = membership.permissions.get(scope, {})
    return bool(actions.get("edit" if edit else "view"))


def resolve_workspace(user, workspace_id=None):
    if workspace_id in (None, "") or str(workspace_id) == str(user.pk):
        return user, None
    if (
        not isinstance(workspace_id, str) or len(workspace_id) > 20
        or not workspace_id.isascii() or not workspace_id.isdecimal()
    ):
        raise svc.ServiceError("Choose a valid business workspace.", 400)
    membership = m.TeamMembership.objects.select_related("owner").filter(
        member=user, owner_id=int(workspace_id),
        owner__preferences__team_sharing_enabled=True,
    ).first()
    if membership is None:
        raise svc.ServiceError("You no longer have access to that business workspace.", 403)
    return membership.owner, membership


def workspaces_for_user(user):
    own_settings = m.UserSettings.objects.filter(owner=user).first()
    own_name = own_settings.business_name if own_settings else ""
    workspaces = [{
        "id": user.pk,
        "name": own_name or user.username,
        "role": "owner",
        "permissions": {scope: {"view": True, "edit": True} for scope in m.TEAM_PERMISSION_SCOPES},
        "can_manage_members": True,
    }]
    memberships = m.TeamMembership.objects.select_related("owner").filter(
        member=user, owner__preferences__team_sharing_enabled=True,
    ).order_by("owner_id")
    for membership in memberships:
        business = m.UserSettings.objects.filter(owner=membership.owner).only("business_name").first()
        workspaces.append({
            "id": membership.owner_id,
            "name": (business.business_name if business else "") or membership.owner.username,
            "role": "member",
            "permissions": normalize_permissions(membership.permissions),
            "can_manage_members": membership.can_manage_members,
        })
    return workspaces


def select_workspace(user, requested_id):
    owner, _ = resolve_workspace(user, requested_id)
    return owner


def set_sharing(owner, enabled):
    if not isinstance(enabled, bool):
        raise svc.ServiceError("team_sharing_enabled must be true or false.")
    with transaction.atomic():
        prefs = m.UserSettings.objects.select_for_update().get(owner=owner)
        if prefs.team_sharing_enabled == enabled:
            return
        prefs.team_sharing_enabled = enabled
        prefs.save(update_fields=["team_sharing_enabled"])
        if not enabled:
            m.TeamMembership.objects.filter(owner=owner).delete()
            m.TeamInvitation.objects.filter(owner=owner).delete()


def _validated_email(email):
    if not isinstance(email, str):
        raise svc.ServiceError("Enter a valid email address.")
    email = email.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        raise svc.ServiceError("Enter a valid email address.")
    return email


def create_invitation(owner, actor, email, permissions, can_manage_members):
    email = _validated_email(email)
    permissions = normalize_permissions(permissions)
    if not isinstance(can_manage_members, bool):
        raise svc.ServiceError("can_manage_members must be true or false.")
    if email == owner.email.strip().lower():
        raise svc.ServiceError("The business owner is already a member.")
    if not svc.email_delivery_configured():
        raise svc.ServiceError("Secure email delivery is not configured.", 503)
    if svc._rate_limit_hit(f"team-invite:{owner.pk}", 10, 3600):
        raise svc.ServiceError("Too many invitations sent. Try again later.", 429)

    raw_token = secrets.token_urlsafe(32)
    now = timezone.now()
    base = settings.FRONTEND_URL.split("#", 1)[0]
    try:
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=owner.pk)
            prefs = m.UserSettings.objects.select_for_update().get(owner=owner)
            if not prefs.team_sharing_enabled:
                raise svc.ServiceError("Enable team sharing before inviting members.")
            if not prefs.email_verified:
                raise svc.ServiceError("Verify the business owner's email before sending invitations.", 403)
            if svc.users_with_email(email).filter(business_memberships__owner=owner).exists():
                raise svc.ServiceError("That person is already a member of this business.", 409)
            if actor.pk != owner.pk:
                actor_membership = m.TeamMembership.objects.select_for_update().filter(
                    owner=owner, member=actor,
                ).first()
                if not actor_membership or not actor_membership.can_manage_members:
                    raise svc.ServiceError("You are not allowed to manage this business's team.", 403)
                if can_manage_members:
                    raise svc.ServiceError("Only the business owner can grant team-management access.", 403)
                actor_permissions = normalize_permissions(actor_membership.permissions)
                for scope in m.TEAM_PERMISSION_SCOPES:
                    if permissions[scope]["view"] and not actor_permissions[scope]["view"]:
                        raise svc.ServiceError("You cannot grant permissions you do not have.", 403)
                    if permissions[scope]["edit"] and not actor_permissions[scope]["edit"]:
                        raise svc.ServiceError("You cannot grant permissions you do not have.", 403)
            link = f"{base}#team_invite={raw_token}"
            business_name = prefs.business_name or owner.username
            m.TeamInvitation.objects.filter(
                owner=owner, email=email, accepted_at__isnull=True,
            ).update(accepted_at=now)
            invitation = m.TeamInvitation.objects.create(
                owner=owner, email=email, token_hash=svc._hash(raw_token),
                permissions=permissions, can_manage_members=can_manage_members,
                expires_at=now + timedelta(days=7),
            )
            sent = svc._send_email(
                f"Invitation to join {business_name} on Nexa",
                f"You were invited to join {business_name} on Nexa.\n\n"
                f"Open this link to sign in or create your own account and accept the invitation:\n{link}\n\n"
                "The invitation expires in 7 days. If you did not expect it, ignore this email.",
                settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False,
            )
            if sent != 1:
                raise OSError("Email backend did not confirm delivery.")
    except svc.ServiceError:
        raise
    except (OSError, smtplib.SMTPException, ValueError) as error:
        svc.logger.exception("Could not send business team invitation")
        raise svc.ServiceError("The invitation could not be sent. Try again later.", 503) from error
    return invitation


def invitation_preview(raw_token):
    if not isinstance(raw_token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,100}", raw_token):
        raise svc.ServiceError("This invitation is invalid or has expired.", 404)
    invitation = m.TeamInvitation.objects.select_related("owner").filter(
        token_hash=svc._hash(raw_token), accepted_at__isnull=True, expires_at__gt=timezone.now(),
        owner__preferences__team_sharing_enabled=True,
    ).first()
    if invitation is None:
        raise svc.ServiceError("This invitation is invalid or has expired.", 404)
    prefs = m.UserSettings.objects.filter(owner=invitation.owner).only("business_name").first()
    return {
        "email": invitation.email,
        "business_name": (prefs.business_name if prefs else "") or invitation.owner.username,
        "expires_at": invitation.expires_at,
    }


@transaction.atomic
def accept_invitation(user, raw_token):
    if not isinstance(raw_token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,100}", raw_token):
        raise svc.ServiceError("This invitation is invalid or has expired.", 404)
    invitation = m.TeamInvitation.objects.select_for_update().filter(
        token_hash=svc._hash(raw_token), accepted_at__isnull=True, expires_at__gt=timezone.now(),
        owner__preferences__team_sharing_enabled=True,
    ).first()
    if invitation is None:
        raise svc.ServiceError("This invitation is invalid or has expired.", 404)
    if user.email.strip().lower() != invitation.email:
        raise svc.ServiceError("Sign in with the email address this invitation was sent to.", 403)
    if not user.is_active:
        raise svc.ServiceError("This account is inactive.", 403)
    if invitation.owner_id == user.pk:
        raise svc.ServiceError("A business owner cannot accept their own invitation.")
    try:
        membership, created = m.TeamMembership.objects.get_or_create(
            owner=invitation.owner, member=user,
            defaults={
                "permissions": normalize_permissions(invitation.permissions),
                "can_manage_members": invitation.can_manage_members,
            },
        )
    except IntegrityError:
        membership = m.TeamMembership.objects.filter(owner=invitation.owner, member=user).first()
        if membership is None:
            raise
        created = False
    if not created:
        raise svc.ServiceError("This account is already a member of the business.", 409)
    prefs, _ = m.UserSettings.objects.get_or_create(owner=user)
    if not prefs.email_verified:
        prefs.email_verified = True
        prefs.save(update_fields=["email_verified"])
    now = timezone.now()
    invitation.accepted_at = now
    invitation.save(update_fields=["accepted_at"])
    m.TeamInvitation.objects.filter(
        owner=invitation.owner, email=invitation.email, accepted_at__isnull=True,
    ).update(accepted_at=now)
    return invitation.owner


def list_team(owner, actor=None):
    memberships = list(
        m.TeamMembership.objects.select_related("member").filter(owner=owner).order_by("created_at", "id")
    )
    return [{
        "id": membership.id,
        "username": membership.member.username,
        "email": membership.member.email,
        "created_at": membership.created_at,
        "permissions": normalize_permissions(membership.permissions),
        "can_manage_members": membership.can_manage_members,
        "is_current_user": actor is not None and membership.member_id == actor.pk,
    } for membership in memberships]


@transaction.atomic
def update_member(owner, actor, membership_id, permissions, can_manage_members):
    permissions = normalize_permissions(permissions)
    if not isinstance(can_manage_members, bool):
        raise svc.ServiceError("can_manage_members must be true or false.")
    actor_membership = None
    if actor.pk != owner.pk:
        actor_membership = m.TeamMembership.objects.select_for_update().filter(
            owner=owner, member=actor,
        ).first()
        if not actor_membership or not actor_membership.can_manage_members:
            raise svc.ServiceError("You are not allowed to manage this business's team.", 403)
    membership = m.TeamMembership.objects.select_for_update().filter(
        owner=owner, pk=membership_id,
    ).first()
    if membership is None:
        raise svc.ServiceError("That team member no longer exists.", 404)
    if actor.pk != owner.pk:
        if membership.can_manage_members or membership.member_id == actor.pk or can_manage_members:
            raise svc.ServiceError("Only the business owner can change team administrators.", 403)
        actor_permissions = normalize_permissions(actor_membership.permissions)
        for scope in m.TEAM_PERMISSION_SCOPES:
            if permissions[scope]["view"] and not actor_permissions[scope]["view"]:
                raise svc.ServiceError("You cannot grant permissions you do not have.", 403)
            if permissions[scope]["edit"] and not actor_permissions[scope]["edit"]:
                raise svc.ServiceError("You cannot grant permissions you do not have.", 403)
    membership.permissions = permissions
    membership.can_manage_members = can_manage_members
    membership.save(update_fields=["permissions", "can_manage_members"])
    return membership


@transaction.atomic
def remove_member(owner, actor, membership_id):
    actor_membership = None
    if actor.pk != owner.pk:
        actor_membership = m.TeamMembership.objects.select_for_update().filter(
            owner=owner, member=actor,
        ).first()
        if not actor_membership or not actor_membership.can_manage_members:
            raise svc.ServiceError("You are not allowed to remove this team member.", 403)
    membership = m.TeamMembership.objects.select_for_update().filter(owner=owner, pk=membership_id).first()
    if membership is None:
        raise svc.ServiceError("That team member no longer exists.", 404)
    if actor.pk != owner.pk:
        if (
            membership.can_manage_members or membership.member_id == actor.pk
        ):
            raise svc.ServiceError("You are not allowed to remove this team member.", 403)
    membership.delete()


@transaction.atomic
def cancel_invitation(owner, invitation_id):
    invitation = m.TeamInvitation.objects.select_for_update().filter(
        owner=owner, pk=invitation_id, accepted_at__isnull=True,
    ).first()
    if invitation is None:
        raise svc.ServiceError("That invitation no longer exists.", 404)
    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at"])
