CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    service_date TEXT NOT NULL,
    spot TEXT NOT NULL,
    people_count INTEGER DEFAULT 1,
    phone TEXT DEFAULT '',
    price REAL DEFAULT 0,
    unit_price REAL DEFAULT 0,
    assignee TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    raw_input TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
