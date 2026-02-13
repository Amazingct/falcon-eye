const express = require('express');
const { initDB } = require('./db');
const camerasRouter = require('./routes/cameras');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(express.json());

// Request logging
app.use((req, res, next) => {
  console.log(`${new Date().toISOString()} ${req.method} ${req.path}`);
  next();
});

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// API info
app.get('/', (req, res) => {
  res.json({
    name: 'Falcon-Eye Camera Manager',
    version: '1.0.0',
    endpoints: {
      'GET /health': 'Health check',
      'GET /api/cameras': 'List all cameras',
      'GET /api/cameras/:id': 'Get camera details',
      'POST /api/cameras': 'Add new camera',
      'PATCH /api/cameras/:id': 'Update camera',
      'DELETE /api/cameras/:id': 'Delete camera',
      'POST /api/cameras/:id/restart': 'Restart camera deployment',
      'GET /api/cameras/:id/stream-info': 'Get stream URLs',
    },
    protocols: ['usb', 'rtsp', 'onvif', 'http'],
  });
});

// Camera routes
app.use('/api/cameras', camerasRouter);

// Error handler
app.use((err, req, res, next) => {
  console.error('Unhandled error:', err);
  res.status(500).json({ error: 'Internal server error' });
});

// Start server
async function start() {
  try {
    await initDB();
    console.log('Database connected');

    app.listen(PORT, '0.0.0.0', () => {
      console.log(`Falcon-Eye Camera Manager running on port ${PORT}`);
      console.log(`API docs: http://localhost:${PORT}/`);
    });
  } catch (err) {
    console.error('Failed to start:', err);
    process.exit(1);
  }
}

start();
