-- AI 토론 시뮬레이터 - PostgreSQL 초기화 스크립트
-- 프로덕션 프로파일에서 PostgreSQL 사용 시 실행됩니다.

-- 데이터베이스 생성
CREATE DATABASE IF NOT EXISTS debate_simulator;

-- 토론 세션 테이블
CREATE TABLE IF NOT EXISTS debate_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic TEXT NOT NULL,
    format VARCHAR(50) NOT NULL,
    max_rounds INTEGER DEFAULT 5,
    status VARCHAR(20) DEFAULT 'created',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 토론 인수 테이블
CREATE TABLE IF NOT EXISTS debate_arguments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES debate_sessions(id),
    agent_name VARCHAR(100) NOT NULL,
    stance VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    quality_score FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_arguments_session ON debate_arguments(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON debate_sessions(status);
