const k8s = require('@kubernetes/client-node');
const config = require('../config');

const kc = new k8s.KubeConfig();

// Load kubeconfig based on environment
if (config.k8s.configPath) {
  kc.loadFromFile(config.k8s.configPath);
} else if (config.k8s.apiServer && config.k8s.token) {
  // External cluster access
  kc.loadFromOptions({
    clusters: [{
      name: 'falcon-eye-cluster',
      server: config.k8s.apiServer,
      caData: config.k8s.caCert,
      skipTLSVerify: !config.k8s.caCert,
    }],
    users: [{
      name: 'falcon-eye-user',
      token: config.k8s.token,
    }],
    contexts: [{
      name: 'falcon-eye-context',
      cluster: 'falcon-eye-cluster',
      user: 'falcon-eye-user',
    }],
    currentContext: 'falcon-eye-context',
  });
} else {
  // In-cluster or default kubeconfig
  try {
    kc.loadFromCluster();
  } catch (e) {
    kc.loadFromDefault();
  }
}

const k8sAppsApi = kc.makeApiClient(k8s.AppsV1Api);
const k8sCoreApi = kc.makeApiClient(k8s.CoreV1Api);

const NAMESPACE = config.k8s.namespace;

// Generate deployment manifest based on camera protocol
function generateDeployment(camera) {
  const { id, name, protocol, node_name, device_path, source_url, resolution, framerate } = camera;
  const deploymentName = `cam-${name.toLowerCase().replace(/[^a-z0-9]/g, '-')}`;
  const [width, height] = (resolution || '640x480').split('x');
  const fps = framerate || 15;

  // Base deployment template
  const deployment = {
    apiVersion: 'apps/v1',
    kind: 'Deployment',
    metadata: {
      name: deploymentName,
      namespace: NAMESPACE,
      labels: {
        app: 'falcon-eye',
        component: 'camera',
        'camera-id': id,
        protocol: protocol,
      },
    },
    spec: {
      replicas: 1,
      selector: {
        matchLabels: {
          'camera-id': id,
        },
      },
      template: {
        metadata: {
          labels: {
            app: 'falcon-eye',
            component: 'camera',
            'camera-id': id,
            protocol: protocol,
          },
        },
        spec: {
          containers: [getContainerSpec(protocol, camera, width, height, fps)],
          volumes: protocol === 'usb' ? [{
            name: 'dev-video',
            hostPath: { path: device_path || '/dev/video0' },
          }] : [],
        },
      },
    },
  };

  // Add node selector and tolerations for Jetson nodes
  if (node_name) {
    deployment.spec.template.spec.nodeSelector = {
      'kubernetes.io/hostname': node_name,
    };
    // Add tolerations for Jetson nodes
    if (['ace', 'falcon'].includes(node_name)) {
      deployment.spec.template.spec.tolerations = [{
        key: 'dedicated',
        operator: 'Equal',
        value: 'jetson',
        effect: 'NoSchedule',
      }];
    }
  }

  return { deployment, deploymentName };
}

// Get container spec based on protocol
function getContainerSpec(protocol, camera, width, height, fps) {
  const { device_path, source_url, name } = camera;

  switch (protocol) {
    case 'usb':
      return {
        name: 'motion',
        image: 'ubuntu:22.04',
        command: ['/bin/bash', '-c'],
        args: [generateUSBScript(device_path, width, height, fps, name)],
        securityContext: { privileged: true },
        ports: [
          { containerPort: 8081, name: 'stream' },
          { containerPort: 8080, name: 'control' },
        ],
        volumeMounts: [{
          name: 'dev-video',
          mountPath: device_path || '/dev/video0',
        }],
        resources: {
          requests: { memory: '128Mi', cpu: '100m' },
          limits: { memory: '512Mi', cpu: '500m' },
        },
      };

    case 'rtsp':
      return {
        name: 'rtsp-relay',
        image: 'ubuntu:22.04',
        command: ['/bin/bash', '-c'],
        args: [generateRTSPScript(source_url, width, height, fps, name)],
        ports: [
          { containerPort: 8081, name: 'stream' },
        ],
        resources: {
          requests: { memory: '128Mi', cpu: '100m' },
          limits: { memory: '512Mi', cpu: '500m' },
        },
      };

    case 'onvif':
      return {
        name: 'onvif-relay',
        image: 'ubuntu:22.04',
        command: ['/bin/bash', '-c'],
        args: [generateONVIFScript(source_url, width, height, fps, name)],
        ports: [
          { containerPort: 8081, name: 'stream' },
        ],
        resources: {
          requests: { memory: '128Mi', cpu: '100m' },
          limits: { memory: '512Mi', cpu: '500m' },
        },
      };

    case 'http':
      return {
        name: 'http-relay',
        image: 'ubuntu:22.04',
        command: ['/bin/bash', '-c'],
        args: [generateHTTPScript(source_url, name)],
        ports: [
          { containerPort: 8081, name: 'stream' },
        ],
        resources: {
          requests: { memory: '64Mi', cpu: '50m' },
          limits: { memory: '256Mi', cpu: '250m' },
        },
      };

    default:
      throw new Error(`Unsupported protocol: ${protocol}`);
  }
}

// Script generators for each protocol
function generateUSBScript(devicePath, width, height, fps, label) {
  return `
apt-get update && apt-get install -y motion && \\
cat > /etc/motion/motion.conf << 'CONF'
daemon off
videodevice ${devicePath || '/dev/video0'}
width ${width}
height ${height}
framerate ${fps}
stream_port 8081
stream_localhost off
stream_maxrate ${fps}
stream_quality 70
webcontrol_port 8080
webcontrol_localhost off
picture_output off
movie_output off
text_left FALCON-EYE-${label.toUpperCase()}
text_right %Y-%m-%d\\n%T
CONF
motion -c /etc/motion/motion.conf
`;
}

function generateRTSPScript(rtspUrl, width, height, fps, label) {
  return `
apt-get update && apt-get install -y ffmpeg python3 python3-pip && \\
pip3 install flask && \\
cat > /app.py << 'PYEOF'
from flask import Flask, Response
import subprocess
import signal
import sys

app = Flask(__name__)

def gen_frames():
    cmd = [
        'ffmpeg', '-rtsp_transport', 'tcp',
        '-i', '${rtspUrl}',
        '-f', 'mjpeg',
        '-q:v', '5',
        '-r', '${fps}',
        '-s', '${width}x${height}',
        'pipe:1'
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            data = proc.stdout.read(4096)
            if not data:
                break
            yield (b'--frame\\r\\nContent-Type: image/jpeg\\r\\n\\r\\n' + data + b'\\r\\n')
    finally:
        proc.kill()

@app.route('/')
def index():
    return '<html><body><h1>FALCON-EYE-${label.toUpperCase()}</h1><img src="/stream"></body></html>'

@app.route('/stream')
def stream():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, threaded=True)
PYEOF
python3 /app.py
`;
}

function generateONVIFScript(onvifUrl, width, height, fps, label) {
  // ONVIF typically provides RTSP streams, so we extract and relay
  return `
apt-get update && apt-get install -y ffmpeg python3 python3-pip && \\
pip3 install flask onvif-zeep && \\
cat > /app.py << 'PYEOF'
from flask import Flask, Response
from onvif import ONVIFCamera
import subprocess
import re

app = Flask(__name__)

def get_rtsp_url():
    # Parse ONVIF URL: onvif://user:pass@host:port
    match = re.match(r'onvif://(?:([^:]+):([^@]+)@)?([^:/]+)(?::(\d+))?', '${onvifUrl}')
    if not match:
        return None
    user, passwd, host, port = match.groups()
    port = int(port) if port else 80
    try:
        cam = ONVIFCamera(host, port, user or 'admin', passwd or 'admin')
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        stream_uri = media.GetStreamUri({
            'StreamSetup': {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}},
            'ProfileToken': profiles[0].token
        })
        return stream_uri.Uri
    except Exception as e:
        print(f'ONVIF error: {e}')
        return None

rtsp_url = get_rtsp_url()

def gen_frames():
    if not rtsp_url:
        return
    cmd = [
        'ffmpeg', '-rtsp_transport', 'tcp',
        '-i', rtsp_url,
        '-f', 'mjpeg', '-q:v', '5',
        '-r', '${fps}', '-s', '${width}x${height}',
        'pipe:1'
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            data = proc.stdout.read(4096)
            if not data:
                break
            yield (b'--frame\\r\\nContent-Type: image/jpeg\\r\\n\\r\\n' + data + b'\\r\\n')
    finally:
        proc.kill()

@app.route('/')
def index():
    return '<html><body><h1>FALCON-EYE-${label.toUpperCase()}</h1><img src="/stream"></body></html>'

@app.route('/stream')
def stream():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, threaded=True)
PYEOF
python3 /app.py
`;
}

function generateHTTPScript(httpUrl, label) {
  return `
apt-get update && apt-get install -y python3 python3-pip curl && \\
pip3 install flask requests && \\
cat > /app.py << 'PYEOF'
from flask import Flask, Response
import requests

app = Flask(__name__)

def gen_frames():
    try:
        r = requests.get('${httpUrl}', stream=True, timeout=30)
        for chunk in r.iter_content(chunk_size=4096):
            yield chunk
    except Exception as e:
        print(f'Stream error: {e}')

@app.route('/')
def index():
    return '<html><body><h1>FALCON-EYE-${label.toUpperCase()}</h1><img src="/stream"></body></html>'

@app.route('/stream')
def stream():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, threaded=True)
PYEOF
python3 /app.py
`;
}

// Generate service manifest
function generateService(camera, deploymentName) {
  const { id, name } = camera;
  const serviceName = `svc-${name.toLowerCase().replace(/[^a-z0-9]/g, '-')}`;
  
  // Find next available NodePort (30900-30999 range for cameras)
  const basePort = 30900;
  
  return {
    service: {
      apiVersion: 'v1',
      kind: 'Service',
      metadata: {
        name: serviceName,
        namespace: NAMESPACE,
        labels: {
          app: 'falcon-eye',
          component: 'camera',
          'camera-id': id,
        },
      },
      spec: {
        type: 'NodePort',
        selector: {
          'camera-id': id,
        },
        ports: [
          {
            port: 8081,
            targetPort: 8081,
            name: 'stream',
          },
          {
            port: 8080,
            targetPort: 8080,
            name: 'control',
          },
        ],
      },
    },
    serviceName,
  };
}

// Create camera deployment and service
async function createCameraDeployment(camera) {
  const { deployment, deploymentName } = generateDeployment(camera);
  const { service, serviceName } = generateService(camera, deploymentName);

  try {
    // Create deployment
    await k8sAppsApi.createNamespacedDeployment(NAMESPACE, deployment);
    console.log(`Created deployment: ${deploymentName}`);

    // Create service
    const createdService = await k8sCoreApi.createNamespacedService(NAMESPACE, service);
    const streamPort = createdService.body.spec.ports.find(p => p.name === 'stream')?.nodePort;
    const controlPort = createdService.body.spec.ports.find(p => p.name === 'control')?.nodePort;
    console.log(`Created service: ${serviceName} (stream: ${streamPort}, control: ${controlPort})`);

    return {
      deploymentName,
      serviceName,
      streamPort,
      controlPort,
    };
  } catch (err) {
    console.error('K8s error:', err.body?.message || err.message);
    throw err;
  }
}

// Delete camera deployment and service
async function deleteCameraDeployment(deploymentName, serviceName) {
  try {
    await k8sAppsApi.deleteNamespacedDeployment(deploymentName, NAMESPACE);
    console.log(`Deleted deployment: ${deploymentName}`);
  } catch (err) {
    if (err.statusCode !== 404) throw err;
  }

  try {
    await k8sCoreApi.deleteNamespacedService(serviceName, NAMESPACE);
    console.log(`Deleted service: ${serviceName}`);
  } catch (err) {
    if (err.statusCode !== 404) throw err;
  }
}

// Get deployment status
async function getDeploymentStatus(deploymentName) {
  try {
    const res = await k8sAppsApi.readNamespacedDeploymentStatus(deploymentName, NAMESPACE);
    const status = res.body.status;
    return {
      ready: status.readyReplicas === status.replicas,
      replicas: status.replicas || 0,
      readyReplicas: status.readyReplicas || 0,
      availableReplicas: status.availableReplicas || 0,
    };
  } catch (err) {
    if (err.statusCode === 404) return null;
    throw err;
  }
}

module.exports = {
  createCameraDeployment,
  deleteCameraDeployment,
  getDeploymentStatus,
  NAMESPACE,
};
