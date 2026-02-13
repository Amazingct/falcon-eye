const { Pool } = require('pg');
const config = require('./config');

const pool = new Pool({
  host: config.db.host,
  port: config.db.port,
  user: config.db.user,
  password: config.db.password,
  database: config.db.database,
  // Connection pool settings
  max: 10,
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
});

// Log connection events
pool.on('connect', () => {
  console.log('Database pool: new client connected');
});

pool.on('error', (err) => {
  console.error('Database pool error:', err.message);
});

// Initialize database tables
async function initDB() {
  const client = await pool.connect();
  try {
    await client.query(`
      CREATE TABLE IF NOT EXISTS cameras (
        id UUID PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        protocol VARCHAR(50) NOT NULL,
        location VARCHAR(255),
        source_url TEXT,
        device_path VARCHAR(255),
        node_name VARCHAR(255),
        deployment_name VARCHAR(255),
        service_name VARCHAR(255),
        stream_port INTEGER,
        control_port INTEGER,
        status VARCHAR(50) DEFAULT 'pending',
        resolution VARCHAR(20) DEFAULT '${config.camera.resolution}',
        framerate INTEGER DEFAULT ${config.camera.framerate},
        metadata JSONB DEFAULT '{}',
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
      );
      
      CREATE INDEX IF NOT EXISTS idx_cameras_status ON cameras(status);
      CREATE INDEX IF NOT EXISTS idx_cameras_protocol ON cameras(protocol);
      CREATE INDEX IF NOT EXISTS idx_cameras_node ON cameras(node_name);
      CREATE INDEX IF NOT EXISTS idx_cameras_name ON cameras(name);
    `);
    console.log('Database initialized');
  } finally {
    client.release();
  }
}

// Graceful shutdown
async function closeDB() {
  await pool.end();
  console.log('Database pool closed');
}

module.exports = { pool, initDB, closeDB };
