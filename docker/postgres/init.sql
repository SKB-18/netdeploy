-- Create the test database alongside the main database.
-- This script runs automatically when the postgres container is first started.
SELECT 'CREATE DATABASE netdeploy_test OWNER netdeploy'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'netdeploy_test')\gexec
