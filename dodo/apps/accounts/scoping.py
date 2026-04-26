"""
apps/accounts/scoping.py

Single source of truth for scope and role checks.

Key rules (revised):

    1. A user's access to a country office is recorded in UserCountryAccess.
    2. UserCountryAccess.unit is the cornerstone:
         - NULL  -> CO-level access (central M&E office, CO admin, etc.)
         - SET   -> unit-attached; this user is restricted to that unit
    3. A user can hold multiple UserCountryAccess rows. The visible scope
       is the UNION across all active rows in the active CO.
    4. Logical roles (admin, M&E officer, tracker editor) are configured in
       MERoleConfig at runtime, not hardcoded.
    5. The tracker has a special rule: only users whose triggering
       permissions are EXCLUSIVELY held at CO-level (unit=NULL) qualify as
       "central" tracker editors who see everything. Users with the same
       permission but only via a unit-attached access row are unit-scoped.
"""
from collections import defaultdict

from django.db.models import Q

from .models import (
    ModulePermission, UserCountryAccess, MERoleConfig,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _co_id(co):
    """Accept a CO instance or an id; return id or None."""
    if co is None:
        return None
    return getattr(co, 'pk', co)


def _user_access_rows(user, co):
    """Active UserCountryAccess rows for this user in the given CO."""
    if not user or not user.is_authenticated:
        return UserCountryAccess.objects.none()
    qs = UserCountryAccess.objects.filter(user=user, is_active=True).select_related('role', 'unit')
    cid = _co_id(co)
    if cid is not None:
        qs = qs.filter(country_office_id=cid)
    return qs


def _permissions_held(user, co):
    """
    Returns {(module, action): {co_level_seen, unit_ids_seen}} for this user.

    co_level_seen = True if the perm came via at least one access row with unit=NULL
    unit_ids_seen = set of unit ids where the perm was held via unit-attached rows
    """
    held = defaultdict(lambda: {'co_level': False, 'units': set()})
    rows = _user_access_rows(user, co).values_list('role_id', 'unit_id')
    if not rows:
        return held

    role_to_units = defaultdict(lambda: {'co_level': False, 'units': set()})
    for role_id, unit_id in rows:
        if unit_id is None:
            role_to_units[role_id]['co_level'] = True
        else:
            role_to_units[role_id]['units'].add(unit_id)

    perms = ModulePermission.objects.filter(
        role_id__in=role_to_units.keys()
    ).values_list('role_id', 'module', 'action')

    for role_id, module, action in perms:
        bucket = held[(module, action)]
        if role_to_units[role_id]['co_level']:
            bucket['co_level'] = True
        bucket['units'] |= role_to_units[role_id]['units']
    return held


def _is_global(user):
    return bool(user and user.is_authenticated and (user.is_superuser or getattr(user, 'is_global_admin', False)))


# ---------------------------------------------------------------------------
# Logical role detection (config-driven)
# ---------------------------------------------------------------------------

def _logical_role_match(user, co, logical_role):
    """
    Does the user qualify for `logical_role` in this CO, per MERoleConfig?

    Returns one of: 'no', 'co_level', 'unit_scoped'
        no          - user does not hold the logical role
        co_level    - user holds it at CO level (unit=NULL access row)
        unit_scoped - user holds it but only via unit-attached access
    """
    if _is_global(user):
        return 'co_level'

    try:
        config = MERoleConfig.objects.get(logical_role=logical_role, is_active=True)
    except MERoleConfig.DoesNotExist:
        return 'no'

    triggers = []
    for raw in config.triggering_permissions or []:
        if ':' in raw:
            mod, act = raw.split(':', 1)
            triggers.append((mod.strip(), act.strip()))
    if not triggers:
        return 'no'

    held = _permissions_held(user, co)
    co_level_match = any(held[t]['co_level'] for t in triggers if t in held)
    unit_match = any(held[t]['units'] for t in triggers if t in held)

    if config.co_level_only:
        return 'co_level' if co_level_match else 'no'
    if co_level_match:
        return 'co_level'
    if unit_match:
        return 'unit_scoped'
    return 'no'


def is_global_admin(user):
    return _is_global(user)


def is_admin(user, co=None):
    return _logical_role_match(user, co, 'admin') == 'co_level'


def is_me_officer(user, co=None):
    """Central M&E officer — must be CO-level (no unit attachment)."""
    if is_admin(user, co):
        return True
    return _logical_role_match(user, co, 'me_officer') == 'co_level'


def is_unit_head(user, co=None):
    """User leads at least one ProgrammeUnit in this CO."""
    if not user or not user.is_authenticated:
        return False
    from apps.projects.models import ProgrammeUnit
    qs = ProgrammeUnit.objects.filter(lead=user, is_active=True)
    cid = _co_id(co)
    if cid is not None:
        qs = qs.filter(country_office_id=cid)
    return qs.exists()


# ---------------------------------------------------------------------------
# The tracker rules — what the user explicitly asked for
# ---------------------------------------------------------------------------

def tracker_access(user, co):
    """
    Returns one of:
        'global'  - admin / M&E officer / global admin: sees & edits ALL units
        'unit'    - tracker editor with unit attachment OR unit head: sees &
                    edits only their own unit(s)
        'none'    - cannot use the tracker

    This is the canonical answer for "who can see/use the tracker."
    """
    if _is_global(user):
        return 'global'
    if is_admin(user, co) or is_me_officer(user, co):
        return 'global'

    # Tracker-editor permission: CO-level wins; unit-attached gets unit scope
    role = _logical_role_match(user, co, 'tracker_editor')
    if role == 'co_level':
        return 'global'
    if role == 'unit_scoped':
        return 'unit'

    # Unit heads can use the tracker on their own unit even without an
    # explicit tracker_editor permission, since they own the unit's data.
    if is_unit_head(user, co):
        return 'unit'
    return 'none'


def can_edit_tracker(user, co=None):
    return tracker_access(user, co) != 'none'


def can_comment(user, co=None):
    if _is_global(user):
        return True
    return _logical_role_match(user, co, 'comment_author') in ('co_level', 'unit_scoped') \
        or is_unit_head(user, co)


def role_label(user, co=None):
    """Short label for UI hints. First match wins."""
    if is_admin(user, co):
        return 'admin'
    if is_me_officer(user, co):
        return 'me_officer'
    access = tracker_access(user, co)
    if access == 'unit':
        return 'unit_editor' if not is_unit_head(user, co) else 'unit_head'
    if is_unit_head(user, co):
        return 'unit_head'
    return 'viewer'


# ---------------------------------------------------------------------------
# Scope queries — the units and projects a user can see
# ---------------------------------------------------------------------------

def user_units(user, co):
    """
    Programme units this user can SEE.

    - global / admin / M&E officer -> all active units in the CO
    - unit-scoped tracker editor   -> the units on their attached access rows
    - unit head                    -> the units they lead
    - everyone else                -> none
    """
    from apps.projects.models import ProgrammeUnit
    cid = _co_id(co)
    if not user or not user.is_authenticated or cid is None:
        return ProgrammeUnit.objects.none()

    if tracker_access(user, co) == 'global':
        return ProgrammeUnit.objects.filter(country_office_id=cid, is_active=True)

    unit_ids = set(
        _user_access_rows(user, co)
        .exclude(unit__isnull=True)
        .values_list('unit_id', flat=True)
    )
    led_ids = set(
        ProgrammeUnit.objects
        .filter(country_office_id=cid, lead=user, is_active=True)
        .values_list('id', flat=True)
    )
    all_ids = unit_ids | led_ids
    if not all_ids:
        return ProgrammeUnit.objects.none()
    return ProgrammeUnit.objects.filter(id__in=all_ids, is_active=True)


def user_projects(user, co):
    from apps.projects.models import Project
    cid = _co_id(co)
    if not user or not user.is_authenticated or cid is None:
        return Project.objects.none()
    if tracker_access(user, co) == 'global':
        return Project.objects.filter(country_office_id=cid)
    units = user_units(user, co)
    if not units.exists():
        return Project.objects.none()
    return Project.objects.filter(country_office_id=cid, programme_unit__in=units)


def user_can_see_unit(user, unit):
    if not user or not user.is_authenticated or unit is None:
        return False
    if _is_global(user):
        return True
    co = unit.country_office
    if tracker_access(user, co) == 'global':
        return True
    return user_units(user, co).filter(pk=unit.pk).exists()


def user_can_see_project(user, project):
    if not user or not user.is_authenticated or project is None:
        return False
    if _is_global(user):
        return True
    co = project.country_office
    if tracker_access(user, co) == 'global':
        return True
    if project.programme_unit_id is None:
        return False
    return user_units(user, co).filter(pk=project.programme_unit_id).exists()


def user_can_edit_tracker_for(user, project_or_unit):
    """
    Specific check for tracker writes. M&E officers / admins can edit any
    project/unit in the CO; unit-scoped editors can only edit within their
    units.
    """
    if hasattr(project_or_unit, 'programme_unit'):
        unit = project_or_unit.programme_unit
        co = project_or_unit.country_office
    else:
        unit = project_or_unit
        co = project_or_unit.country_office

    access = tracker_access(user, co)
    if access == 'global':
        return True
    if access == 'none' or unit is None:
        return False
    return user_units(user, co).filter(pk=unit.pk).exists()


# ---------------------------------------------------------------------------
# Notification recipients
# ---------------------------------------------------------------------------

def project_notification_recipients(project, exclude_user=None):
    """
    Who gets emailed when something happens on this project?

    - Unit lead
    - Project manager
    - Anyone with M&E-officer logical role at CO level

    Deduplicated; excludes the actor when supplied.
    """
    from .models import User
    user_ids = set()
    if project.programme_unit and project.programme_unit.lead_id:
        user_ids.add(project.programme_unit.lead_id)
    if project.project_manager_id:
        user_ids.add(project.project_manager_id)

    try:
        config = MERoleConfig.objects.get(logical_role='me_officer', is_active=True)
        triggers = []
        for raw in config.triggering_permissions or []:
            if ':' in raw:
                mod, act = raw.split(':', 1)
                triggers.append((mod.strip(), act.strip()))
        if triggers:
            q = Q()
            for mod, act in triggers:
                q |= Q(module=mod, action=act)
            me_user_ids = ModulePermission.objects.filter(q).filter(
                role__user_access__country_office=project.country_office,
                role__user_access__is_active=True,
                role__user_access__unit__isnull=True,  # CO-level only
            ).values_list('role__user_access__user_id', flat=True)
            user_ids.update(me_user_ids)
    except MERoleConfig.DoesNotExist:
        pass

    if exclude_user and getattr(exclude_user, 'id', None):
        user_ids.discard(exclude_user.id)
    return User.objects.filter(id__in=user_ids, is_active=True).exclude(email='')