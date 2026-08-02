-- Set passwords for Supabase service roles on first DB init.
-- POSTGRES_PASSWORD must match the value used by rest/storage connection strings.
-- Only roles created by the image init scripts (not optional extension roles).
\set pgpass `echo "$POSTGRES_PASSWORD"`

ALTER USER authenticator WITH PASSWORD :'pgpass';
ALTER USER pgbouncer WITH PASSWORD :'pgpass';
ALTER USER supabase_auth_admin WITH PASSWORD :'pgpass';
ALTER USER supabase_storage_admin WITH PASSWORD :'pgpass';
