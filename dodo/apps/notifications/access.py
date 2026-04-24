"""
Centralized access control service for the Dodo.

Combines 3 layers of authorization:
  1. Role-based permissions (ModulePermission via UserCountryAccess)
  2. Unit Head privileges (see all reports under their unit)
  3. Granular data-level grants (DataAccessGrant for specific resources)
  4. Cycle-level delegations (ReportDelegation for specific project/cycle combos)

Usage:
    from apps.notifications.access import AccessChecker
    if AccessChecker.can_edit_project(user, project):
        ...
"""
from django.utils import timezone
from apps.notifications.models import DataAccessGrant, ReportDelegation, UnitHead


class AccessChecker:
    """Central authorization for every resource in the platform."""

    # ---------- Super-user shortcuts ----------
    @staticmethod
    def is_super(user):
        return user.is_authenticated and (user.is_superuser or user.is_global_admin)

    @staticmethod
    def is_co_admin(user, country_office):
        """User has 'admin' action on 'admin' module in this CO (typically M&E staff)."""
        if AccessChecker.is_super(user):
            return True
        if not country_office:
            return False
        return user.has_module_permission('admin', 'edit', country_office) or \
               user.has_module_permission('admin', 'create', country_office)

    # ---------- Unit Head checks ----------
    @staticmethod
    def is_head_of_unit(user, programme_unit):
        if AccessChecker.is_super(user):
            return True
        return UnitHead.objects.filter(
            user=user, programme_unit=programme_unit, is_active=True
        ).exists()

    @staticmethod
    def get_headed_units(user):
        """Returns all programme units this user heads."""
        from apps.projects.models import ProgrammeUnit
        if AccessChecker.is_super(user):
            return ProgrammeUnit.objects.filter(is_active=True)
        return ProgrammeUnit.objects.filter(
            heads__user=user, heads__is_active=True
        ).distinct()

    # ---------- Project-level access ----------
    @staticmethod
    def can_view_project(user, project):
        if AccessChecker.is_super(user):
            return True
        if AccessChecker.is_co_admin(user, project.country_office):
            return True
        # Head of the project's unit?
        if project.programme_unit and AccessChecker.is_head_of_unit(user, project.programme_unit):
            return True
        # Project responsibility?
        if project.responsibilities.filter(user=user, is_active=True).exists():
            return True
        # Assigned via delegation?
        if ReportDelegation.objects.filter(
            project=project, delegated_to=user, is_active=True
        ).exists():
            return True
        # Granular grant?
        if AccessChecker._has_grant(user, 'project', project.pk, 'view'):
            return True
        if AccessChecker._has_grant(user, 'all_projects', None, 'view', project.country_office):
            return True
        if project.programme_unit and AccessChecker._has_grant(user, 'programme_unit', project.programme_unit.pk, 'view'):
            return True
        # Basic module view in their CO
        return user.has_module_permission('projects', 'view', project.country_office)

    @staticmethod
    def can_edit_project(user, project):
        if AccessChecker.is_super(user):
            return True
        if AccessChecker.is_co_admin(user, project.country_office):
            return True
        if project.programme_unit and AccessChecker.is_head_of_unit(user, project.programme_unit):
            return True
        if project.responsibilities.filter(
            user=user, is_active=True,
            role__in=['manager', 'm_and_e', 'responsible_officer']
        ).exists():
            return True
        if AccessChecker._has_grant(user, 'project', project.pk, level_in=['edit', 'delete', 'approve', 'full']):
            return True
        if AccessChecker._has_grant(user, 'all_projects', None, level_in=['edit', 'delete', 'approve', 'full'], co=project.country_office):
            return True
        return False

    @staticmethod
    def can_delete_project(user, project):
        if AccessChecker.is_super(user):
            return True
        if AccessChecker.is_co_admin(user, project.country_office):
            return True
        if AccessChecker._has_grant(user, 'project', project.pk, level_in=['delete', 'full']):
            return True
        return False

    @staticmethod
    def can_approve_project_report(user, project):
        if AccessChecker.is_super(user):
            return True
        if AccessChecker.is_co_admin(user, project.country_office):
            return True
        if project.programme_unit:
            head = UnitHead.objects.filter(
                user=user, programme_unit=project.programme_unit,
                is_active=True, can_approve=True
            ).exists()
            if head:
                return True
        if AccessChecker._has_grant(user, 'project', project.pk, level_in=['approve', 'full']):
            return True
        return False

    @staticmethod
    def can_download_project_data(user, project):
        if AccessChecker.can_view_project(user, project):
            if AccessChecker.is_super(user) or AccessChecker.is_co_admin(user, project.country_office):
                return True
            if AccessChecker._has_grant(user, 'project', project.pk, level_in=['download', 'edit', 'delete', 'approve', 'full']):
                return True
            if AccessChecker._has_grant(user, 'all_projects', None, level_in=['download', 'full'], co=project.country_office):
                return True
            if project.programme_unit and AccessChecker.is_head_of_unit(user, project.programme_unit):
                return True
            if user.has_module_permission('projects', 'export', project.country_office):
                return True
        return False

    # ---------- Reporting cycle access ----------
    @staticmethod
    def can_enter_cycle_data(user, project, cycle):
        """Can this user enter reporting data for this project in this cycle?"""
        if AccessChecker.can_edit_project(user, project):
            return True
        # Delegated for this specific cycle?
        if ReportDelegation.objects.filter(
            project=project, cycle=cycle, delegated_to=user, is_active=True,
            delegation_type__in=['draft', 'full', 'data_entry']
        ).exists():
            return True
        # Assigned for this specific cycle?
        from apps.projects.models import ReportAssignment
        if ReportAssignment.objects.filter(
            project=project, cycle=cycle, assigned_to=user,
            status__in=['assigned', 'accepted', 'in_progress', 'revisions_requested']
        ).exists():
            return True
        return False

    # ---------- Granular data grant helper ----------
    @staticmethod
    def _has_grant(user, resource_type, resource_id, level=None, level_in=None, co=None):
        qs = DataAccessGrant.objects.filter(
            granted_to=user, is_active=True, resource_type=resource_type
        )
        if resource_id is not None:
            qs = qs.filter(resource_id=resource_id)
        if co:
            qs = qs.filter(country_office=co)
        if level:
            qs = qs.filter(access_level=level)
        if level_in:
            qs = qs.filter(access_level__in=level_in)
        # Check date validity
        today = timezone.now().date()
        qs = qs.filter(start_date__lte=today)
        qs = qs.filter(models_q_valid_end(today))
        return qs.exists()

    # ---------- Accessible project queryset ----------
    @staticmethod
    def get_accessible_projects(user, country_office=None):
        """Returns QuerySet of projects this user can at least view."""
        from apps.projects.models import Project
        if AccessChecker.is_super(user):
            qs = Project.objects.all()
            if country_office:
                qs = qs.filter(country_office=country_office)
            return qs
        from django.db.models import Q
        co_filter = Q()
        if country_office:
            co_filter = Q(country_office=country_office)

        # Build OR query for all access paths
        accessible_project_ids = set()

        # Projects via responsibility
        accessible_project_ids.update(
            user.project_responsibilities.filter(is_active=True).values_list('project_id', flat=True)
        )
        # Projects via delegation
        accessible_project_ids.update(
            user.received_delegations.filter(is_active=True).values_list('project_id', flat=True)
        )
        # Projects via headed units
        headed = AccessChecker.get_headed_units(user)
        headed_projects = Project.objects.filter(programme_unit__in=headed).values_list('pk', flat=True)
        accessible_project_ids.update(headed_projects)
        # Projects via grants
        project_grants = DataAccessGrant.objects.filter(
            granted_to=user, is_active=True, resource_type='project'
        ).values_list('resource_id', flat=True)
        accessible_project_ids.update(project_grants)
        # All-projects grants (by CO)
        co_all_grants = DataAccessGrant.objects.filter(
            granted_to=user, is_active=True, resource_type='all_projects'
        ).values_list('country_office_id', flat=True)
        if co_all_grants:
            accessible_project_ids.update(
                Project.objects.filter(country_office_id__in=co_all_grants).values_list('pk', flat=True)
            )

        # CO admin / module view fallback: all projects in COs where they have view permission
        from apps.accounts.models import UserCountryAccess
        access_co_ids = UserCountryAccess.objects.filter(
            user=user, is_active=True,
            role__permissions__module='projects', role__permissions__action='view'
        ).values_list('country_office_id', flat=True).distinct()
        if access_co_ids:
            accessible_project_ids.update(
                Project.objects.filter(country_office_id__in=access_co_ids).values_list('pk', flat=True)
            )

        qs = Project.objects.filter(pk__in=accessible_project_ids).filter(co_filter)
        return qs


def models_q_valid_end(today):
    """Helper for grants whose end_date is null OR >= today"""
    from django.db.models import Q
    return Q(end_date__isnull=True) | Q(end_date__gte=today)
