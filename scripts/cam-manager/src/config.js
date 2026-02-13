// Falcon-Eye Camera Manager Configuration
// Loads from environment variables with sensible defaults

const config = {
  // Server
  port: parseInt(process.env.PORT) || 3000,
  nodeEnv: process.env.NODE_ENV || 'development',

  // Database
  db: {
    host: process.env.DB_HOST || 'localhost',
    port: parseInt(process.env.DB_PORT) || 5432,
    user: process.env.DB_USER || 'admin',
    password: process.env.DB_PASSWORD || 'amazingct',
    database: process.env.DB_NAME || 'homedb',
  },

  // Kubernetes
  k8s: {
    namespace: process.env.K8S_NAMESPACE || 'falcon-eye',
    configPath: process.env.KUBECONFIG_PATH || process.env.KUBECONFIG,
    apiServer: process.env.K8S_API_SERVER,
    token: process.env.K8S_TOKEN,
    caCert: process.env.K8S_CA_CERT,
  },

  // Node IPs for stream URL generation
  nodeIPs: {
    ace: process.env.NODE_IP_ACE || '192.168.1.142',
    falcon: process.env.NODE_IP_FALCON || '192.168.1.176',
    'k3s-1': process.env.NODE_IP_K3S1 || '192.168.1.207',
    'k3s-2': process.env.NODE_IP_K3S2 || '192.168.1.138',
  },

  // NodePort range
  ports: {
    streamStart: parseInt(process.env.STREAM_PORT_START) || 30900,
    streamEnd: parseInt(process.env.STREAM_PORT_END) || 30999,
  },

  // Camera defaults
  camera: {
    resolution: process.env.DEFAULT_RESOLUTION || '640x480',
    framerate: parseInt(process.env.DEFAULT_FRAMERATE) || 15,
    quality: parseInt(process.env.DEFAULT_STREAM_QUALITY) || 70,
  },

  // Jetson nodes (require tolerations)
  jetsonNodes: ['ace', 'falcon'],
};

// Helper to get node IP
config.getNodeIP = (nodeName) => {
  return config.nodeIPs[nodeName] || config.nodeIPs['k3s-1'];
};

// Helper to check if node is Jetson
config.isJetsonNode = (nodeName) => {
  return config.jetsonNodes.includes(nodeName);
};

module.exports = config;
