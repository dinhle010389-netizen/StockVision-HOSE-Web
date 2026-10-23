-- Apply to an existing StockVision database created before Market Overview index fields.
-- Safe to re-run on PostgreSQL versions supporting ADD COLUMN IF NOT EXISTS.
SET search_path TO sv, public;
ALTER TABLE index_bar ADD COLUMN IF NOT EXISTS change_value NUMERIC(20,6);
ALTER TABLE index_bar ADD COLUMN IF NOT EXISTS change_pct NUMERIC(12,6);
CREATE INDEX IF NOT EXISTS ix_index_bar_latest ON index_bar(index_code, timeframe, bar_start DESC);
