const express = require('express');
const { v4: uuidv4 } = require('uuid');
const { pool } = require('../db');
const k8s = require('../services/k8s');
const config = require('../config');

const router = express.Router();

// List all cameras
router.get('/', async (req, res) => {
  try {
    const { protocol, status, node } = req.query;
    let query = 'SELECT * FROM cameras WHERE 1=1';
    const params = [];

    if (protocol) {
      params.push(protocol);
      query += ` AND protocol = $${params.length}`;
    }
    if (status) {
      params.push(status);
      query += ` AND status = $${params.length}`;
    }
    if (node) {
      params.push(node);
      query += ` AND node_name = $${params.length}`;
    }

    query += ' ORDER BY created_at DESC';
    
    const result = await pool.query(query, params);
    
    // Enrich with live status
    const cameras = await Promise.all(result.rows.map(async (cam) => {
      if (cam.deployment_name) {
        const k8sStatus = await k8s.getDeploymentStatus(cam.deployment_name);
        cam.k8s_status = k8sStatus;
      }
      return cam;
    }));

    res.json({ cameras, total: cameras.length });
  } catch (err) {
    console.error('List cameras error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Get single camera
router.get('/:id', async (req, res) => {
  try {
    const result = await pool.query('SELECT * FROM cameras WHERE id = $1', [req.params.id]);
    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Camera not found' });
    }

    const camera = result.rows[0];
    if (camera.deployment_name) {
      camera.k8s_status = await k8s.getDeploymentStatus(camera.deployment_name);
    }

    // Build stream URLs
    if (camera.stream_port && camera.node_name) {
      const nodeIP = config.getNodeIP(camera.node_name);
      camera.stream_url = `http://${nodeIP}:${camera.stream_port}`;
      if (camera.control_port) {
        camera.control_url = `http://${nodeIP}:${camera.control_port}`;
      }
    }

    res.json(camera);
  } catch (err) {
    console.error('Get camera error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Add new camera
router.post('/', async (req, res) => {
  const client = await pool.connect();
  try {
    const {
      name,
      protocol,
      location,
      source_url,
      device_path,
      node_name,
      resolution,
      framerate,
      metadata,
    } = req.body;

    // Validate required fields
    if (!name || !protocol) {
      return res.status(400).json({ error: 'name and protocol are required' });
    }

    // Validate protocol
    const validProtocols = ['usb', 'rtsp', 'onvif', 'http'];
    if (!validProtocols.includes(protocol)) {
      return res.status(400).json({ 
        error: `Invalid protocol. Must be one of: ${validProtocols.join(', ')}` 
      });
    }

    // Protocol-specific validation
    if (protocol === 'usb' && !node_name) {
      return res.status(400).json({ error: 'node_name is required for USB cameras' });
    }
    if (['rtsp', 'onvif', 'http'].includes(protocol) && !source_url) {
      return res.status(400).json({ error: 'source_url is required for this protocol' });
    }

    const id = uuidv4();

    await client.query('BEGIN');

    // Insert camera record
    const insertResult = await client.query(`
      INSERT INTO cameras (id, name, protocol, location, source_url, device_path, node_name, resolution, framerate, metadata, status)
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'creating')
      RETURNING *
    `, [id, name, protocol, location, source_url, device_path, node_name, resolution || '640x480', framerate || 15, JSON.stringify(metadata || {})]);

    const camera = insertResult.rows[0];

    // Create K8s deployment
    try {
      const { deploymentName, serviceName, streamPort, controlPort } = await k8s.createCameraDeployment(camera);

      // Update camera with deployment info
      await client.query(`
        UPDATE cameras 
        SET deployment_name = $1, service_name = $2, stream_port = $3, control_port = $4, status = 'running', updated_at = NOW()
        WHERE id = $5
      `, [deploymentName, serviceName, streamPort, controlPort, id]);

      camera.deployment_name = deploymentName;
      camera.service_name = serviceName;
      camera.stream_port = streamPort;
      camera.control_port = controlPort;
      camera.status = 'running';

      // Build stream URL
      const nodeIP = config.getNodeIP(node_name);
      camera.stream_url = `http://${nodeIP}:${streamPort}`;

    } catch (k8sErr) {
      await client.query(`
        UPDATE cameras SET status = 'error', metadata = metadata || $1, updated_at = NOW() WHERE id = $2
      `, [JSON.stringify({ error: k8sErr.message }), id]);
      camera.status = 'error';
      camera.error = k8sErr.message;
    }

    await client.query('COMMIT');

    res.status(201).json(camera);
  } catch (err) {
    await client.query('ROLLBACK');
    console.error('Add camera error:', err);
    res.status(500).json({ error: err.message });
  } finally {
    client.release();
  }
});

// Update camera
router.patch('/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const updates = req.body;

    // Check camera exists
    const existing = await pool.query('SELECT * FROM cameras WHERE id = $1', [id]);
    if (existing.rows.length === 0) {
      return res.status(404).json({ error: 'Camera not found' });
    }

    // Build update query
    const allowedFields = ['name', 'location', 'resolution', 'framerate', 'metadata'];
    const setClauses = [];
    const values = [];

    for (const [key, value] of Object.entries(updates)) {
      if (allowedFields.includes(key)) {
        values.push(key === 'metadata' ? JSON.stringify(value) : value);
        setClauses.push(`${key} = $${values.length}`);
      }
    }

    if (setClauses.length === 0) {
      return res.status(400).json({ error: 'No valid fields to update' });
    }

    values.push(id);
    setClauses.push(`updated_at = NOW()`);

    const result = await pool.query(
      `UPDATE cameras SET ${setClauses.join(', ')} WHERE id = $${values.length} RETURNING *`,
      values
    );

    res.json(result.rows[0]);
  } catch (err) {
    console.error('Update camera error:', err);
    res.status(500).json({ error: err.message });
  }
});

// Delete camera
router.delete('/:id', async (req, res) => {
  const client = await pool.connect();
  try {
    const { id } = req.params;

    const existing = await client.query('SELECT * FROM cameras WHERE id = $1', [id]);
    if (existing.rows.length === 0) {
      return res.status(404).json({ error: 'Camera not found' });
    }

    const camera = existing.rows[0];

    await client.query('BEGIN');

    // Delete K8s resources
    if (camera.deployment_name || camera.service_name) {
      await k8s.deleteCameraDeployment(camera.deployment_name, camera.service_name);
    }

    // Delete from database
    await client.query('DELETE FROM cameras WHERE id = $1', [id]);

    await client.query('COMMIT');

    res.json({ message: 'Camera deleted', id });
  } catch (err) {
    await client.query('ROLLBACK');
    console.error('Delete camera error:', err);
    res.status(500).json({ error: err.message });
  } finally {
    client.release();
  }
});

// Restart camera (recreate deployment)
router.post('/:id/restart', async (req, res) => {
  const client = await pool.connect();
  try {
    const { id } = req.params;

    const existing = await client.query('SELECT * FROM cameras WHERE id = $1', [id]);
    if (existing.rows.length === 0) {
      return res.status(404).json({ error: 'Camera not found' });
    }

    const camera = existing.rows[0];

    await client.query('BEGIN');

    // Delete existing deployment
    if (camera.deployment_name || camera.service_name) {
      await k8s.deleteCameraDeployment(camera.deployment_name, camera.service_name);
    }

    // Recreate deployment
    const { deploymentName, serviceName, streamPort, controlPort } = await k8s.createCameraDeployment(camera);

    // Update camera record
    await client.query(`
      UPDATE cameras 
      SET deployment_name = $1, service_name = $2, stream_port = $3, control_port = $4, status = 'running', updated_at = NOW()
      WHERE id = $5
    `, [deploymentName, serviceName, streamPort, controlPort, id]);

    await client.query('COMMIT');

    res.json({ 
      message: 'Camera restarted',
      deployment_name: deploymentName,
      service_name: serviceName,
      stream_port: streamPort,
    });
  } catch (err) {
    await client.query('ROLLBACK');
    console.error('Restart camera error:', err);
    res.status(500).json({ error: err.message });
  } finally {
    client.release();
  }
});

// Get camera stream info (for proxying)
router.get('/:id/stream-info', async (req, res) => {
  try {
    const result = await pool.query('SELECT * FROM cameras WHERE id = $1', [req.params.id]);
    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Camera not found' });
    }

    const camera = result.rows[0];
    const nodeIP = config.getNodeIP(camera.node_name);

    res.json({
      id: camera.id,
      name: camera.name,
      stream_url: camera.stream_port ? `http://${nodeIP}:${camera.stream_port}` : null,
      control_url: camera.control_port ? `http://${nodeIP}:${camera.control_port}` : null,
      protocol: camera.protocol,
      status: camera.status,
    });
  } catch (err) {
    console.error('Stream info error:', err);
    res.status(500).json({ error: err.message });
  }
});

module.exports = router;
