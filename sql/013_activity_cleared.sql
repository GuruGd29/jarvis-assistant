-- Clearing Activity (More -> Activity -> Clear): cleared entries are hidden, not deleted, so Clear can be undone.
-- They go with the 90-day clean-up like any other entry (jarvis/web/notify.py).
ALTER TABLE activity ADD COLUMN IF NOT EXISTS cleared_at timestamptz;
