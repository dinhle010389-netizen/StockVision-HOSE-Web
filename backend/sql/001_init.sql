-- StockVision HOSE 0.1 — PostgreSQL reference schema
-- Read-only research MVP; no order-routing tables or broker credentials in frontend.
-- Production deployment should add migrations, retention/partition policies and stricter RBAC.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS sv;
SET search_path TO sv, public;

CREATE TABLE IF NOT EXISTS data_source (
    source_id           BIGSERIAL PRIMARY KEY,
    code                TEXT NOT NULL UNIQUE,
    display_name        TEXT NOT NULL,
    source_type         TEXT NOT NULL CHECK (source_type IN ('broker_api','exchange','issuer','manual','derived')),
    base_url            TEXT,
    terms_url           TEXT,
    license_status      TEXT NOT NULL DEFAULT 'pending' CHECK (license_status IN ('pending','approved','restricted','rejected','unknown')),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS instrument (
    instrument_id       BIGSERIAL PRIMARY KEY,
    symbol              VARCHAR(16) NOT NULL,
    exchange_code       VARCHAR(12) NOT NULL CHECK (exchange_code IN ('HOSE','HNX','UPCOM','INDEX','OTHER')),
    instrument_type     VARCHAR(24) NOT NULL DEFAULT 'equity',
    company_name        TEXT,
    sector_code         VARCHAR(40),
    industry_code       VARCHAR(60),
    currency            CHAR(3) NOT NULL DEFAULT 'VND',
    price_scale         NUMERIC(12,6) NOT NULL DEFAULT 1 CHECK (price_scale > 0),
    lot_size            INTEGER,
    listing_date        DATE,
    delisting_date      DATE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from          TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to            TIMESTAMPTZ,
    source_id           BIGINT REFERENCES data_source(source_id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(symbol, exchange_code, valid_from),
    CHECK (delisting_date IS NULL OR listing_date IS NULL OR delisting_date >= listing_date)
);
CREATE INDEX IF NOT EXISTS ix_instrument_symbol ON instrument(symbol);
CREATE INDEX IF NOT EXISTS ix_instrument_exchange_active ON instrument(exchange_code, is_active);

CREATE TABLE IF NOT EXISTS market_session (
    session_date        DATE PRIMARY KEY,
    exchange_code       VARCHAR(12) NOT NULL DEFAULT 'HOSE',
    is_trading_day      BOOLEAN NOT NULL,
    session_label       TEXT,
    open_at             TIMESTAMPTZ,
    close_at            TIMESTAMPTZ,
    calendar_source_id  BIGINT REFERENCES data_source(source_id),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingest_job (
    job_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id           BIGINT NOT NULL REFERENCES data_source(source_id),
    job_type            TEXT NOT NULL CHECK (job_type IN ('master_data','quote_snapshot','trade_stream','ohlcv','fundamentals','corporate_actions','index_data','reconciliation')),
    status              TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','partial','failed','cancelled')),
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    records_received    BIGINT NOT NULL DEFAULT 0,
    records_inserted    BIGINT NOT NULL DEFAULT 0,
    records_rejected    BIGINT NOT NULL DEFAULT 0,
    watermark_from      TIMESTAMPTZ,
    watermark_to        TIMESTAMPTZ,
    error_code          TEXT,
    error_message       TEXT,
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ingest_job_status_created ON ingest_job(status, created_at DESC);

CREATE TABLE IF NOT EXISTS raw_event (
    raw_event_id        BIGSERIAL PRIMARY KEY,
    source_id           BIGINT NOT NULL REFERENCES data_source(source_id),
    job_id              UUID REFERENCES ingest_job(job_id),
    event_type          TEXT NOT NULL,
    provider_event_id   TEXT,
    symbol              VARCHAR(16),
    exchange_code       VARCHAR(12),
    event_time          TIMESTAMPTZ,
    received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload             JSONB NOT NULL,
    payload_sha256      CHAR(64) NOT NULL,
    parse_status        TEXT NOT NULL DEFAULT 'pending' CHECK (parse_status IN ('pending','parsed','rejected')),
    parse_error         TEXT,
    UNIQUE(source_id, payload_sha256)
);
CREATE INDEX IF NOT EXISTS ix_raw_event_symbol_time ON raw_event(symbol, event_time DESC);
CREATE INDEX IF NOT EXISTS ix_raw_event_payload_gin ON raw_event USING GIN(payload);

CREATE TABLE IF NOT EXISTS quote_snapshot (
    instrument_id       BIGINT NOT NULL REFERENCES instrument(instrument_id),
    source_id           BIGINT NOT NULL REFERENCES data_source(source_id),
    quote_time          TIMESTAMPTZ NOT NULL,
    received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_price          NUMERIC(20,6),
    change_value        NUMERIC(20,6),
    change_pct          NUMERIC(12,6),
    reference_price     NUMERIC(20,6),
    ceiling_price       NUMERIC(20,6),
    floor_price         NUMERIC(20,6),
    open_price          NUMERIC(20,6),
    high_price          NUMERIC(20,6),
    low_price           NUMERIC(20,6),
    matched_volume      BIGINT,
    matched_value       NUMERIC(28,4),
    foreign_buy_volume  BIGINT,
    foreign_sell_volume BIGINT,
    bid1_price          NUMERIC(20,6), bid1_volume BIGINT,
    bid2_price          NUMERIC(20,6), bid2_volume BIGINT,
    bid3_price          NUMERIC(20,6), bid3_volume BIGINT,
    ask1_price          NUMERIC(20,6), ask1_volume BIGINT,
    ask2_price          NUMERIC(20,6), ask2_volume BIGINT,
    ask3_price          NUMERIC(20,6), ask3_volume BIGINT,
    quality_flags       JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_event_id        BIGINT REFERENCES raw_event(raw_event_id),
    PRIMARY KEY(instrument_id, source_id, quote_time)
);
CREATE INDEX IF NOT EXISTS ix_quote_time ON quote_snapshot(quote_time DESC);

CREATE TABLE IF NOT EXISTS trade_tick (
    trade_tick_id       BIGSERIAL PRIMARY KEY,
    instrument_id       BIGINT NOT NULL REFERENCES instrument(instrument_id),
    source_id           BIGINT NOT NULL REFERENCES data_source(source_id),
    trade_time          TIMESTAMPTZ NOT NULL,
    provider_trade_id   TEXT,
    price               NUMERIC(20,6) NOT NULL CHECK (price > 0),
    quantity            BIGINT NOT NULL CHECK (quantity >= 0),
    side                VARCHAR(12),
    trade_value         NUMERIC(28,4),
    received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_event_id        BIGINT REFERENCES raw_event(raw_event_id)
);
CREATE INDEX IF NOT EXISTS ix_trade_tick_time ON trade_tick(instrument_id, trade_time DESC);
CREATE UNIQUE INDEX IF NOT EXISTS ux_trade_tick_provider_id ON trade_tick(instrument_id, source_id, provider_trade_id) WHERE provider_trade_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS ohlcv_bar (
    instrument_id       BIGINT NOT NULL REFERENCES instrument(instrument_id),
    source_id           BIGINT NOT NULL REFERENCES data_source(source_id),
    timeframe           VARCHAR(8) NOT NULL CHECK (timeframe IN ('1m','3m','5m','15m','30m','1h','1d','1w','1mo')),
    bar_start           TIMESTAMPTZ NOT NULL,
    bar_end             TIMESTAMPTZ NOT NULL,
    open_price          NUMERIC(20,6) NOT NULL CHECK (open_price > 0),
    high_price          NUMERIC(20,6) NOT NULL CHECK (high_price > 0),
    low_price           NUMERIC(20,6) NOT NULL CHECK (low_price > 0),
    close_price         NUMERIC(20,6) NOT NULL CHECK (close_price > 0),
    volume              BIGINT NOT NULL DEFAULT 0 CHECK (volume >= 0),
    value_traded        NUMERIC(28,4),
    adjusted_close      NUMERIC(20,6),
    is_final            BOOLEAN NOT NULL DEFAULT FALSE,
    corporate_action_version TEXT,
    quality_flags       JSONB NOT NULL DEFAULT '[]'::jsonb,
    raw_event_id        BIGINT REFERENCES raw_event(raw_event_id),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(instrument_id, source_id, timeframe, bar_start),
    CHECK (bar_end > bar_start),
    CHECK (high_price >= GREATEST(open_price, close_price, low_price)),
    CHECK (low_price <= LEAST(open_price, close_price, high_price))
);
CREATE INDEX IF NOT EXISTS ix_ohlcv_symbol_time ON ohlcv_bar(instrument_id, timeframe, bar_start DESC);

CREATE TABLE IF NOT EXISTS index_bar (
    index_code          VARCHAR(24) NOT NULL,
    source_id           BIGINT NOT NULL REFERENCES data_source(source_id),
    timeframe           VARCHAR(8) NOT NULL,
    bar_start           TIMESTAMPTZ NOT NULL,
    bar_end             TIMESTAMPTZ NOT NULL,
    open_value          NUMERIC(20,6), high_value NUMERIC(20,6),
    low_value            NUMERIC(20,6), close_value NUMERIC(20,6) NOT NULL,
    change_value        NUMERIC(20,6), change_pct NUMERIC(12,6),
    volume              BIGINT,
    advancers           INTEGER,
    decliners           INTEGER,
    unchanged_count     INTEGER,
    received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(index_code, source_id, timeframe, bar_start)
);

CREATE TABLE IF NOT EXISTS corporate_action (
    action_id           BIGSERIAL PRIMARY KEY,
    instrument_id       BIGINT NOT NULL REFERENCES instrument(instrument_id),
    source_id           BIGINT NOT NULL REFERENCES data_source(source_id),
    action_type         TEXT NOT NULL CHECK (action_type IN ('cash_dividend','stock_dividend','split','rights_issue','bonus_issue','other')),
    announcement_date   DATE,
    ex_date             DATE,
    record_date         DATE,
    payment_date        DATE,
    cash_per_share      NUMERIC(20,6),
    share_ratio         NUMERIC(20,8),
    subscription_price  NUMERIC(20,6),
    status              TEXT NOT NULL DEFAULT 'announced',
    source_reference    TEXT,
    raw_event_id        BIGINT REFERENCES raw_event(raw_event_id),
    UNIQUE(instrument_id, source_id, action_type, ex_date, share_ratio, cash_per_share)
);
CREATE INDEX IF NOT EXISTS ix_corporate_action_ex_date ON corporate_action(instrument_id, ex_date);

CREATE TABLE IF NOT EXISTS financial_period (
    period_id           BIGSERIAL PRIMARY KEY,
    instrument_id       BIGINT NOT NULL REFERENCES instrument(instrument_id),
    source_id           BIGINT NOT NULL REFERENCES data_source(source_id),
    fiscal_year         SMALLINT NOT NULL,
    fiscal_quarter      SMALLINT CHECK (fiscal_quarter BETWEEN 1 AND 4),
    period_start        DATE,
    period_end          DATE NOT NULL,
    published_at        TIMESTAMPTZ,
    available_at        TIMESTAMPTZ NOT NULL,
    currency            CHAR(3) NOT NULL DEFAULT 'VND',
    consolidated        BOOLEAN NOT NULL DEFAULT TRUE,
    statement_type      TEXT NOT NULL CHECK (statement_type IN ('income','balance_sheet','cash_flow','ratios')),
    source_reference    TEXT,
    raw_event_id        BIGINT REFERENCES raw_event(raw_event_id),
    UNIQUE(instrument_id, source_id, fiscal_year, fiscal_quarter, statement_type, consolidated)
);
CREATE INDEX IF NOT EXISTS ix_financial_period_asof ON financial_period(instrument_id, available_at DESC);

CREATE TABLE IF NOT EXISTS financial_metric (
    period_id           BIGINT NOT NULL REFERENCES financial_period(period_id) ON DELETE CASCADE,
    metric_code         VARCHAR(64) NOT NULL,
    metric_value        NUMERIC(28,8),
    unit                VARCHAR(24),
    calculation_method  TEXT NOT NULL DEFAULT 'reported',
    quality_flags       JSONB NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY(period_id, metric_code)
);
CREATE INDEX IF NOT EXISTS ix_financial_metric_code ON financial_metric(metric_code, metric_value);

CREATE TABLE IF NOT EXISTS indicator_snapshot (
    instrument_id       BIGINT NOT NULL REFERENCES instrument(instrument_id),
    timeframe           VARCHAR(8) NOT NULL,
    as_of               TIMESTAMPTZ NOT NULL,
    calculation_version TEXT NOT NULL,
    values_json         JSONB NOT NULL,
    source_bar_end      TIMESTAMPTZ NOT NULL,
    quality_flags       JSONB NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY(instrument_id, timeframe, as_of, calculation_version)
);

CREATE TABLE IF NOT EXISTS feature_snapshot (
    instrument_id       BIGINT NOT NULL REFERENCES instrument(instrument_id),
    as_of               TIMESTAMPTZ NOT NULL,
    feature_set_version TEXT NOT NULL,
    features            JSONB NOT NULL,
    labels_available_at TIMESTAMPTZ,
    data_cutoff_at      TIMESTAMPTZ NOT NULL,
    quality_score       NUMERIC(5,4) CHECK (quality_score BETWEEN 0 AND 1),
    PRIMARY KEY(instrument_id, as_of, feature_set_version)
);

CREATE TABLE IF NOT EXISTS model_registry (
    model_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name          TEXT NOT NULL,
    model_version       TEXT NOT NULL,
    model_family        TEXT NOT NULL,
    target_definition   TEXT NOT NULL,
    horizon_sessions    INTEGER NOT NULL CHECK (horizon_sessions > 0),
    feature_set_version TEXT NOT NULL,
    training_start      DATE,
    training_end        DATE,
    validation_start    DATE,
    validation_end      DATE,
    status              TEXT NOT NULL CHECK (status IN ('draft','challenger','approved','retired','failed')),
    metrics             JSONB NOT NULL DEFAULT '{}'::jsonb,
    artifact_uri        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at         TIMESTAMPTZ,
    UNIQUE(model_name, model_version)
);

CREATE TABLE IF NOT EXISTS forecast_run (
    run_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id            UUID NOT NULL REFERENCES model_registry(model_id),
    run_type            TEXT NOT NULL CHECK (run_type IN ('live','backtest','research','paper')),
    as_of               TIMESTAMPTZ NOT NULL,
    data_cutoff_at      TIMESTAMPTZ NOT NULL,
    code_version        TEXT NOT NULL,
    params              JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              TEXT NOT NULL CHECK (status IN ('running','succeeded','partial','failed')),
    error_message       TEXT,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS forecast (
    run_id              UUID NOT NULL REFERENCES forecast_run(run_id) ON DELETE CASCADE,
    instrument_id       BIGINT NOT NULL REFERENCES instrument(instrument_id),
    horizon_sessions    INTEGER NOT NULL CHECK (horizon_sessions > 0),
    target_code         TEXT NOT NULL,
    probability_up      NUMERIC(8,7) CHECK (probability_up BETWEEN 0 AND 1),
    expected_return     NUMERIC(16,8),
    lower_quantile      NUMERIC(16,8),
    upper_quantile      NUMERIC(16,8),
    volatility_estimate NUMERIC(16,8),
    var_95              NUMERIC(16,8),
    cvar_95             NUMERIC(16,8),
    score               NUMERIC(8,4),
    confidence_label    TEXT NOT NULL DEFAULT 'experimental',
    explanation         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(run_id, instrument_id, horizon_sessions, target_code),
    CHECK (lower_quantile IS NULL OR upper_quantile IS NULL OR lower_quantile <= upper_quantile)
);
CREATE INDEX IF NOT EXISTS ix_forecast_symbol_created ON forecast(instrument_id, created_at DESC);

CREATE TABLE IF NOT EXISTS backtest_run (
    backtest_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id            UUID NOT NULL REFERENCES model_registry(model_id),
    start_date          DATE NOT NULL,
    end_date            DATE NOT NULL,
    train_window_sessions INTEGER,
    test_window_sessions INTEGER NOT NULL,
    step_sessions       INTEGER NOT NULL,
    transaction_cost_bps NUMERIC(10,4) NOT NULL DEFAULT 0,
    slippage_bps        NUMERIC(10,4) NOT NULL DEFAULT 0,
    benchmark_code      TEXT NOT NULL DEFAULT 'VNINDEX',
    split_config        JSONB NOT NULL,
    metrics             JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings            JSONB NOT NULL DEFAULT '[]'::jsonb,
    run_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS validation_fold (
    fold_id             BIGSERIAL PRIMARY KEY,
    backtest_id         UUID NOT NULL REFERENCES backtest_run(backtest_id) ON DELETE CASCADE,
    fold_number         INTEGER NOT NULL,
    train_start         DATE NOT NULL,
    train_end           DATE NOT NULL,
    test_start          DATE NOT NULL,
    test_end            DATE NOT NULL,
    n_observations      INTEGER NOT NULL DEFAULT 0,
    metrics             JSONB NOT NULL DEFAULT '{}'::jsonb,
    warnings            JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE(backtest_id, fold_number),
    CHECK (test_start > train_end),
    CHECK (test_end >= test_start)
);

CREATE TABLE IF NOT EXISTS app_user (
    user_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email               TEXT UNIQUE,
    password_hash       TEXT,
    auth_provider       TEXT NOT NULL DEFAULT 'local',
    role                TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin','researcher')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at       TIMESTAMPTZ,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS watchlist (
    watchlist_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    is_default          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS watchlist_item (
    watchlist_id        UUID NOT NULL REFERENCES watchlist(watchlist_id) ON DELETE CASCADE,
    instrument_id       BIGINT NOT NULL REFERENCES instrument(instrument_id),
    note                TEXT,
    added_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(watchlist_id, instrument_id)
);

CREATE TABLE IF NOT EXISTS alert_rule (
    alert_rule_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    instrument_id       BIGINT REFERENCES instrument(instrument_id) ON DELETE CASCADE,
    rule_type           TEXT NOT NULL CHECK (rule_type IN ('price_above','price_below','volume_spike','rsi_threshold','score_threshold','forecast_probability','data_stale')),
    rule_config         JSONB NOT NULL,
    delivery_channels   JSONB NOT NULL DEFAULT '["in_app"]'::jsonb,
    is_enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    cooldown_seconds    INTEGER NOT NULL DEFAULT 900 CHECK (cooldown_seconds >= 0),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_event (
    alert_event_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_rule_id       UUID NOT NULL REFERENCES alert_rule(alert_rule_id) ON DELETE CASCADE,
    triggered_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    observed_value      NUMERIC(24,8),
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    delivery_status     TEXT NOT NULL DEFAULT 'pending' CHECK (delivery_status IN ('pending','sent','failed','suppressed')),
    delivered_at        TIMESTAMPTZ,
    error_message       TEXT
);
CREATE INDEX IF NOT EXISTS ix_alert_event_pending ON alert_event(delivery_status, triggered_at DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    audit_id            BIGSERIAL PRIMARY KEY,
    user_id             UUID REFERENCES app_user(user_id),
    action              TEXT NOT NULL,
    object_type         TEXT,
    object_id           TEXT,
    ip_hash             TEXT,
    details             JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_audit_log_time ON audit_log(occurred_at DESC);

-- Security/deployment notes:
-- 1. Never store broker API keys or plaintext tokens in these app tables.
-- 2. Store raw provider payloads only under the applicable data licence/retention terms.
-- 3. Use separate DB roles: ingest_writer, analytics_writer, api_reader, migration_admin.
-- 4. Consider monthly partitioning for quote_snapshot/trade_tick/ohlcv_bar at production scale.
