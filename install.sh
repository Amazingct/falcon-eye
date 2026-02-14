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
RELEASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/falcon-eye/main"
IS_UPGRADE=false

echo -e "${BLUE}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║                    🦅 FALCON-EYE                          ║"
echo "║         Distributed Camera Streaming for K8s              ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check prerequisites
check_prerequisites() {
    echo -e "${YELLOW}[1/8] Checking prerequisites...${NC}"
    
    if ! command -v kubectl &> /dev/null; then
        echo -e "${RED}✗ kubectl not found. Please install kubectl first.${NC}"
        echo "  Visit: https://kubernetes.io/docs/tasks/tools/"
        exit 1
    fi
    echo -e "${GREEN}✓ kubectl found${NC}"
    
    if ! kubectl cluster-info &> /dev/null; then
        echo -e "${RED}✗ Cannot connect to Kubernetes cluster.${NC}"
        echo ""
        echo "Please ensure:"
        echo "  1. Your kubeconfig is set up (~/.kube/config)"
        echo "  2. Or set KUBECONFIG environment variable"
        echo ""
        exit 1
    fi
    echo -e "${GREEN}✓ Connected to Kubernetes cluster${NC}"
    
    CLUSTER_NAME=$(kubectl config current-context 2>/dev/null || echo "unknown")
    echo -e "  Cluster context: ${BLUE}${CLUSTER_NAME}${NC}"
}

# Check for existing installation
check_existing() {
    echo -e "${YELLOW}[2/8] Checking for existing installation...${NC}"
    
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

# Detect cluster nodes
detect_nodes() {
    echo -e "${YELLOW}[3/8] Detecting cluster nodes...${NC}"
    
    NODE_COUNT=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
    echo -e "${GREEN}✓ Found ${NODE_COUNT} node(s)${NC}"
    
    echo ""
    kubectl get nodes -o wide --no-headers | while read line; do
        NODE_NAME=$(echo $line | awk '{print $1}')
        NODE_STATUS=$(echo $line | awk '{print $2}')
        NODE_IP=$(echo $line | awk '{print $6}')
        echo -e "  • ${NODE_NAME} (${NODE_STATUS}) - ${NODE_IP}"
    done
    echo ""
}

# Create namespace
create_namespace() {
    echo -e "${YELLOW}[4/8] Setting up namespace '${NAMESPACE}'...${NC}"
    
    if kubectl get namespace ${NAMESPACE} &> /dev/null; then
        echo -e "${GREEN}✓ Namespace '${NAMESPACE}' exists${NC}"
    else
        kubectl create namespace ${NAMESPACE}
        echo -e "${GREEN}✓ Namespace '${NAMESPACE}' created${NC}"
    fi
}

# Deploy PostgreSQL
deploy_database() {
    echo -e "${YELLOW}[5/8] Deploying PostgreSQL database...${NC}"
    
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
    echo -e "${YELLOW}[6/8] Deploying Falcon-Eye API...${NC}"
    
    cat <<EOF | kubectl apply -n ${NAMESPACE} -f -
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: falcon-eye-config
data:
  DATABASE_URL: "postgresql://falcon:falcon-eye-2026@postgres:5432/falconeye"
  NODE_ENV: "production"
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
      containers:
      - name: api
        image: ${REGISTRY}/${REPO_OWNER}/falcon-eye-api:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 3000
        envFrom:
        - configMapRef:
            name: falcon-eye-config
        resources:
          requests:
            memory: "128Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
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
  - port: 3000
    targetPort: 3000
    nodePort: 30901
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
  resources: ["pods", "services", "configmaps"]
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
    echo -e "${YELLOW}[7/8] Deploying Falcon-Eye Dashboard...${NC}"
    
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
      containers:
      - name: dashboard
        image: ${REGISTRY}/${REPO_OWNER}/falcon-eye-dashboard:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 80
        env:
        - name: API_URL
          value: "http://falcon-eye-api:3000"
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

# Deploy cleanup CronJob
deploy_cleanup_cronjob() {
    echo -e "${YELLOW}[8/8] Deploying cleanup CronJob...${NC}"
    
    # Get cleanup interval from ConfigMap or use default
    CLEANUP_INTERVAL=$(kubectl get configmap falcon-eye-config -n ${NAMESPACE} -o jsonpath='{.data.CLEANUP_INTERVAL}' 2>/dev/null || echo "*/10 * * * *")
    
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
    
    # Get node IPs
    NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null)
    
    if [ -z "$NODE_IP" ]; then
        NODE_IP="<node-ip>"
    fi
    
    echo -e "${YELLOW}Access URLs:${NC}"
    echo -e "  📊 Dashboard:  http://${NODE_IP}:30900"
    echo -e "  🔌 API:        http://${NODE_IP}:30901"
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
    
    # Get node IP
    NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null)
    if [ -z "$NODE_IP" ]; then
        NODE_IP="<node-ip>"
    fi
    
    echo -e "${GREEN}✓ Falcon-Eye is installed${NC}"
    echo ""
    
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${YELLOW}                        ACCESS URLS                         ${NC}"
    echo -e "${YELLOW}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "  📊 ${CYAN}Dashboard${NC}:  http://${NODE_IP}:30900"
    echo -e "  🔌 ${CYAN}API${NC}:        http://${NODE_IP}:30901"
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
    create_namespace
    deploy_database
    deploy_backend
    deploy_frontend
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
