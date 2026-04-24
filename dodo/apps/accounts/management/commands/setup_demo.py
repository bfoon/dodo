from django.core.management.base import BaseCommand
from django.utils import timezone
import datetime


class Command(BaseCommand):
    help = 'Set up demo data for Dodo'

    def handle(self, *args, **kwargs):
        from apps.accounts.models import CountryOffice, User, Role, UserCountryAccess, ModulePermission
        from apps.projects.models import ProgrammeUnit, Project, ReportingCycle, ProjectReportingStatus, CPDFramework, CPDOutcome, CPDIndicator, DonorReportingTimeline

        self.stdout.write('Setting up demo data...')

        # Country Office
        co, _ = CountryOffice.objects.get_or_create(
            code='GMB', defaults={'name': 'The Gambia', 'region': 'West Africa', 'is_active': True}
        )
        co2, _ = CountryOffice.objects.get_or_create(
            code='SEN', defaults={'name': 'Senegal', 'region': 'West Africa', 'is_active': True}
        )

        # Roles
        roles_data = [
            ('M&E Specialist', 'me_specialist', 'M&E data entry and monitoring'),
            ('Programme Lead', 'programme_lead', 'Programme oversight and review'),
            ('PMSU Reviewer', 'pmsu_reviewer', 'PMSU review and clearance'),
            ('DRR/RR', 'drr_rr', 'Final clearance authority'),
            ('Project Manager', 'project_manager', 'Project-level management'),
            ('CO Admin', 'co_admin', 'Country office administration'),
        ]
        for name, code, desc in roles_data:
            role, created = Role.objects.get_or_create(code=code, country_office=co, defaults={'name': name, 'description': desc})
            if created:
                for module, _ in ModulePermission.MODULE_CHOICES:
                    for action, _ in ModulePermission.ACTION_CHOICES:
                        if name == 'CO Admin' or (module in ('dashboard', 'projects', 'monitoring', 'surveys', 'reporting') and action in ('view', 'create', 'edit')):
                            ModulePermission.objects.get_or_create(role=role, module=module, action=action)

        admin_role = Role.objects.filter(code='co_admin', country_office=co).first()
        me_role = Role.objects.filter(code='me_specialist', country_office=co).first()
        pm_role = Role.objects.filter(code='project_manager', country_office=co).first()

        # Users
        admin_user, created = User.objects.get_or_create(
            email='admin@undp.org',
            defaults={
                'username': 'admin@undp.org', 'first_name': 'System', 'last_name': 'Admin',
                'is_global_admin': True, 'is_staff': True, 'is_superuser': True,
                'primary_country_office': co, 'position': 'System Administrator',
            }
        )
        if created:
            admin_user.set_password('admin123')
            admin_user.save()

        me_user, created = User.objects.get_or_create(
            email='me@undp.org',
            defaults={
                'username': 'me@undp.org', 'first_name': 'Fatou', 'last_name': 'Diallo',
                'primary_country_office': co, 'position': 'M&E Specialist',
            }
        )
        if created:
            me_user.set_password('admin123')
            me_user.save()
            if me_role:
                UserCountryAccess.objects.get_or_create(user=me_user, country_office=co, role=me_role, defaults={'granted_by': admin_user})

        if admin_role:
            UserCountryAccess.objects.get_or_create(user=admin_user, country_office=co, role=admin_role, defaults={'granted_by': admin_user})

        # Programme Units
        units_data = [
            ('Climate & Environment', 'CE', '#009e60'),
            ('Governance', 'GOV', '#0077c8'),
            ('Inclusive Growth', 'IG', '#f59e0b'),
        ]
        units = {}
        for name, code, color in units_data:
            u, _ = ProgrammeUnit.objects.get_or_create(
                code=code, country_office=co,
                defaults={'name': name, 'color': color, 'lead': me_user}
            )
            units[code] = u

        # CPD Framework
        framework, _ = CPDFramework.objects.get_or_create(
            country_office=co, year_start=2022, year_end=2026,
            defaults={'title': 'Country Programme Document 2022–2026 — The Gambia', 'is_active': True}
        )

        # CPD Outcomes
        outcome_data = [
            ('2.1', 'outcome', 'By 2028, marginalised and vulnerable people in The Gambia participate in functional, accountable, and transparent institutions.', 'Strategic Objective 2: Effective Governance', units['GOV']),
            ('3.1', 'outcome', 'By 2028, people in The Gambia benefit from a healthy planet and resilient ecosystems.', 'Strategic Objective: Healthy Planet', units['CE']),
            ('1.1', 'outcome', 'By 2028, people in The Gambia benefit from inclusive and sustainable economic growth.', 'Strategic Area: Green inclusive economic growth', units['IG']),
        ]
        for code, tier, title, sp, unit in outcome_data:
            outcome, _ = CPDOutcome.objects.get_or_create(
                framework=framework, code=code,
                defaults={'tier': tier, 'title': title, 'sp_outcome': sp, 'programme_unit': unit}
            )
            CPDIndicator.objects.get_or_create(
                outcome=outcome, code=f'{code}-I1',
                defaults={
                    'description': f'Key performance indicator for {unit.name}',
                    'baseline': 'To be established', 'end_target': 'Per CPD targets',
                    'frequency': 'Quarterly', 'responsible_institution': 'Government, UNDP'
                }
            )

        # Projects
        projects_data = [
            ('PIMS-9873', 'Biodiversity Finance Plan Gambia (BIOFIN)', 'CE', 'active', '2024-01-01', '2027-03-06', 'GEF', 'NEA, MoFEA'),
            ('FFEM-001', 'Strengthening National and Municipal Capacities', 'CE', 'active', '2023-05-30', '2027-06-30', 'bilateral', 'Municipalities'),
            (None, 'Build Capacity in PCB and UPOPs', 'CE', 'closed', '2020-01-01', '2025-12-31', 'other', 'NEA'),
            ('PIMS-10205', 'GEF SGP 8th Operational Phase', 'CE', 'active', '2024-10-01', '2028-12-31', 'gef', 'CSOs'),
            (None, 'Security Sector Reform Project', 'GOV', 'active', '2025-02-28', '2028-02-29', 'pbf', 'NSA, Security Agencies'),
            (None, 'BRIDGE AFDB Project', 'GOV', 'pipeline', '2026-04-01', '2028-03-31', 'bilateral', 'IEC'),
            (None, 'JSB Community Security and Women Leadership Project', 'GOV', 'active', '2026-03-31', '2027-03-30', 'pbf', 'CSOs'),
            (None, 'Rule of Law and Access to Justice', 'GOV', 'active', '2026-02-01', '2030-02-01', 'bilateral', 'MoJ, Judiciary'),
            (None, 'Public Accountability Project', 'GOV', 'active', '2024-06-01', '2027-05-31', 'pbf', 'NALA, IEC'),
            (None, 'Building an Inclusive and Resilient Economy for All in The Gambia (Portfolio)', 'IG', 'active', '2026-01-01', '2030-12-31', 'trac', 'MoTIE'),
            (None, 'Programme for Accelerated Community Development II (PACD)', 'IG', 'active', '2026-01-01', '2030-12-31', 'trac', 'Local Government'),
            (None, 'Institutional Support to ECOWAS Commission for AfCFTA', 'IG', 'active', '2025-09-01', '2027-10-31', 'bilateral', 'ECOWAS'),
        ]
        projects = []
        for pims, title, unit_code, status, start, end, dtype, partner in projects_data:
            p, _ = Project.objects.get_or_create(
                country_office=co, title=title,
                defaults={
                    'programme_unit': units[unit_code], 'pims_id': pims or '',
                    'status': status, 'start_date': start, 'end_date': end,
                    'donor_type': dtype, 'data_source_partner': partner,
                    'responsible_person': 'Project Manager / Project M&E',
                    'programme_reviewer': f'{units[unit_code].name} Lead',
                    'pmsu_reviewer': 'M&E Specialist/Programme Finance Associate',
                    'final_clearance': 'DRR/RR', 'created_by': admin_user,
                }
            )
            projects.append((p, unit_code))

        # Reporting Cycles + Statuses
        quarters = ['Q1', 'Q2', 'Q3', 'Q4']
        q_timelines = {
            'Q1': {'progress': '3–14 April 2026', 'verification': 'Mar–Apr 2026'},
            'Q2': {'progress': '3–15 July 2026', 'verification': 'Jun–Jul 2026'},
            'Q3': {'progress': '3–15 October 2026', 'verification': 'Sept–Oct 2026'},
            'Q4': {'progress': '18–31 December 2026', 'verification': 'Dec 2026'},
        }
        q_due = {'Q1': '2026-04-14', 'Q2': '2026-07-15', 'Q3': '2026-10-15', 'Q4': '2026-12-31'}
        q_status_map = {
            'PIMS-9873': {'Q1': 'under_review', 'Q2': 'pending', 'Q3': 'pending', 'Q4': 'pending'},
            'FFEM-001': {'Q1': 'under_review', 'Q2': 'pending', 'Q3': 'pending', 'Q4': 'pending'},
        }
        default_status = {'Q1': 'pending', 'Q2': 'pending', 'Q3': 'not_started', 'Q4': 'not_started'}

        for q in quarters:
            for ctype in ['progress', 'verification']:
                cycle, _ = ReportingCycle.objects.get_or_create(
                    country_office=co, year=2026, quarter=q, cycle_type=ctype,
                    defaults={
                        'reporting_timeline': q_timelines[q][ctype],
                        'final_report_due': q_due[q],
                        'programme_review_dates': '4–5 days after submission',
                        'pmsu_review_dates': '6–8 days after submission',
                    }
                )
                for p, unit_code in projects:
                    status_map = q_status_map.get(p.pims_id, default_status)
                    status = status_map.get(q, 'pending')
                    if p.status == 'closed':
                        status = 'not_applicable'
                    elif p.status == 'pipeline' and q in ['Q1']:
                        status = 'not_applicable'
                    elif p.status == 'pipeline':
                        status = 'not_started'

                    if ctype == 'verification':
                        from apps.monitoring.models import OutputVerification
                        OutputVerification.objects.get_or_create(
                            project=p, cycle=cycle,
                            defaults={'status': 'not_applicable' if status == 'not_applicable' else 'pending', 'verification_period': q_timelines[q][ctype]}
                        )
                    else:
                        ProjectReportingStatus.objects.get_or_create(
                            project=p, cycle=cycle,
                            defaults={'status': status, 'updated_by': admin_user}
                        )

        # Donor timelines
        pbf_projects = Project.objects.filter(country_office=co, donor_type='pbf')
        for p in pbf_projects[:2]:
            DonorReportingTimeline.objects.get_or_create(
                country_office=co, project=p,
                defaults={
                    'donor': 'PBF', 'reporting_frequency': 'Bi-annual',
                    'period_1': 'Jan–May 2026', 'internal_draft_1': '1–7 June 2026',
                    'programme_review_1': '8–10 June 2026', 'pmsu_review_1': '11–13 June 2026',
                    'final_submission_1': '15 June 2026',
                    'period_2': 'Jun–Oct 2026', 'internal_draft_2': '1–7 November 2026',
                    'programme_review_2': '8–10 November 2026', 'pmsu_review_2': '11–13 November 2026',
                    'final_submission_2': '15 November 2026',
                    'notes': 'Fixed PBF submission dates',
                }
            )

        # Sample Surveys
        from apps.surveys.models import Survey, Question, QuestionChoice
        survey, created = Survey.objects.get_or_create(
            country_office=co, title='Q1 2026 Project Monitoring Survey',
            defaults={
                'survey_type': 'monitoring', 'status': 'active',
                'description': 'Quarterly monitoring data collection for Q1 2026',
                'created_by': admin_user,
            }
        )
        if created:
            questions_demo = [
                ('radio', 'What is the overall implementation status of the project this quarter?', '', ['On Track', 'Slightly Delayed', 'Significantly Delayed', 'At Risk'], False),
                ('number', 'What percentage of planned activities have been completed?', 'Enter a number between 0 and 100', [], True),
                ('textarea', 'What are the key achievements this quarter?', 'Describe main outputs and results delivered', [], True),
                ('textarea', 'What are the main challenges encountered?', 'List any bottlenecks or constraints', [], False),
                ('checkbox', 'Which cross-cutting issues were addressed?', '', ['Gender Equality', 'Youth Engagement', 'Disability Inclusion', 'Climate Resilience', 'Human Rights'], False),
                ('likert', 'How would you rate stakeholder engagement this quarter?', '1 = Very Poor, 5 = Excellent', [], True),
                ('textarea', 'What are recommendations for next quarter?', '', [], False),
            ]
            for i, (qtype, text, desc, choices, req) in enumerate(questions_demo, 1):
                q = Question.objects.create(
                    survey=survey, question_type=qtype, text=text, description=desc,
                    is_required=req, order=i, scale_min=1, scale_max=5,
                    scale_min_label='Very Poor', scale_max_label='Excellent'
                )
                for j, ct in enumerate(choices):
                    QuestionChoice.objects.create(question=q, text=ct, order=j)

        self.stdout.write(self.style.SUCCESS('✅ Demo data setup complete!'))
        self.stdout.write('   Login: admin@undp.org / admin123')
        self.stdout.write('   M&E User: me@undp.org / admin123')


# Note: the Command class above handles basic setup.
# The extended demo setup (deadline templates, unit heads, delegations, grants)
# is appended below via the setup_workflow command.
