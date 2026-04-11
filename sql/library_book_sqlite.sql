-- SQLite 馆藏书目表（与 Action 中 library_db 结构一致；亦可仅用 Python 首次自动建表+种子）
-- 使用：sqlite3 backend/data/library.db < sql/library_book_sqlite.sql
-- 或：在 backend 目录 sqlite3 data/library.db < ../sql/library_book_sqlite.sql

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS library_book (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_key TEXT NOT NULL UNIQUE,
    lib_book TEXT NOT NULL,
    book_pos TEXT,
    is_borrow INTEGER NOT NULL DEFAULT 0 CHECK (is_borrow IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_library_book_is_borrow ON library_book (is_borrow);
CREATE INDEX IF NOT EXISTS idx_library_book_lib_book ON library_book (lib_book);

-- 若表已有数据请勿重复执行 INSERT
INSERT OR IGNORE INTO library_book (book_key, lib_book, book_pos, is_borrow) VALUES
    ('B-HLM-001', '红楼梦（人民文学）', '文学库 A-01', 0),
    ('B-XYJ-002', '西游记（人民文学）', '文学库 A-02', 1),
    ('TP311.5/PY-01', 'Python 程序设计', '科技库 T-03', 0),
    ('TP311/DL-01', '深度学习入门', '科技库 T-05', 0),
    ('I247.5/XX-01', '平凡的世界', '文学库 B-10', 0);
