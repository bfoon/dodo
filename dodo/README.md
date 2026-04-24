# Dodo — M&E Platform

**Dodo** is a comprehensive Monitoring & Evaluation web application for UNDP Country Offices.

Built with **Django 4.2**, **Bootstrap 5**, and **Docker** — a 12-factor, container-native stack ready for laptop, on-prem, or cloud deployment.

**Stack:** Django 4.2 · PostgreSQL · Redis · Celery · Bootstrap 5 · Nginx · Docker

---

## Quick Start with Docker

### Prerequisites
- Docker 20.10+
- Docker Compose V2
- (Optional) `make` for convenience commands

### 1. Initial setup

```bash
# Copy environment template
cp .env.example .env

# Edit .env - at minimum, change DJANGO_SECRET_KEY and DB_PASSWORD
nano .env
```

### 2. Start the platform

**Production mode** (Gunicorn + Nginx + Celery workers):
```bash
docker compose up -d --build
```

**Development mode** (Django runserver with live reload):
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Or using Make:
```bash
make setup      # copy .env.example
make build      # build images
make up         # production mode
make dev        # development mode
```

### 3. First-time data setup

On first boot, set `LOAD_DEMO_DATA=1` in `.env` — the entrypoint will automatically run `setup_demo` and `setup_workflow`.

Or load manually any time:
```bash
make demo
# equivalent to:
docker compose exec web python manage.py setup_demo
docker compose exec web python manage.py setup_workflow
```

### 4. Access the platform

- **Web (Nginx):** http://localhost/
- **Web (Django direct):** http://localhost:8000/
- **Admin:** http://localhost/admin/

---

## Architecture

The Docker Compose stack brings up 6 services on an isolated bridge network:

```
                    ┌─────────────────┐
                    │   nginx  :80    │  ← reverse proxy, static files
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  web  :8000     │  ← Django + Gunicorn (4 workers)
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
    ┌────▼────┐        ┌─────▼─────┐      ┌─────▼──────┐
    │ db :5432│        │redis :6379│      │celery_worker│
    │Postgres │        │           │      │            │
    └─────────┘        └─────┬─────┘      └────────────┘
                             │
                      ┌──────▼──────┐
                      │ celery_beat │ ← scheduled tasks (reminders)
                      └─────────────┘
```

| Service | Container | Role |
|---|---|---|
| `web` | `dodo_web` | Django app (Gunicorn, 4 workers) |
| `db` | `dodo_db` | PostgreSQL 16 |
| `redis` | `dodo_redis` | Cache + Celery broker |
| `celery_worker` | `dodo_celery` | Async tasks (emails, reports) |
| `celery_beat` | `dodo_beat` | Scheduled tasks (daily reminders) |
| `nginx` | `dodo_nginx` | Reverse proxy + static files |

---

## Common Operations (Makefile)

```bash
make help              # list all commands
make up                # start all services
make down              # stop all services
make logs              # tail all logs
make logs-web          # tail web only
make shell             # bash shell in web container
make django-shell      # Django shell
make dbshell           # PostgreSQL prompt
make migrate           # apply migrations
make createsuperuser   # create superuser
make demo              # load demo data
make reminders         # dispatch reminders now
make backup-db         # backup database
make restore-db FILE=backups/xxx.sql.gz
make rebuild           # full rebuild
make prune             # DESTRUCTIVE: remove all data
```

---

## Core Features

### Multi-Country Office Architecture
- Every user is scoped to their **primary country office** by default
- Admins can grant **cross-office access** with specific roles
- Users switch between offices from the sidebar dropdown

### Dynamic Roles & Granular Permissions
- Roles are created **per country office** (not global)
- Each role has **module × action** permissions (e.g. `projects:edit`, `surveys:create`)
- Module list: dashboard, projects, monitoring, surveys, reporting, users, admin
- Action list: view, create, edit, delete, approve, export

### Six Layers of Access Control
Every request is checked against these layers:
1. **Superuser / Global Admin** — bypasses all checks
2. **Country Office Admin** (typically M&E staff) — full access in their CO
3. **Role-based Module Permissions** — from `UserCountryAccess`
4. **Unit Head** — sees all reports under their programme unit
5. **Granular Data Grants** — specific user → specific resource → specific action
6. **Cycle-level Delegations** — head of unit delegates one report to one person

## Workflow Features

### 1. Configurable Submission Deadlines & Reminders
- **DeadlineTemplate** with 4 configurable stages (Draft, Programme, PMSU, Clearance)
- **DeadlineSchedule** per project/cycle — every date editable per instance
- **Reminder schedule** configurable per template (e.g. "14, 7, 3, 1 days before")
- **Escalation rule** — notifies Head of Unit if overdue by N days
- **Automatic dispatch** via Celery Beat every morning at 08:00 UTC

### 2. Delegation Workflow
- Heads of Unit delegate reports to specific users
- 4 types: Draft Preparation, Full Report, Review Only, Data Entry Only
- Scoped to cycle or ongoing · Time-bound · Revocable
- Automatic in-app + email notification to delegatee

### 3. Unit Head Dashboard
- "My Unit" sidebar item for Heads of Programme Units
- All projects, deadlines, assignments under their unit
- One-click delegate button on every deadline

### 4. Admin-Granted Data Access
- Admins (M&E staff) grant any user access to any resource
- Resource types: Project, Programme Unit, Cycle, Survey, Indicator, All Projects, All Reports
- Access levels: View, Edit, Delete, Approve, Download, Full
- Time-bound with optional end date · Revocable · Full audit trail

### 5. In-App Notification Center
- Bell icon in topbar with unread badge
- Full notification center at `/notifications/` with filters
- Priority levels: low, normal, high, critical
- In-app + email delivery (async via Celery)

### 6. Dynamic Surveys & Questionnaires
- 14 question types: text, number, date, radio, checkbox, dropdown, likert, rating, file, matrix, ranking, yes/no, geo, section header
- Conditional logic
- Live results with charts
- Anonymous or named responses

### 7. Reporting Tracker
- Quarter-by-quarter status tracker by programme cluster
- Mirrors the Excel tracker structure exactly
- Real-time status updates with dropdown

---

## Demo Accounts

After running `make demo`:

| Email | Password | Role |
|---|---|---|
| `admin@undp.org` | `admin123` | Global Admin |
| `me@undp.org` | `admin123` | M&E Specialist |
| `sanneh@undp.org` | `admin123` | Head of Governance Unit |
| `jallow@undp.org` | `admin123` | Head of Climate & Environment |
| `ceesay@undp.org` | `admin123` | Head of Inclusive Growth |
| `drammeh@undp.org` | `admin123` | Deputy Head of Governance |
| `touray@undp.org` | `admin123` | Project Manager |
| `bah@undp.org` | `admin123` | M&E Officer (has delegations + grants) |

---

## Deployment

### Production Checklist

Before exposing to the public internet, update `.env`:

```bash
DJANGO_SECRET_KEY=<generate with: openssl rand -base64 50>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=me.undp.org
CSRF_TRUSTED_ORIGINS=https://me.undp.org

DB_PASSWORD=<strong random password>

SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST_USER=<your-smtp-user>
EMAIL_HOST_PASSWORD=<your-smtp-password>

LOAD_DEMO_DATA=0
```

### SSL/TLS

Uncomment the HTTPS server block in `docker/nginx/default.conf` and mount certificates:

```yaml
# in docker-compose.yml under nginx service:
volumes:
  - ./docker/nginx/ssl:/etc/nginx/ssl:ro
ports:
  - "443:443"
```

Use Let's Encrypt via `certbot` or a cloud-managed certificate.

### Backups

```bash
# Manual
make backup-db

# Automated (add to host's crontab)
0 2 * * * cd /opt/dodo && make backup-db
```

---

## Project Structure

```
dodo/
├── Dockerfile
├── docker-compose.yml          # production stack
├── docker-compose.dev.yml      # dev overrides (runserver)
├── Makefile                    # common commands
├── .env.example                # env var template
├── requirements.txt
├── manage.py
├── docker/
│   ├── entrypoint.sh           # waits for DB, migrates, loads demo
│   ├── nginx/
│   │   ├── nginx.conf
│   │   └── default.conf        # reverse proxy config
│   └── db/
│       └── init.sql            # Postgres extensions
├── dodo/
│   ├── settings.py             # env-driven config
│   ├── celery.py               # Celery app + Beat schedule
│   ├── wsgi.py / asgi.py
│   └── urls.py
├── apps/
│   ├── accounts/               # Users, CountryOffice, Roles
│   ├── projects/               # Projects, Cycles, CPD Framework
│   ├── monitoring/             # Indicators, Verification, Visits
│   ├── surveys/                # Dynamic surveys
│   ├── reporting/              # Reports & exports
│   ├── dashboard/              # Dashboards
│   └── notifications/          # Deadlines, reminders, delegations,
│       │                       # access grants, unit heads
│       ├── access.py           # AccessChecker — central auth
│       ├── services.py         # Notification + Reminder dispatch
│       └── tasks.py            # Celery tasks
└── templates/                  # Bootstrap 5 UI
```

---

## Troubleshooting

**Containers won't start:**
```bash
docker compose logs
```

**Database connection refused:**
Wait for the healthcheck — the entrypoint script waits up to 60 seconds for Postgres.

**Static files 404:**
```bash
make collectstatic
```

**Reset everything:**
```bash
make prune   # ⚠️ deletes all data
make setup
make up
make demo
```

**Reminder dispatcher not running:**
Check Celery Beat logs:
```bash
docker compose logs celery_beat
docker compose logs celery_worker
```
