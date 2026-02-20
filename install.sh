#!/bin/bash
#
# Falcon-Eye Installer & Updater
# Install/update: curl -sSL https://raw.githubusercontent.com/Amazingct/falcon-eye/main/install.sh | bash
# Show status:    curl -sSL https://raw.githubusercontent.com/Amazingct/falcon-eye/main/install.sh | bash -s -- --status
#
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

NAMESPACE="falcon-eye"
REPO_OWNER="${FALCON_EYE_OWNER:-amazingct}"
REGISTRY="ghcr.io"
API_PORT=8000  # Single source of truth for API port
RELEASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/falcon-eye/main"
IS_UPGRADE=false

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                    🦅 FALCON-EYE                          ║"
echo "║         Distributed Camera Streaming for K8s              ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Install k3s (Linux) or k3d (macOS)
install_k3s() {
    OS_TYPE=$(uname -s)

    if [ "$OS_TYPE" = "Darwin" ]; then
        install_k3d_mac
    else
        install_k3s_linux
    fi
}

# Linux: native k3s install
install_k3s_linux() {
    echo -e "${YELLOW}Installing k3s...${NC}"

    curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644

    echo -e "${YELLOW}Waiting for k3s to start...${NC}"
    sleep 10

    mkdir -p ~/.kube
    sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
    sudo chown $(id -u):$(id -g) ~/.kube/config
    export KUBECONFIG=~/.kube/config

    echo -e "${YELLOW}Waiting for node to be ready...${NC}"
    kubectl wait --for=condition=Ready node --all --timeout=120s

    echo -e "${GREEN}✓ k3s installed successfully${NC}"
}

# macOS: k3s is Linux-only, so use k3d (k3s-in-Docker) instead
install_k3d_mac() {
    if [ "$(id -u)" -eq 0 ]; then
        echo -e "${YELLOW}⚠ Running as root is not recommended on macOS.${NC}"
        echo -e "${YELLOW}  k3d uses Docker Desktop and does not require sudo.${NC}"
        echo -e "${YELLOW}  Continuing anyway...${NC}"
        echo ""
    fi

    echo -e "${YELLOW}macOS detected — k3s requires Linux.${NC}"
    echo -e "${YELLOW}Installing k3d (runs k3s inside Docker containers)...${NC}"
    echo ""

    # Docker is required for k3d
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}✗ Docker is required for k3d on macOS but was not found.${NC}"
        echo -e "  Install Docker Desktop: ${CYAN}https://www.docker.com/products/docker-desktop/${NC}"
        exit 1
    fi

    if ! docker info &> /dev/null 2>&1; then
        echo -e "${RED}✗ Docker is installed but not running. Please start Docker Desktop and try again.${NC}"
        exit 1
    fi

    # Install k3d: prefer Homebrew when available and not running as root
    if command -v k3d &> /dev/null; then
        echo -e "${GREEN}✓ k3d already installed${NC}"
    elif [ "$(id -u)" -ne 0 ] && command -v brew &> /dev/null; then
        echo -e "${YELLOW}Installing k3d via Homebrew...${NC}"
        brew install k3d
    else
        echo -e "${YELLOW}Installing k3d via install script...${NC}"
        curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | TAG=v5.7.5 bash
    fi

    if ! command -v k3d &> /dev/null; then
        echo -e "${RED}✗ k3d installation failed${NC}"
        exit 1
    fi

    echo -e "${YELLOW}Creating k3d cluster 'falcon-eye'...${NC}"
    k3d cluster create falcon-eye \
        --port "30800:30800@server:0" \
        --port "30900:30900@server:0" \
        --wait --timeout 120s

    mkdir -p ~/.kube
    k3d kubeconfig get falcon-eye > ~/.kube/config
    chmod 600 ~/.kube/config
    export KUBECONFIG=~/.kube/config

    echo -e "${YELLOW}Waiting for node to be ready...${NC}"
    kubectl wait --for=condition=Ready node --all --timeout=120s

    echo -e "${GREEN}✓ k3d cluster created successfully (k3s running in Docker)${NC}"
}

# Set up kubeconfig from user input
setup_kubeconfig() {
    echo -e "${YELLOW}Please paste your kubeconfig content below.${NC}"
    echo -e "${YELLOW}When done, press Enter, then Ctrl+D (or type 'EOF' on a new line):${NC}"
    echo ""
    
    mkdir -p ~/.kube
    
    # Read multiline input
    KUBECONFIG_CONTENT=""
    while IFS= read -r line; do
        [[ "$line" == "EOF" ]] && break
        KUBECONFIG_CONTENT+="$line"$'\n'
    done
    
    echo "$KUBECONFIG_CONTENT" > ~/.kube/config
    chmod 600 ~/.kube/config
    export KUBECONFIG=~/.kube/config
    
    echo -e "${GREEN}✓ Kubeconfig saved to ~/.kube/config${NC}"
}

# Ensure kubectl is installed
ensure_kubectl() {
    if command -v kubectl &> /dev/null; then
        echo -e "${GREEN}✓ kubectl found${NC}"
        return
    fi

    echo -e "${YELLOW}⚠ kubectl not found. Installing...${NC}"

    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)
    case $ARCH in
        x86_64) ARCH="amd64" ;;
        aarch64|arm64) ARCH="arm64" ;;
        armv7l) ARCH="arm" ;;
    esac

    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/${OS}/${ARCH}/kubectl"
    chmod +x kubectl
    sudo mv kubectl /usr/local/bin/

    if command -v kubectl &> /dev/null; then
        echo -e "${GREEN}✓ kubectl installed${NC}"
    else
        echo -e "${RED}✗ Failed to install kubectl${NC}"
        exit 1
    fi
}

# Detect all reachable kubectl contexts and return them as a list
detect_contexts() {
    CONTEXTS=()
    CONTEXT_DETAILS=()

    while IFS= read -r ctx; do
        [ -z "$ctx" ] && continue
        if kubectl --context "$ctx" cluster-info &> /dev/null 2>&1; then
            CLUSTER_ENDPOINT=$(kubectl --context "$ctx" cluster-info 2>/dev/null | head -1 | awk '{print $NF}' | sed 's/\x1b\[[0-9;]*m//g')
            CONTEXTS+=("$ctx")
            CONTEXT_DETAILS+=("$ctx  →  $CLUSTER_ENDPOINT")
        fi
    done < <(kubectl config get-contexts -o name 2>/dev/null)
}

# Check prerequisites
check_prerequisites() {
    echo -e "${YELLOW}[1/9] Checking prerequisites...${NC}"

    ensure_kubectl

    # Non-interactive mode (piped stdin): try the current context silently
    if [ ! -t 0 ]; then
        if kubectl cluster-info &> /dev/null 2>&1; then
            echo -e "${GREEN}✓ Connected to Kubernetes cluster${NC}"
            CLUSTER_NAME=$(kubectl config current-context 2>/dev/null || echo "unknown")
            echo -e "  Cluster context: ${BLUE}${CLUSTER_NAME}${NC}"
            return
        else
            echo -e "${RED}✗ No reachable Kubernetes cluster found (non-interactive mode).${NC}"
            echo -e "  Set KUBECONFIG or configure ~/.kube/config and try again."
            exit 1
        fi
    fi

    echo ""
    echo -e "${CYAN}How would you like to set up the cluster?${NC}"
    echo ""

    if [ "$(uname -s)" = "Darwin" ]; then
        NEW_LABEL="Create a new cluster  (installs k3d — k3s-in-Docker, recommended for macOS)"
    else
        NEW_LABEL="Create a new cluster  (installs k3s, recommended for single-node setup)"
    fi

    echo -e "  ${CYAN}1)${NC} ${NEW_LABEL}"
    echo -e "  ${CYAN}2)${NC} Connect to an existing cluster"
    echo ""

    read -p "Enter choice [1-2]: " SETUP_CHOICE
    echo ""

    case $SETUP_CHOICE in
        1)
            if [ "$(uname -s)" = "Darwin" ]; then
                echo -e "${YELLOW}This will install k3d and create a k3s cluster in Docker.${NC}"
            else
                echo -e "${YELLOW}This will install k3s on this machine.${NC}"
            fi
            read -p "Continue? [y/N]: " CONFIRM_K3S
            if [[ "$CONFIRM_K3S" =~ ^[Yy]$ ]]; then
                install_k3s
            else
                echo -e "${RED}Aborted.${NC}"
                exit 1
            fi
            ;;
        2)
            choose_existing_cluster
            ;;
        *)
            echo -e "${RED}Invalid choice. Exiting.${NC}"
            exit 1
            ;;
    esac

    echo -e "${GREEN}✓ Connected to Kubernetes cluster${NC}"

    CLUSTER_NAME=$(kubectl config current-context 2>/dev/null || echo "unknown")
    echo -e "  Cluster context: ${BLUE}${CLUSTER_NAME}${NC}"
}

# Let user pick from existing contexts or paste a kubeconfig
choose_existing_cluster() {
    echo -e "${YELLOW}Scanning for reachable kubectl contexts...${NC}"
    detect_contexts

    # Build the menu dynamically
    MENU_ITEMS=()
    MENU_IDX=1

    if [ ${#CONTEXTS[@]} -gt 0 ]; then
        for detail in "${CONTEXT_DETAILS[@]}"; do
            echo -e "  ${CYAN}${MENU_IDX})${NC} ${detail}"
            MENU_ITEMS+=("ctx:$((MENU_IDX-1))")
            MENU_IDX=$((MENU_IDX+1))
        done
    else
        echo -e "  ${YELLOW}No reachable contexts found in kubeconfig.${NC}"
    fi

    echo -e "  ${CYAN}${MENU_IDX})${NC} Paste a kubeconfig manually"
    MENU_ITEMS+=("paste")
    PASTE_IDX=$MENU_IDX
    MENU_IDX=$((MENU_IDX+1))

    echo -e "  ${CYAN}${MENU_IDX})${NC} Exit and configure manually"
    MENU_ITEMS+=("exit")
    EXIT_IDX=$MENU_IDX
    echo ""

    read -p "Enter choice [1-${EXIT_IDX}]: " CTX_CHOICE
    echo ""

    # Validate input
    if ! [[ "$CTX_CHOICE" =~ ^[0-9]+$ ]] || [ "$CTX_CHOICE" -lt 1 ] || [ "$CTX_CHOICE" -gt "$EXIT_IDX" ]; then
        echo -e "${RED}Invalid choice. Exiting.${NC}"
        exit 1
    fi

    SELECTED="${MENU_ITEMS[$((CTX_CHOICE-1))]}"

    case "$SELECTED" in
        ctx:*)
            IDX="${SELECTED#ctx:}"
            CHOSEN_CTX="${CONTEXTS[$IDX]}"
            kubectl config use-context "$CHOSEN_CTX" > /dev/null
            echo -e "${GREEN}✓ Switched to context: ${CHOSEN_CTX}${NC}"
            ;;
        paste)
            setup_kubeconfig
            if ! kubectl cluster-info &> /dev/null 2>&1; then
                echo -e "${RED}✗ Cannot connect with the provided kubeconfig. Please check it and try again.${NC}"
                exit 1
            fi
            ;;
        exit)
            echo -e "Please configure kubectl manually:"
            echo "  1. Set up ~/.kube/config"
            echo "  2. Or set KUBECONFIG environment variable"
            echo "  3. Run this installer again"
            exit 1
            ;;
    esac
}

# Check for existing installation
check_existing() {
    echo -e "${YELLOW}[2/9] Checking for existing installation...${NC}"
    
    if kubectl get namespace ${NAMESPACE} &> /dev/null; then
        if kubectl get deployment falcon-eye-api -n ${NAMESPACE} &> /dev/null; then
            IS_UPGRADE=true
            CURRENT_API_IMAGE=$(kubectl get deployment falcon-eye-api -n ${NAMESPACE} -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "unknown")
            CURRENT_DASH_IMAGE=$(kubectl get deployment falcon-eye-dashboard -n ${NAMESPACE} -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "unknown")
            
            echo -e "${CYAN}✓ Existing installation found - will upgrade${NC}"
            echo -e "  Current API:       ${CURRENT_API_IMAGE}"
            echo -e "  Current Dashboard: ${CURRENT_DASH_IMAGE}"
            echo -e "  New images:        ${REGISTRY}/${REPO_OWNER}/falcon-eye-*:latest"
        else
            echo -e "${GREEN}✓ Namespace exists but no deployment - fresh install${NC}"
        fi
    else
        echo -e "${GREEN}✓ No existing installation - fresh install${NC}"
    fi
}

# Detect cluster nodes and identify the master
detect_nodes() {
    echo -e "${YELLOW}[3/9] Detecting cluster nodes...${NC}"
    
    NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
    echo -e "${GREEN}✓ Found ${NODE_COUNT} node(s)${NC}"
    
    # Detect master/control-plane node
    MASTER_NODE=$(kubectl get nodes -l 'node-role.kubernetes.io/control-plane' --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    if [ -z "$MASTER_NODE" ]; then
        MASTER_NODE=$(kubectl get nodes -l 'node-role.kubernetes.io/master' --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    fi
    if [ -z "$MASTER_NODE" ]; then
        # Fallback: first node in the cluster
        MASTER_NODE=$(kubectl get nodes --no-headers -o custom-columns=":metadata.name" 2>/dev/null | head -1)
    fi
    
    echo ""
    kubectl get nodes -o wide --no-headers | while read line; do
        NODE_NAME=$(echo $line | awk '{print $1}')
        NODE_STATUS=$(echo $line | awk '{print $2}')
        NODE_IP=$(echo $line | awk '{print $6}')
        MARKER=""
        [ "$NODE_NAME" = "$MASTER_NODE" ] && MARKER=" ${CYAN}(master)${NC}"
        echo -e "  • ${NODE_NAME} (${NODE_STATUS}) - ${NODE_IP}${MARKER}"
    done
    echo ""
    
    echo -e "  Master node: ${CYAN}${MASTER_NODE}${NC}"
    echo ""
}

# Helper function to prompt for node selection
select_node() {
    local COMPONENT_NAME="$1"
    local COMPONENT_DESC="$2"
    local VAR_NAME="$3"
    
    echo -e "  ${CYAN}${COMPONENT_NAME}${NC} - ${COMPONENT_DESC}"
    read -p "  Choose node [0-${NODE_COUNT}] (default: 0): " NODE_CHOICE
    
    if [ -n "$NODE_CHOICE" ] && [ "$NODE_CHOICE" != "0" ] && [ "$NODE_CHOICE" -le "$NODE_COUNT" ] 2>/dev/null; then
        eval "${VAR_NAME}=\"${NODES[$((NODE_CHOICE-1))]}\""
        eval "echo -e \"${GREEN}  ✓ ${COMPONENT_NAME}: \${${VAR_NAME}}${NC}\""
    else
        eval "${VAR_NAME}=\"\""
        echo -e "${GREEN}  ✓ ${COMPONENT_NAME}: auto-assigned${NC}"
    fi
    echo ""
}

# Prompt for optional configuration
configure_options() {
    # Non-interactive or upgrade: let Kubernetes scheduler decide placement
    if [ ! -t 0 ] || [ "$IS_UPGRADE" = true ]; then
        POSTGRES_NODE=""
        API_NODE=""
        DASHBOARD_NODE=""
        CAMERA_NODE=""
        RECORDER_NODE=""
        ANTHROPIC_API_KEY=""
        echo -e "${GREEN}  Auto-configured: Kubernetes scheduler will place all components${NC}"
        return
    fi
    
    echo -e "${YELLOW}[3.5/9] Optional Configuration...${NC}"
    echo ""
    
    # Get nodes and display options
    NODES=($(kubectl get nodes --no-headers -o custom-columns=":metadata.name" 2>/dev/null))
    NODE_COUNT=${#NODES[@]}
    
    if [ $NODE_COUNT -gt 1 ]; then
        echo -e "  ${CYAN}Node Selection:${NC}"
        echo -e "  Choose where to deploy each component (0 = auto-assign)"
        echo ""
        
        # Display node list
        for i in "${!NODES[@]}"; do
            NODE_STATUS=$(kubectl get node ${NODES[$i]} -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)
            STATUS_ICON="🟢"
            [ "$NODE_STATUS" != "True" ] && STATUS_ICON="🔴"
            echo -e "    ${CYAN}$((i+1)))${NC} ${NODES[$i]} ${STATUS_ICON}"
        done
        echo -e "    ${CYAN}0)${NC} Auto (let Kubernetes decide)"
        echo ""
        
        # Select nodes for each component
        select_node "PostgreSQL" "Database (needs stable storage)" "POSTGRES_NODE"
        select_node "API Server" "Backend service" "API_NODE"
        select_node "Dashboard" "Web UI" "DASHBOARD_NODE"
        select_node "Camera Streams" "Default node for camera pods" "CAMERA_NODE"
        
        echo -e "  ${CYAN}Recordings${NC} - Default node for recorder pods"
        echo -e "  ${YELLOW}Tip: Pin to one node to centralize all recordings on a single disk${NC}"
        read -p "  Choose node [0-${NODE_COUNT}] (default: 0 = auto): " NODE_CHOICE
        
        if [ -n "$NODE_CHOICE" ] && [ "$NODE_CHOICE" != "0" ] && [ "$NODE_CHOICE" -le "$NODE_COUNT" ] 2>/dev/null; then
            RECORDER_NODE="${NODES[$((NODE_CHOICE-1))]}"
            echo -e "${GREEN}  ✓ Recordings: ${RECORDER_NODE}${NC}"
        else
            RECORDER_NODE=""
            echo -e "${GREEN}  ✓ Recordings: auto-assigned${NC}"
        fi
        echo ""
        
    else
        POSTGRES_NODE=""
        API_NODE=""
        DASHBOARD_NODE=""
        CAMERA_NODE=""
        RECORDER_NODE=""
        echo -e "  Single node cluster - all components will deploy to: ${NODES[0]}"
        echo ""
    fi
    
    # Anthropic API key
    echo -e "  ${CYAN}AI Chatbot Configuration:${NC}"
    echo -e "  The AI chatbot requires an Anthropic API key."
    echo -e "  Get one at: ${CYAN}https://console.anthropic.com/settings/keys${NC}"
    echo ""
    read -p "  Enter Anthropic API key (or press Enter to skip): " ANTHROPIC_API_KEY
    
    if [ -n "$ANTHROPIC_API_KEY" ]; then
        echo -e "${GREEN}  ✓ API key configured - chatbot enabled${NC}"
    else
        echo -e "${YELLOW}  ⚠ Skipped - chatbot will be disabled${NC}"
    fi
    echo ""
}

# Create namespace
create_namespace() {
    echo -e "${YELLOW}[4/9] Setting up namespace '${NAMESPACE}'...${NC}"
    
    if kubectl get namespace ${NAMESPACE} &> /dev/null; then
        echo -e "${GREEN}✓ Namespace '${NAMESPACE}' exists${NC}"
    else
        kubectl create namespace ${NAMESPACE}
        echo -e "${GREEN}✓ Namespace '${NAMESPACE}' created${NC}"
    fi
}

# Deploy PostgreSQL
deploy_database() {
    echo -e "${YELLOW}[5/9] Deploying PostgreSQL database...${NC}"
    
    cat <<EOF | kubectl apply -n ${NAMESPACE} -f -
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Secret
metadata:
  name: postgres-secret
type: Opaque
stringData:
  POSTGRES_USER: falcon
  POSTGRES_PASSWORD: falcon-eye-2026
  POSTGRES_DB: falconeye
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
$([ -n "$POSTGRES_NODE" ] && echo "      nodeSelector:
        kubernetes.io/hostname: ${POSTGRES_NODE}")
      containers:
      - name: postgres
        image: postgres:15-alpine
        ports:
        - containerPort: 5432
        envFrom:
        - secretRef:
            name: postgres-secret
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
      volumes:
      - name: postgres-storage
        persistentVolumeClaim:
          claimName: postgres-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
spec:
  selector:
    app: postgres
  ports:
  - port: 5432
    targetPort: 5432
EOF
    
    echo -e "${GREEN}✓ PostgreSQL configured${NC}"
    
    # Wait for postgres only on fresh install
    if [ "$IS_UPGRADE" = false ]; then
        echo "  Waiting for PostgreSQL to be ready..."
        kubectl wait --for=condition=available deployment/postgres -n ${NAMESPACE} --timeout=120s 2>/dev/null || true
    fi
}

# Deploy Falcon-Eye backend
deploy_backend() {
    echo -e "${YELLOW}[6/9] Deploying Falcon-Eye API...${NC}"
    
    cat <<EOF | kubectl apply -n ${NAMESPACE} -f -
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: falcon-eye-config
data:
  DATABASE_URL: "postgresql://falcon:falcon-eye-2026@postgres:5432/falconeye"
  NODE_ENV: "production"
  CLEANUP_INTERVAL: "*/2 * * * *"
  CREATING_TIMEOUT_MINUTES: "15"
  DEFAULT_RESOLUTION: "640x480"
  DEFAULT_FRAMERATE: "15"
  ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY:-}"
  DEFAULT_CAMERA_NODE: "${CAMERA_NODE:-}"
  DEFAULT_RECORDER_NODE: "${RECORDER_NODE:-}"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: falcon-eye-api
  annotations:
    falcon-eye/updated: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: falcon-eye-api
  template:
    metadata:
      labels:
        app: falcon-eye-api
      annotations:
        falcon-eye/updated: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    spec:
      serviceAccountName: falcon-eye-sa
$([ -n "$API_NODE" ] && echo "      nodeSelector:
        kubernetes.io/hostname: ${API_NODE}")
      containers:
      - name: api
        image: ${REGISTRY}/${REPO_OWNER}/falcon-eye-api:latest
        imagePullPolicy: Always
        ports:
        - containerPort: ${API_PORT}
        envFrom:
        - configMapRef:
            name: falcon-eye-config
        volumeMounts:
        - name: recordings
          mountPath: /recordings
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
      volumes:
      - name: recordings
        hostPath:
          path: /data/falcon-eye/recordings
          type: DirectoryOrCreate
---
apiVersion: v1
kind: Service
metadata:
  name: falcon-eye-api
spec:
  type: NodePort
  selector:
    app: falcon-eye-api
  ports:
  - port: ${API_PORT}
    targetPort: ${API_PORT}
    nodePort: 30800
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: falcon-eye-sa
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: falcon-eye-role
rules:
- apiGroups: [""]
  resources: ["pods", "services", "configmaps", "secrets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["batch"]
  resources: ["cronjobs", "jobs"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: falcon-eye-binding
subjects:
- kind: ServiceAccount
  name: falcon-eye-sa
  namespace: ${NAMESPACE}
roleRef:
  kind: ClusterRole
  name: falcon-eye-role
  apiGroup: rbac.authorization.k8s.io
EOF
    
    echo -e "${GREEN}✓ Falcon-Eye API configured${NC}"
    
    # Force pull new image on upgrade
    if [ "$IS_UPGRADE" = true ]; then
        echo "  Restarting API to pull latest image..."
        kubectl rollout restart deployment/falcon-eye-api -n ${NAMESPACE} 2>/dev/null || true
    fi
}

# Deploy frontend
deploy_frontend() {
    echo -e "${YELLOW}[7/9] Deploying Falcon-Eye Dashboard...${NC}"
    
    cat <<EOF | kubectl apply -n ${NAMESPACE} -f -
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: falcon-eye-dashboard
  annotations:
    falcon-eye/updated: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
spec:
  replicas: 1
  selector:
    matchLabels:
      app: falcon-eye-dashboard
  template:
    metadata:
      labels:
        app: falcon-eye-dashboard
      annotations:
        falcon-eye/updated: "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    spec:
$([ -n "$DASHBOARD_NODE" ] && echo "      nodeSelector:
        kubernetes.io/hostname: ${DASHBOARD_NODE}")
      containers:
      - name: dashboard
        image: ${REGISTRY}/${REPO_OWNER}/falcon-eye-dashboard:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 80
        env:
        - name: API_URL
          value: "http://falcon-eye-api:${API_PORT}"
---
apiVersion: v1
kind: Service
metadata:
  name: falcon-eye-dashboard
spec:
  type: NodePort
  selector:
    app: falcon-eye-dashboard
  ports:
  - port: 80
    targetPort: 80
    nodePort: 30900
EOF
    
    echo -e "${GREEN}✓ Dashboard configured${NC}"
    
    # Force pull new image on upgrade
    if [ "$IS_UPGRADE" = true ]; then
        echo "  Restarting Dashboard to pull latest image..."
        kubectl rollout restart deployment/falcon-eye-dashboard -n ${NAMESPACE} 2>/dev/null || true
    fi
}

# Deploy file-server DaemonSet (serves recordings from every node)
deploy_file_server() {
    echo -e "${YELLOW}[8/9] Deploying recordings file-server...${NC}"
    
    cat <<'NGINXEOF' | kubectl apply -n ${NAMESPACE} -f - >/dev/null 2>&1 || true
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: file-server-nginx-config
data:
  default.conf: |
    server {
        listen 8080;
        root /recordings;
        location / {
            autoindex on;
            autoindex_format json;
        }
    }
NGINXEOF

    cat <<EOF | kubectl apply -n ${NAMESPACE} -f -
---
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: falcon-eye-file-server
  labels:
    app: falcon-eye
    component: file-server
spec:
  selector:
    matchLabels:
      app: falcon-eye
      component: file-server
  template:
    metadata:
      labels:
        app: falcon-eye
        component: file-server
    spec:
      tolerations:
      - operator: Exists
      containers:
      - name: nginx
        image: nginx:alpine
        ports:
        - containerPort: 8080
          name: http
        volumeMounts:
        - name: recordings
          mountPath: /recordings
          readOnly: true
        - name: nginx-config
          mountPath: /etc/nginx/conf.d
        resources:
          requests:
            memory: "16Mi"
            cpu: "10m"
          limits:
            memory: "64Mi"
            cpu: "100m"
      volumes:
      - name: recordings
        hostPath:
          path: /data/falcon-eye/recordings
          type: DirectoryOrCreate
      - name: nginx-config
        configMap:
          name: file-server-nginx-config
---
apiVersion: v1
kind: Service
metadata:
  name: falcon-eye-file-server
  labels:
    app: falcon-eye
    component: file-server
spec:
  clusterIP: None
  selector:
    app: falcon-eye
    component: file-server
  ports:
  - port: 8080
    targetPort: 8080
    name: http
EOF
    
    echo -e "${GREEN}✓ File-server DaemonSet configured (runs on every node)${NC}"
}

# Deploy cleanup CronJob
deploy_cleanup_cronjob() {
    echo -e "${YELLOW}[9/9] Deploying cleanup CronJob...${NC}"
    
    # Get cleanup interval from ConfigMap or use default (every 2 minutes)
    CLEANUP_INTERVAL=$(kubectl get configmap falcon-eye-config -n ${NAMESPACE} -o jsonpath='{.data.CLEANUP_INTERVAL}' 2>/dev/null)
    CLEANUP_INTERVAL="${CLEANUP_INTERVAL:-*/2 * * * *}"
    
    cat <<EOF | kubectl apply -n ${NAMESPACE} -f -
---
apiVersion: batch/v1
kind: CronJob
metadata:
  name: falcon-eye-cleanup
  labels:
    app: falcon-eye
    component: cleanup
spec:
  schedule: "${CLEANUP_INTERVAL}"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      activeDeadlineSeconds: 300
      template:
        metadata:
          labels:
            app: falcon-eye
            component: cleanup
        spec:
          restartPolicy: Never
          serviceAccountName: falcon-eye-sa
          containers:
          - name: cleanup
            image: ${REGISTRY}/${REPO_OWNER}/falcon-eye-api:latest
            imagePullPolicy: Always
            command: ["python", "-m", "app.tasks.cleanup"]
            env:
            - name: K8S_NAMESPACE
              value: "${NAMESPACE}"
            envFrom:
            - configMapRef:
                name: falcon-eye-config
            resources:
              requests:
                memory: "64Mi"
                cpu: "50m"
              limits:
                memory: "128Mi"
                cpu: "200m"
EOF
    
    echo -e "${GREEN}✓ Cleanup CronJob configured (runs: ${CLEANUP_INTERVAL})${NC}"
}

# Resolve the IP/hostname users should use to reach NodePort services
get_access_host() {
    local CONTEXT
    CONTEXT=$(kubectl config current-context 2>/dev/null || echo "")

    # k3d clusters use Docker networking; NodePorts are forwarded to localhost
    if echo "$CONTEXT" | grep -q "k3d-"; then
        echo "localhost"
        return
    fi

    # Default: use the first node's InternalIP
    local IP
    IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null)
    echo "${IP:-<node-ip>}"
}

# Wait for rollout
wait_for_rollout() {
    echo ""
    echo -e "${YELLOW}Waiting for deployments to be ready...${NC}"
    
    kubectl rollout status deployment/falcon-eye-api -n ${NAMESPACE} --timeout=120s 2>/dev/null || true
    kubectl rollout status deployment/falcon-eye-dashboard -n ${NAMESPACE} --timeout=120s 2>/dev/null || true
    
    echo -e "${GREEN}✓ All deployments ready${NC}"
}

# Get access info
print_access_info() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    if [ "$IS_UPGRADE" = true ]; then
        echo -e "${GREEN}🎉 Falcon-Eye upgraded successfully!${NC}"
    else
        echo -e "${GREEN}🎉 Falcon-Eye installed successfully!${NC}"
    fi
    echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    
    NODE_IP=$(get_access_host)
    
    echo -e "${YELLOW}Access:${NC}"
    echo -e "  📊 Dashboard:  http://${NODE_IP}:30900"
    echo -e "  🔌 API:        http://${NODE_IP}:30800"
    echo ""
    
    # Show pod status
    echo -e "${YELLOW}Pod Status:${NC}"
    kubectl get pods -n ${NAMESPACE} --no-headers 2>/dev/null | while read line; do
        POD_NAME=$(echo $line | awk '{print $1}')
        POD_STATUS=$(echo $line | awk '{print $3}')
        POD_READY=$(echo $line | awk '{print $2}')
        if [ "$POD_STATUS" = "Running" ]; then
            echo -e "  ${GREEN}✓${NC} ${POD_NAME} (${POD_READY})"
        else
            echo -e "  ${YELLOW}◐${NC} ${POD_NAME} (${POD_STATUS})"
        fi
    done
    echo ""
    
    echo -e "${YELLOW}Quick Commands:${NC}"
    echo "  # Check status"
    echo "  kubectl get pods -n ${NAMESPACE}"
    echo ""
    echo "  # View API logs"
    echo "  kubectl logs -n ${NAMESPACE} -l app=falcon-eye-api -f"
    echo ""
    echo "  # Update to latest"
    echo "  curl -sSL https://raw.githubusercontent.com/${REPO_OWNER}/falcon-eye/main/install.sh | bash"
    echo ""
    echo "  # Uninstall"
    echo "  kubectl delete namespace ${NAMESPACE}"
    echo ""
    echo -e "${BLUE}Documentation: https://github.com/${REPO_OWNER}/falcon-eye${NC}"
    echo ""
}

# Show status only
show_status() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║                 🦅 FALCON-EYE STATUS                      ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    
    if ! command -v kubectl &> /dev/null; then
        echo -e "${RED}✗ kubectl not found${NC}"
        exit 1
    fi
    
    if ! kubectl get namespace ${NAMESPACE} &> /dev/null; then
        echo -e "${RED}✗ Falcon-Eye is not installed${NC}"
        echo ""
        echo "Install with:"
        echo "  curl -sSL https://raw.githubusercontent.com/${REPO_OWNER}/falcon-eye/main/install.sh | bash"
        exit 1
    fi
    
    NODE_IP=$(get_access_host)
    
    echo -e "${GREEN}✓ Falcon-Eye is installed${NC}"
    echo ""
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}                        ACCESS URLS                         ${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  📊 ${CYAN}Dashboard${NC}:  http://${NODE_IP}:30900"
    echo -e "  🔌 ${CYAN}API${NC}:        http://${NODE_IP}:30800"
    echo ""
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}                        POD STATUS                          ${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    kubectl get pods -n ${NAMESPACE} --no-headers 2>/dev/null | while read line; do
        POD_NAME=$(echo $line | awk '{print $1}')
        POD_STATUS=$(echo $line | awk '{print $3}')
        POD_READY=$(echo $line | awk '{print $2}')
        POD_AGE=$(echo $line | awk '{print $5}')
        if [ "$POD_STATUS" = "Running" ]; then
            echo -e "  ${GREEN}●${NC} ${POD_NAME}"
            echo -e "    Status: ${GREEN}${POD_STATUS}${NC} | Ready: ${POD_READY} | Age: ${POD_AGE}"
        else
            echo -e "  ${YELLOW}●${NC} ${POD_NAME}"
            echo -e "    Status: ${YELLOW}${POD_STATUS}${NC} | Ready: ${POD_READY} | Age: ${POD_AGE}"
        fi
    done
    echo ""
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}                         IMAGES                             ${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    API_IMAGE=$(kubectl get deployment falcon-eye-api -n ${NAMESPACE} -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "not deployed")
    DASH_IMAGE=$(kubectl get deployment falcon-eye-dashboard -n ${NAMESPACE} -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || echo "not deployed")
    echo -e "  API:       ${API_IMAGE}"
    echo -e "  Dashboard: ${DASH_IMAGE}"
    echo ""
    
    echo -e "${YELLOW}Quick Commands:${NC}"
    echo "  # Update to latest"
    echo "  curl -sSL https://raw.githubusercontent.com/${REPO_OWNER}/falcon-eye/main/install.sh | bash"
    echo ""
    echo "  # View logs"
    echo "  kubectl logs -n ${NAMESPACE} -l app=falcon-eye-api -f"
    echo ""
    echo "  # Uninstall"
    echo "  kubectl delete namespace ${NAMESPACE}"
    echo ""
}

# Main installation flow
main() {
    check_prerequisites
    check_existing
    detect_nodes
    configure_options
    create_namespace
    deploy_database
    deploy_backend
    deploy_frontend
    deploy_file_server
    deploy_cleanup_cronjob
    wait_for_rollout
    print_access_info
}

# Parse arguments
case "${1:-}" in
    --status|-s|status)
        show_status
        ;;
    --help|-h|help)
        echo "Falcon-Eye Installer"
        echo ""
        echo "Usage:"
        echo "  install.sh           Install or upgrade Falcon-Eye"
        echo "  install.sh --status  Show current status and URLs"
        echo "  install.sh --help    Show this help"
        echo ""
        echo "Examples:"
        echo "  # Install/upgrade"
        echo "  curl -sSL https://raw.githubusercontent.com/${REPO_OWNER}/falcon-eye/main/install.sh | bash"
        echo ""
        echo "  # Check status"
        echo "  curl -sSL https://raw.githubusercontent.com/${REPO_OWNER}/falcon-eye/main/install.sh | bash -s -- --status"
        ;;
    *)
        main
        ;;
esac
