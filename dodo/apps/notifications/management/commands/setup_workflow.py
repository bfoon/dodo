"""
Sets up demo data for the workflow features: deadline templates, unit heads,
project responsibilities, and sample notifications.

Run AFTER setup_demo:
    python manage.py setup_demo
    python manage.py setup_workflow
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = 'Set up workflow demo data: deadlines, delegations, unit heads, grants'

    def handle(self, *args, **kwargs):
        from apps.accounts.models import User, CountryOffice
        from apps.projects.models import Project, ProgrammeUnit, ReportingCycle, ProjectResponsibility, ReportAssignment
        from apps.notifications.models import (
            DeadlineTemplate, DeadlineSchedule, UnitHead,
            ReportDelegation, DataAccessGrant, Notification
        )
        from apps.notifications.services import NotificationService, DelegationNotifier

        co = CountryOffice.objects.filter(code='GMB').first()
        if not co:
            self.stdout.write(self.style.ERROR('Run setup_demo first to create the country office.'))
            return

        admin = User.objects.get(email='admin@undp.org')
        me_user = User.objects.get(email='me@undp.org')

        # Create additional demo users for delegation testing
        demo_users_spec = [
            ('sanneh@undp.org', 'Mariama', 'Sanneh', 'Governance Cluster Lead'),
            ('jallow@undp.org', 'Ousman', 'Jallow', 'Climate & Environment Lead'),
            ('ceesay@undp.org', 'Isatou', 'Ceesay', 'Inclusive Growth Lead'),
            ('touray@undp.org', 'Lamin', 'Touray', 'Project Manager'),
            ('drammeh@undp.org', 'Aisha', 'Drammeh', 'Programme Analyst'),
            ('bah@undp.org', 'Mustapha', 'Bah', 'M&E Officer'),
        ]
        demo_users = {}
        for email, first, last, position in demo_users_spec:
            u, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'username': email, 'first_name': first, 'last_name': last,
                    'primary_country_office': co, 'position': position,
                }
            )
            if created:
                u.set_password('admin123')
                u.save()
            demo_users[email] = u

        # --------------------------------------------------------------
        # 1. Deadline Templates
        # --------------------------------------------------------------
        self.stdout.write('Creating deadline templates...')
        templates = {}

        dt, _ = DeadlineTemplate.objects.get_or_create(
            country_office=co, name='Standard Quarterly Progress Reporting',
            defaults={
                'cycle_type': 'progress',
                'internal_draft_days_before': 14,
                'programme_review_days_before': 10,
                'pmsu_review_days_before': 6,
                'final_clearance_days_before': 2,
                'reminder_days_before': '14,7,3,1',
                'escalation_days_after': 1,
                'send_email': True, 'send_in_app': True,
                'notify_head_of_unit': True, 'notify_responsible': True,
                'description': 'Standard 4-stage progress reporting timeline with reminders at 14, 7, 3 and 1 day before deadline',
            }
        )
        templates['progress'] = dt

        dt2, _ = DeadlineTemplate.objects.get_or_create(
            country_office=co, name='Quarterly Output Verification',
            defaults={
                'cycle_type': 'verification',
                'internal_draft_days_before': 20,
                'programme_review_days_before': 15,
                'pmsu_review_days_before': 8,
                'final_clearance_days_before': 3,
                'reminder_days_before': '21,14,7,3,1',
                'escalation_days_after': 2,
                'description': 'Output verification cycle with extended timeline for field work',
            }
        )
        templates['verification'] = dt2

        dt3, _ = DeadlineTemplate.objects.get_or_create(
            country_office=co, name='PBF Bi-annual Donor Report',
            defaults={
                'cycle_type': 'donor',
                'internal_draft_days_before': 21,
                'programme_review_days_before': 14,
                'pmsu_review_days_before': 7,
                'final_clearance_days_before': 2,
                'reminder_days_before': '30,21,14,7,3,1',
                'escalation_days_after': 0,
                'description': 'PBF-compliant reporting schedule with mandatory early-warning reminders',
            }
        )
        templates['donor'] = dt3

        # --------------------------------------------------------------
        # 2. Unit Heads
        # --------------------------------------------------------------
        self.stdout.write('Assigning unit heads...')
        units = {u.code: u for u in ProgrammeUnit.objects.filter(country_office=co)}

        unit_head_map = [
            (demo_users['sanneh@undp.org'], 'GOV', True),
            (demo_users['jallow@undp.org'], 'CE', True),
            (demo_users['ceesay@undp.org'], 'IG', True),
            (demo_users['drammeh@undp.org'], 'GOV', False),  # deputy
        ]
        for user, unit_code, is_primary in unit_head_map:
            if unit_code in units:
                UnitHead.objects.get_or_create(
                    user=user, programme_unit=units[unit_code],
                    defaults={
                        'is_primary': is_primary,
                        'can_delegate': True, 'can_approve': True,
                        'assigned_by': admin,
                    }
                )

        # --------------------------------------------------------------
        # 3. Project Responsibilities
        # --------------------------------------------------------------
        self.stdout.write('Assigning project responsibilities...')
        projects = Project.objects.filter(country_office=co)
        responsibility_map = {
            'CE': [(demo_users['touray@undp.org'], 'manager'), (demo_users['bah@undp.org'], 'm_and_e')],
            'GOV': [(demo_users['touray@undp.org'], 'manager'), (me_user, 'm_and_e')],
            'IG': [(demo_users['drammeh@undp.org'], 'manager'), (demo_users['bah@undp.org'], 'm_and_e')],
        }

        for project in projects:
            unit_code = project.programme_unit.code if project.programme_unit else None
            if unit_code in responsibility_map:
                for user, role in responsibility_map[unit_code]:
                    ProjectResponsibility.objects.get_or_create(
                        project=project, user=user, role=role,
                        defaults={'is_primary': True, 'receive_notifications': True, 'assigned_by': admin}
                    )

        # --------------------------------------------------------------
        # 4. Deadline Schedules from templates
        # --------------------------------------------------------------
        self.stdout.write('Generating deadline schedules...')
        today = timezone.now().date()

        cycles = ReportingCycle.objects.filter(country_office=co, cycle_type='progress')
        for cycle in cycles:
            submission_date = cycle.final_report_due
            if not submission_date:
                continue
            template = templates['progress']
            for project in projects.exclude(status='closed'):
                DeadlineSchedule.objects.get_or_create(
                    project=project, cycle=cycle,
                    defaults={
                        'template': template,
                        'internal_draft_deadline': submission_date - timedelta(days=template.internal_draft_days_before),
                        'programme_review_deadline': submission_date - timedelta(days=template.programme_review_days_before),
                        'pmsu_review_deadline': submission_date - timedelta(days=template.pmsu_review_days_before),
                        'final_clearance_deadline': submission_date - timedelta(days=template.final_clearance_days_before),
                        'final_submission_deadline': submission_date,
                        'created_by': admin,
                    }
                )

        # Update statuses based on current date
        for deadline in DeadlineSchedule.objects.filter(project__country_office=co):
            deadline.status = deadline.compute_status()
            deadline.save(update_fields=['status'])

        # --------------------------------------------------------------
        # 5. Report Assignments
        # --------------------------------------------------------------
        self.stdout.write('Creating report assignments...')
        q1_cycle = ReportingCycle.objects.filter(country_office=co, year=2026, quarter='Q1', cycle_type='progress').first()
        if q1_cycle:
            for project in projects[:5]:
                unit_code = project.programme_unit.code if project.programme_unit else None
                assignee = None
                if unit_code in responsibility_map:
                    assignee = responsibility_map[unit_code][0][0]  # project manager
                if assignee:
                    assignment, created = ReportAssignment.objects.get_or_create(
                        project=project, cycle=q1_cycle, assigned_to=assignee,
                        defaults={
                            'assigned_by': admin,
                            'status': 'in_progress',
                            'due_date': q1_cycle.final_report_due,
                            'instructions': f'Please prepare Q1 2026 report for {project.display_title}. Include activity updates, indicator progress, and key challenges.',
                        }
                    )
                    if created:
                        DelegationNotifier.on_assignment_created(assignment)

        # --------------------------------------------------------------
        # 6. Sample Delegation
        # --------------------------------------------------------------
        self.stdout.write('Creating sample delegation...')
        pilot_project = projects.filter(status='active').first()
        if pilot_project and q1_cycle:
            delegation, created = ReportDelegation.objects.get_or_create(
                project=pilot_project, cycle=q1_cycle,
                delegated_to=demo_users['bah@undp.org'],
                delegated_by=demo_users['sanneh@undp.org'],
                defaults={
                    'delegation_type': 'full',
                    'start_date': today,
                    'end_date': today + timedelta(days=30),
                    'instructions': 'Please prepare full Q1 progress report on behalf of the project team. Coordinate with the M&E focal point for data verification.',
                    'is_active': True,
                }
            )
            if created:
                DelegationNotifier.on_delegation_created(delegation)

        # --------------------------------------------------------------
        # 7. Data Access Grants (examples)
        # --------------------------------------------------------------
        self.stdout.write('Creating sample data access grants...')
        # Give M&E officer download access to all reports
        grant1, created = DataAccessGrant.objects.get_or_create(
            granted_to=demo_users['bah@undp.org'],
            country_office=co, resource_type='all_reports',
            defaults={
                'granted_by': admin,
                'resource_name': f'All reports in {co.name}',
                'access_level': 'download',
                'reason': 'M&E Officer requires access to download all progress reports for consolidation',
                'start_date': today,
            }
        )
        if created:
            DelegationNotifier.on_grant_created(grant1)

        # Give specific user view+edit on a single project
        if pilot_project:
            grant2, created = DataAccessGrant.objects.get_or_create(
                granted_to=demo_users['drammeh@undp.org'],
                country_office=co, resource_type='project', resource_id=pilot_project.pk,
                defaults={
                    'granted_by': admin,
                    'resource_name': pilot_project.display_title,
                    'access_level': 'edit',
                    'reason': 'Temporary cover during project manager leave',
                    'start_date': today,
                    'end_date': today + timedelta(days=60),
                }
            )
            if created:
                DelegationNotifier.on_grant_created(grant2)

        # --------------------------------------------------------------
        # 8. Sample notifications (to show the bell badge)
        # --------------------------------------------------------------
        self.stdout.write('Creating sample notifications...')
        if pilot_project:
            NotificationService.create(
                user=admin, notification_type='reminder',
                title='Upcoming deadline: Q1 Progress Report',
                message=f'The Q1 2026 progress report for "{pilot_project.display_title}" is due in 7 days.',
                priority='normal', project=pilot_project, cycle=q1_cycle,
                action_url=f'/projects/{pilot_project.pk}/'
            )
            NotificationService.create(
                user=demo_users['bah@undp.org'], notification_type='delegation',
                title=f'Delegation: {pilot_project.display_title}',
                message='You have been delegated to prepare the Q1 progress report.',
                priority='high', project=pilot_project,
                action_url=f'/projects/{pilot_project.pk}/'
            )
            NotificationService.create(
                user=demo_users['sanneh@undp.org'], notification_type='approval',
                title='Report submitted for review',
                message='A Q1 progress report is ready for your review as Head of Governance.',
                priority='high', project=pilot_project,
                action_url=f'/projects/{pilot_project.pk}/'
            )

        self.stdout.write(self.style.SUCCESS('\n✅ Workflow demo data setup complete!'))
        self.stdout.write('')
        self.stdout.write('=' * 60)
        self.stdout.write('Demo accounts:')
        self.stdout.write('  admin@undp.org     / admin123  (Global Admin - full access)')
        self.stdout.write('  me@undp.org        / admin123  (M&E Specialist)')
        self.stdout.write('  sanneh@undp.org    / admin123  (Head of Governance)')
        self.stdout.write('  jallow@undp.org    / admin123  (Head of Climate)')
        self.stdout.write('  ceesay@undp.org    / admin123  (Head of Inclusive Growth)')
        self.stdout.write('  drammeh@undp.org   / admin123  (Deputy Head of Governance)')
        self.stdout.write('  touray@undp.org    / admin123  (Project Manager)')
        self.stdout.write('  bah@undp.org       / admin123  (M&E Officer - has delegations)')
        self.stdout.write('=' * 60)
        self.stdout.write('')
        self.stdout.write('To send reminders, run:')
        self.stdout.write('  python manage.py send_reminders')
