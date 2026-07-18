-- migrations/001_init.sql
-- Полная схема БД для MVP (14 таблиц)
-- PostgreSQL 15, UUID, JSONB, asyncpg совместимо

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================
-- 1. АГЕНТСТВА (multi-tenant)
-- ============================================
CREATE TABLE agencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    base_city TEXT NOT NULL,
    subscription_plan TEXT DEFAULT 'mvp' CHECK (subscription_plan IN ('mvp', 'pro', 'enterprise')),
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_agencies_base_city ON agencies(base_city);

-- ============================================
-- 2. ГОРОДА ПРОДАЖ (мульти-гео)
-- ============================================
CREATE TABLE geo_locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    city_name TEXT NOT NULL,
    region TEXT,
    geo_type TEXT NOT NULL CHECK (geo_type IN ('base', 'sales', 'partner')),
    market_profile JSONB DEFAULT '{}',
    keywords JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,
    auto_discovery_enabled BOOLEAN DEFAULT true,
    partner_agency_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(agency_id, city_name, region)
);
CREATE INDEX idx_geo_agency ON geo_locations(agency_id);
CREATE INDEX idx_geo_active ON geo_locations(is_active) WHERE is_active = true;

-- ============================================
-- 3. ЗАЩИЩЁННЫЕ ГЕО (конкурентное преимущество)
-- ============================================
CREATE TABLE protected_geos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    city_name TEXT NOT NULL,
    region TEXT,
    protected_by_agency_id UUID REFERENCES agencies(id) ON DELETE SET NULL,
    protection_radius_km INTEGER DEFAULT 100,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(city_name, region)
);
CREATE INDEX idx_protected_geo_lookup ON protected_geos(city_name, region, is_active);

-- ============================================
-- 4. ИСТОЧНИКИ МОНИТОРИНГА
-- ============================================
CREATE TABLE sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    geo_location_id UUID REFERENCES geo_locations(id) ON DELETE SET NULL,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'telegram_chat', 'telegram_channel', 'vk_group',
        'youtube', 'forum', 'rss', 'website'
    )),
    source_url TEXT NOT NULL,
    source_name TEXT,
    external_id TEXT,
    status TEXT DEFAULT 'sandbox' CHECK (status IN ('sandbox', 'active', 'paused', 'blocked')),
    score INTEGER DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
    signals_per_day FLOAT DEFAULT 0,
    last_checked_at TIMESTAMPTZ,
    auto_found BOOLEAN DEFAULT false,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_sources_agency_geo ON sources(agency_id, geo_location_id);
CREATE INDEX idx_sources_status ON sources(status) WHERE status IN ('active', 'sandbox');

-- ============================================
-- 5. СИГНАЛЫ НАМЕРЕНИЯ (сырые данные)
-- ============================================
CREATE TABLE signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    geo_location_id UUID REFERENCES geo_locations(id) ON DELETE SET NULL,
    raw_text TEXT NOT NULL,
    author_hash TEXT,
    author_display_name TEXT,
    signal_url TEXT,
    intent_score INTEGER CHECK (intent_score BETWEEN 0 AND 100),
    segment TEXT CHECK (segment IN (
        'family', 'investor', 'relocant', 'remote_worker',
        'alternative', 'senior', 'student_parent', 'not_buyer'
    )),
    budget_min INTEGER,
    budget_max INTEGER,
    location_interest TEXT,
    urgency TEXT CHECK (urgency IN ('hot', 'warm', 'cold')),
    status TEXT DEFAULT 'new' CHECK (status IN (
        'new', 'viewed', 'in_progress', 'qualified', 'rejected', 'archived'
    )),
    ai_analysis JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_signals_agency_geo_status ON signals(agency_id, geo_location_id, status);
CREATE INDEX idx_signals_created ON signals(created_at DESC);
CREATE INDEX idx_signals_intent ON signals(intent_score) WHERE intent_score IS NOT NULL;
CREATE INDEX idx_signals_raw_text_fts ON signals USING gin(to_tsvector('russian', raw_text));

-- ============================================
-- 6. ЛИДЫ (квалифицированные контакты) — ПД ШИФРУЮТСЯ!
-- ============================================
CREATE TABLE leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    geo_location_id UUID REFERENCES geo_locations(id) ON DELETE SET NULL,
    signal_id UUID REFERENCES signals(id) ON DELETE SET NULL,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'signal', 'lead_magnet', 'manual', 'referral', 'incoming_call'
    )),
    source_platform TEXT CHECK (source_platform IN ('telegram', 'max', 'web', 'manual')),
    -- ПЕРСОНАЛЬНЫЕ ДАННЫЕ (шифруются в приложении через Fernet)
    name_encrypted BYTEA,
    phone_encrypted BYTEA,
    telegram_username TEXT,
    email_encrypted BYTEA,
    consent_given BOOLEAN DEFAULT false,
    consent_given_at TIMESTAMPTZ,
    consent_text TEXT,
    consent_version TEXT DEFAULT '1.0',
    consent_ip INET,
    consent_user_agent TEXT,
    -- Профиль покупателя
    segment TEXT,
    buyer_profile JSONB DEFAULT '{}',
    intent_score INTEGER,
    budget_min INTEGER,
    budget_max INTEGER,
    purchase_goal TEXT CHECK (purchase_goal IN ('own', 'invest', 'rent_out', 'relocate', 'children')),
    urgency TEXT CHECK (urgency IN ('hot', 'warm', 'cold')),
    lead_type TEXT DEFAULT 'buyer' CHECK (lead_type IN ('buyer', 'alternative', 'investor', 'relocant')),
    alternative_seller_data JSONB,
    assigned_to UUID,
    status TEXT DEFAULT 'new' CHECK (status IN (
        'new', 'in_progress', 'qualified', 'deal', 'rejected', 'archived', 'referred'
    )),
    rejection_reason TEXT,
    referred_to UUID,
    ai_qualification JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_leads_agency_status ON leads(agency_id, status);
CREATE INDEX idx_leads_assigned ON leads(assigned_to) WHERE assigned_to IS NOT NULL;
CREATE INDEX idx_leads_created ON leads(created_at DESC);

-- ============================================
-- 7. ОБЪЕКТЫ НЕДВИЖИМОСТИ
-- ============================================
CREATE TABLE properties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    geo_location_id UUID REFERENCES geo_locations(id) ON DELETE SET NULL,
    partner_agency_id UUID,
    title TEXT NOT NULL,
    property_type TEXT CHECK (property_type IN (
        'apartment', 'house', 'commercial', 'land', 'studio'
    )),
    deal_type TEXT DEFAULT 'sale' CHECK (deal_type IN ('sale', 'rent')),
    developer TEXT,
    address TEXT,
    district TEXT,
    price INTEGER,
    price_per_sqm INTEGER,
    area_total FLOAT,
    area_living FLOAT,
    rooms INTEGER,
    floor INTEGER,
    floors_total INTEGER,
    year_built INTEGER,
    is_new_build BOOLEAN DEFAULT false,
    readiness_status TEXT CHECK (readiness_status IN (
        'ready', 'under_construction', 'foundation', 'planning'
    )),
    readiness_date DATE,
    amenities JSONB DEFAULT '[]',
    target_segments JSONB DEFAULT '[]',
    investment_roi FLOAT,
    description_original TEXT,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'sold', 'reserved', 'archive')),
    source_url TEXT,
    images JSONB DEFAULT '[]',
    ai_analysis JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_properties_agency_geo ON properties(agency_id, geo_location_id, status);
CREATE INDEX idx_properties_price ON properties(price) WHERE status = 'active';

-- ============================================
-- 8. МАТЧИНГ ЛИД ↔ ОБЪЕКТ
-- ============================================
CREATE TABLE lead_property_matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    property_id UUID NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    match_score INTEGER CHECK (match_score BETWEEN 0 AND 100),
    match_reasons JSONB DEFAULT '[]',
    generated_pitch TEXT,
    status TEXT DEFAULT 'suggested' CHECK (status IN (
        'suggested', 'sent', 'viewed', 'interested', 'rejected'
    )),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(lead_id, property_id)
);
CREATE INDEX idx_matches_lead ON lead_property_matches(lead_id);
CREATE INDEX idx_matches_property ON lead_property_matches(property_id);
CREATE INDEX idx_matches_score ON lead_property_matches(match_score DESC);

-- ============================================
-- 9. МЕНЕДЖЕРЫ (мульти-платформа)
-- ============================================
CREATE TABLE managers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    telegram_id BIGINT UNIQUE,
    max_user_id BIGINT UNIQUE,
    preferred_platform TEXT DEFAULT 'telegram' CHECK (preferred_platform IN ('telegram', 'max', 'both')),
    phone_encrypted BYTEA,
    email_encrypted BYTEA,
    role TEXT DEFAULT 'manager' CHECK (role IN ('manager', 'admin', 'owner')),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_managers_agency ON managers(agency_id, is_active);

-- ============================================
-- 10. ЗАДАЧИ ДЛЯ МЕНЕДЖЕРОВ
-- ============================================
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    lead_id UUID REFERENCES leads(id) ON DELETE CASCADE,
    manager_id UUID REFERENCES managers(id) ON DELETE SET NULL,
    task_type TEXT NOT NULL CHECK (task_type IN (
        'contact', 'follow_up', 'showing', 'call_back',
        'referral_confirmation', 'alternative_sell', 'alternative_buy'
    )),
    title TEXT NOT NULL,
    description TEXT,
    suggested_message TEXT,
    due_at TIMESTAMPTZ,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'overdue', 'cancelled')),
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_tasks_manager_status ON tasks(manager_id, status);
CREATE INDEX idx_tasks_due ON tasks(due_at) WHERE status = 'pending';

-- ============================================
-- 11. ПАРТНЁРСКИЕ АГЕНТСТВА
-- ============================================
CREATE TABLE partner_agencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    partner_name TEXT NOT NULL,
    partner_city TEXT NOT NULL,
    partner_region TEXT,
    contact_name TEXT,
    contact_telegram TEXT,
    contact_phone_encrypted BYTEA,
    commission_percent FLOAT,
    commission_fixed INTEGER,
    commission_type TEXT DEFAULT 'percent' CHECK (commission_type IN ('percent', 'fixed', 'hybrid')),
    trust_level TEXT DEFAULT 'standard' CHECK (trust_level IN ('standard', 'verified', 'premium')),
    deals_count INTEGER DEFAULT 0,
    total_commission_earned INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_partners_agency ON partner_agencies(agency_id, is_active);

-- ============================================
-- 12. РЕФЕРАЛЫ (передача лидов партнёрам)
-- ============================================
CREATE TABLE partner_referrals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    partner_agency_id UUID NOT NULL REFERENCES partner_agencies(id) ON DELETE CASCADE,
    lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    referred_by_manager_id UUID REFERENCES managers(id) ON DELETE SET NULL,
    geo_location_id UUID REFERENCES geo_locations(id) ON DELETE SET NULL,
    referral_terms TEXT,
    commission_agreed_percent FLOAT,
    commission_agreed_fixed INTEGER,
    status TEXT DEFAULT 'pending' CHECK (status IN (
        'pending', 'accepted', 'in_progress', 'deal_done',
        'rejected', 'expired', 'dispute'
    )),
    deal_amount INTEGER,
    commission_amount INTEGER,
    partner_feedback TEXT,
    partner_contact_added BOOLEAN DEFAULT false,
    accepted_at TIMESTAMPTZ,
    deal_closed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    status_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_referrals_status ON partner_referrals(status);
CREATE INDEX idx_referrals_expires ON partner_referrals(expires_at) WHERE status = 'pending';

-- ============================================
-- 13. РЕЗУЛЬТАТЫ СДЕЛОК (Knowledge Moat)
-- ============================================
CREATE TABLE deal_outcomes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    lead_id UUID REFERENCES leads(id) ON DELETE SET NULL,
    property_id UUID REFERENCES properties(id) ON DELETE SET NULL,
    source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
    manager_id UUID REFERENCES managers(id) ON DELETE SET NULL,
    geo_location_id UUID REFERENCES geo_locations(id) ON DELETE SET NULL,
    partner_referral_id UUID REFERENCES partner_referrals(id) ON DELETE SET NULL,
    outcome TEXT NOT NULL CHECK (outcome IN (
        'deal_done', 'rejected', 'lost_to_competitor', 'expired', 'referral_deal'
    )),
    deal_amount INTEGER,
    commission_amount INTEGER,
    deal_closed_at TIMESTAMPTZ,
    -- Метрики воронки
    source_to_signal_days INTEGER,
    signal_to_lead_days INTEGER,
    lead_to_contact_days INTEGER,
    contact_to_deal_days INTEGER,
    total_days_to_close INTEGER,
    -- Аналитика
    winning_factors JSONB DEFAULT '[]',
    losing_factors JSONB DEFAULT '[]',
    objections_overcome JSONB DEFAULT '[]',
    buyer_segment TEXT,
    lead_magnet_used TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_deals_agency ON deal_outcomes(agency_id);
CREATE INDEX idx_deals_closed ON deal_outcomes(deal_closed_at) WHERE outcome = 'deal_done';

-- ============================================
-- 14. ЛОГ DISCOVERY ИСТОЧНИКОВ
-- ============================================
CREATE TABLE source_discovery_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    geo_location_id UUID REFERENCES geo_locations(id) ON DELETE SET NULL,
    discovery_method TEXT CHECK (discovery_method IN (
        'keyword_search', 'related', 'linked', 'manual'
    )),
    found_sources JSONB DEFAULT '[]',
    processed_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- 15. ЛОГ ДЕЙСТВИЙ (аудит)
-- ============================================
CREATE TABLE activity_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agency_id UUID NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
    lead_id UUID REFERENCES leads(id) ON DELETE SET NULL,
    manager_id UUID REFERENCES managers(id) ON DELETE SET NULL,
    action_type TEXT NOT NULL,
    description TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_activity_lead ON activity_log(lead_id);
CREATE INDEX idx_activity_manager ON activity_log(manager_id);
