# Dodo — Development Makefile
# Run `make help` for the full list of commands.

.DEFAULT_GOAL := help
.PHONY: help build up down restart logs shell migrate createsuperuser demo reminders test clean prune rebuild

COMPOSE = docker compose
DEV = $(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml

help: ## Show this help message
	@echo "Dodo — Docker commands"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Initial setup: copy .env.example to .env
	@test -f .env || cp .env.example .env
	@echo "✓ .env ready — edit it before starting up."

build: ## Build all Docker images
	$(COMPOSE) build

up: ## Start all services in the background
	$(COMPOSE) up -d
	@echo ""
	@echo "✓ Services started!"
	@echo "  Web:      http://localhost:8000"
	@echo "  Nginx:    http://localhost"
	@echo "  Postgres: localhost:5432"
	@echo "  Redis:    localhost:6379"

dev: ## Start in development mode (runserver with live reload)
	$(DEV) up

down: ## Stop all services
	$(COMPOSE) down

restart: ## Restart all services
	$(COMPOSE) restart

logs: ## Tail logs from all services
	$(COMPOSE) logs -f

logs-web: ## Tail web container logs only
	$(COMPOSE) logs -f web

shell: ## Open a bash shell in the web container
	$(COMPOSE) exec web bash

django-shell: ## Open Django shell
	$(COMPOSE) exec web python manage.py shell

dbshell: ## Open PostgreSQL shell
	$(COMPOSE) exec db psql -U dodo -d dodo

migrate: ## Apply Django migrations
	$(COMPOSE) exec web python manage.py migrate

makemigrations: ## Create new migrations
	$(COMPOSE) exec web python manage.py makemigrations

createsuperuser: ## Create a Django superuser
	$(COMPOSE) exec web python manage.py createsuperuser

demo: ## Load demo data (setup_demo + setup_workflow)
	$(COMPOSE) exec web python manage.py setup_demo
	$(COMPOSE) exec web python manage.py setup_workflow

reminders: ## Dispatch deadline reminders now
	$(COMPOSE) exec web python manage.py send_reminders

collectstatic: ## Collect static files
	$(COMPOSE) exec web python manage.py collectstatic --noinput

test: ## Run Django tests
	$(COMPOSE) exec web python manage.py test

rebuild: ## Rebuild and restart everything
	$(COMPOSE) down
	$(COMPOSE) build --no-cache
	$(COMPOSE) up -d

clean: ## Remove stopped containers (keep volumes)
	$(COMPOSE) down --remove-orphans

prune: ## WARNING: remove all containers AND volumes (data loss!)
	@read -p "⚠️  This deletes ALL data. Continue? [y/N] " ok && [ "$$ok" = "y" ]
	$(COMPOSE) down -v --remove-orphans

backup-db: ## Backup the database to ./backups/
	@mkdir -p backups
	$(COMPOSE) exec -T db pg_dump -U dodo dodo | gzip > backups/dodo_$$(date +%Y%m%d_%H%M%S).sql.gz
	@echo "✓ Backup saved to ./backups/"

restore-db: ## Restore the latest backup (usage: make restore-db FILE=backups/xxx.sql.gz)
	@test -n "$(FILE)" || (echo "Usage: make restore-db FILE=backups/xxx.sql.gz" && exit 1)
	gunzip -c $(FILE) | $(COMPOSE) exec -T db psql -U dodo -d dodo
	@echo "✓ Restored from $(FILE)"
