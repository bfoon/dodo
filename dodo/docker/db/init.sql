-- Dodo — PostgreSQL initialization
-- This runs once on first container startup.

-- Enable trigram extension for fast ILIKE searches across the app
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Ensure UTC timezone for consistent timestamps
SET timezone = 'UTC';
