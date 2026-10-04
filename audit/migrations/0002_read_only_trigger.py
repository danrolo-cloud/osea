"""
Database-level protection for the activity log.

The model already refuses to edit or delete single entries. This trigger
also blocks bulk changes and anything done directly in the database, so the
log stays trustworthy no matter how a change is attempted.
"""

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION audit_event_read_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Activity log entries cannot be changed or deleted.';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_event_read_only
    BEFORE UPDATE OR DELETE ON audit_auditevent
    FOR EACH ROW EXECUTE FUNCTION audit_event_read_only();
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_event_read_only ON audit_auditevent;
DROP FUNCTION IF EXISTS audit_event_read_only();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
