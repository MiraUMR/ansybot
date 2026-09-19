-- Story Mode V1.5 sessions
CREATE TABLE IF NOT EXISTS story_sessions (
    session_id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    initiator_qq TEXT NOT NULL,
    status TEXT DEFAULT 'ACTIVE',
    scene_type TEXT,
    scene_desc TEXT,
    participants TEXT,
    turn_count INTEGER DEFAULT 0,
    max_turns INTEGER DEFAULT 7,
    history_log TEXT,
    recipient_meta TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_story_sessions_group_status
    ON story_sessions(group_id, status);
