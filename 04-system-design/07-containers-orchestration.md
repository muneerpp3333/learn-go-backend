# Containers and Orchestration

## Problem

Your Go service runs on one developer's laptop and crashes in production. Container images are 900MB because you forgot to use multi-stage builds. A service restart takes 5 minutes because it doesn't handle shutdown signals. Running 50 copies manually is impossible; you need automation. When one replica crashes, traffic still tries to reach it. You need 100 replicas at 3am when traffic spikes, but can't scale manually. A new deployment breaks prod; rolling back takes 30 minutes. Your logs are scattered across 50 containers. Debugging production is a nightmare.

Containers + Kubernetes solve this. This lesson covers Docker best practices, Kubernetes patterns, and the mental model for managing thousands of containers.

## Theory

### Docker: Images, Layers, Multi-Stage Builds

A Dockerfile is a recipe. Each instruction creates a **layer** (cached filesystem delta):

```dockerfile
FROM ubuntu:22.04                    # Layer 1: base image (77MB)
RUN apt-get update                    # Layer 2: package list
RUN apt-get install -y go-lang        # Layer 3: Go installation
COPY . /app                           # Layer 4: your code
RUN cd /app && go build -o app        # Layer 5: compiled binary
```

Layers are cached. If you rerun without code changes, layers 1-3 reuse cache. Layer 4 (code copy) invokes layer 5 rebuild. This is why order matters: put things that change least first.

**Problem**: Go binary compiled from Ubuntu image is large (dependencies, system libraries included). Solution: **multi-stage builds**.

```dockerfile
# Stage 1: build
FROM golang:1.21-alpine AS builder
WORKDIR /app
COPY go.mod go.sum .
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o app .
# Result: app binary (10MB)

# Stage 2: runtime
FROM alpine:3.18
RUN apk add --no-cache ca-certificates
COPY --from=builder /app/app /app
ENTRYPOINT ["/app"]
```

First stage builds binary, discards builder image (Go, gcc, etc). Second stage copies only binary + minimal runtime. Final image: 20MB (not 900MB).

Better: use distroless:

```dockerfile
FROM golang:1.21-alpine AS builder
...as above...

FROM gcr.io/distroless/base-debian11:nonroot
COPY --from=builder /app/app /app
ENTRYPOINT ["/app"]
```

Distroless has no shell, no package manager, just libc and minimal tools. Even smaller. Security bonus: fewer CVEs (no packages to patch).

**Layer caching**: reorder Dockerfile to maximize cache hits:

```dockerfile
FROM golang:1.21-alpine
WORKDIR /app

# Go modules change rarely
COPY go.mod go.sum .
RUN go mod download

# Code changes often
COPY . .
RUN CGO_ENABLED=0 go build -o app .
```

If you only change code, layers 1-3 cache, rebuild is fast (5s).

**CGO_ENABLED=0**: static compilation (no glibc dependency). Binary runs on any Linux distro, Alpine included.

**-ldflags="-s -w"**: strip symbols and debug info (10MB -> 8MB).

### Container Networking and DNS

**Bridge network**: containers on same bridge can reach each other by name (Docker daemon runs DNS). Container IP: 172.17.0.2, etc. Not accessible from outside unless port mapped (-p 8080:8080).

**Host network**: container shares host's network namespace (same IP, same ports). No network isolation but fast.

**Overlay network** (Kubernetes): multiple hosts' containers on same network (SDN).

**DNS**: Kubernetes provides cluster DNS (CoreDNS). Service IP resolves to all backend pods. Example:

```
Service: booking-api -> ClusterIP 10.0.1.42
Pod 1: booking-api-xyz (10.0.2.1)
Pod 2: booking-api-abc (10.0.2.2)

Request to booking-api:8080 -> CoreDNS resolves -> round-robin to 10.0.2.1 or 10.0.2.2
```

### Kubernetes Core Concepts

**Pod**: smallest unit. One or more containers (usually one). Containers in pod share network namespace (same IP, can talk via localhost).

**Deployment**: declarative specification. "I want 5 replicas of booking-api running golang:1.21 image." Kubernetes ensures 5 are running; if one dies, replace it.

**Service**: stable IP/DNS for accessing pods. Selects pods by labels (`app: booking-api`). Distributes traffic via load balancer (built-in round-robin).

**Ingress**: routes HTTP traffic to services. Allows `/bookings` -> booking-service, `/payments` -> payment-service.

**ConfigMap**: key-value config, mounted as files or env vars.

**Secret**: encrypted config (passwords, tokens).

Manifest example:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: booking-api
spec:
  replicas: 5
  selector:
    matchLabels:
      app: booking-api
  template:
    metadata:
      labels:
        app: booking-api
    spec:
      containers:
      - name: api
        image: gcr.io/myapp/booking-api:v1.2.3
        ports:
        - containerPort: 8080
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secret
              key: url
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
---
apiVersion: v1
kind: Service
metadata:
  name: booking-api
spec:
  selector:
    app: booking-api
  ports:
  - port: 8080
    targetPort: 8080
  type: ClusterIP
```

**Replicas**: 5 pods, each can receive requests. If one dies, Deployment creates another.

**Probes**:
- **Liveness**: "is the container alive?" If probe fails, restart. Use for deadlock detection.
- **Readiness**: "is the container ready for traffic?" If not ready, remove from load balancer (but don't restart). Use during startup initialization.
- **Startup**: "has the container finished starting?" Similar to liveness but initial grace period.

**Resources**:
- **Requests**: "I need this much." Scheduler reserves it. If you request 100m CPU but pod uses 50m, wasted. If you request 50m but need 100m, pod is throttled.
- **Limits**: "Don't use more than this." If memory limit exceeded, pod is OOMKilled (restarted).

### Graceful Shutdown

When Kubernetes terminates a pod (deployment update, scale down), it sends **SIGTERM** signal. App has 30 seconds to shutdown gracefully.

```go
import "os/signal"

sigChan := make(chan os.Signal, 1)
signal.Notify(sigChan, syscall.SIGTERM, syscall.SIGINT)

go func() {
  <-sigChan
  log.Println("received shutdown signal")

  // Stop accepting new requests
  server.Close()

  // Wait for in-flight requests (with timeout)
  ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
  defer cancel()
  server.Shutdown(ctx)
}()

server.ListenAndServe() // Blocks; shutdown stops it
```

Without graceful shutdown, in-flight requests are killed mid-request, causing errors. With graceful shutdown, Kubernetes waits for requests to finish.

### Health Probes

Liveness probe (checks if container is stuck):

```go
mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
  // Minimal check: can we reach database?
  ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
  defer cancel()

  if err := db.Ping(ctx); err != nil {
    http.Error(w, "db unreachable", http.StatusServiceUnavailable)
    return
  }

  w.WriteHeader(http.StatusOK)
})
```

Readiness probe (checks if container is ready for traffic):

```go
mux.HandleFunc("GET /ready", func(w http.ResponseWriter, r *http.Request) {
  // Check if initialization is complete
  if !initializationDone {
    http.Error(w, "not ready", http.StatusServiceUnavailable)
    return
  }

  // Check dependencies
  ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
  defer cancel()
  if err := db.Ping(ctx); err != nil {
    http.Error(w, "not ready", http.StatusServiceUnavailable)
    return
  }

  w.WriteHeader(http.StatusOK)
})
```

On startup, readiness returns 503 until initialization finishes. Kubernetes waits before routing traffic.

### Deployment Strategies

**Rolling update** (default):
```
V1: 5 replicas
Update image to V2
1. Start 1 V2 pod
2. Once V2 is ready, kill 1 V1 pod
3. Repeat until all V2
Result: zero downtime, slower rollout (5 min for 5 pods)
```

**Blue-green**:
```
Blue (V1): 5 replicas running
Green (V2): 0 replicas
Deploy V2: start 5 green replicas, wait for ready
Switch: ingress routes to green
Rollback: switch back to blue instantly
```

Better for big changes, instant rollback. More resource usage (need 2x capacity).

**Canary**:
```
V1: 10 replicas
Deploy V2: start 1 replica (10% traffic)
Monitor: errors, latency, etc
If OK: scale to 5 replicas (50% traffic)
If OK: scale to 10 replicas (100% traffic)
If NOT OK: rollback, kill V2 replicas
```

Catches bugs early, gradual rollout. Need traffic splitting (Istio, Flagger).

### Horizontal Pod Autoscaler (HPA)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: booking-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: booking-api
  minReplicas: 3
  maxReplicas: 100
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

HPA scales replicas up/down based on CPU/memory. At 70% CPU, scale up. At < 30% CPU, scale down.

Custom metrics: scale by request latency, queue depth, etc (requires metrics exporter).

### Service Discovery

In Kubernetes, service DNS is `<service-name>.<namespace>.svc.cluster.local`.

Booking pod wants to call payment service:
```
payment-api:8080 (uses CoreDNS)
-> resolves to ClusterIP 10.0.1.50
-> load balances to payment-api-xyz pod at 10.0.2.5, port 8080
-> request succeeds
```

## Production Code

### Production-Grade Dockerfile for Go Microservice

```dockerfile
# Build stage
FROM golang:1.21-alpine AS builder

# Install build dependencies
RUN apk add --no-cache git ca-certificates tzdata

WORKDIR /app

# Copy module files for better layer caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . .

# Build with version injection
ARG VERSION=dev
ARG BUILD_DATE
ARG COMMIT_SHA

RUN CGO_ENABLED=0 GOOS=linux go build \
  -ldflags="-w -s \
    -X main.Version=${VERSION} \
    -X main.BuildDate=${BUILD_DATE} \
    -X main.CommitSHA=${COMMIT_SHA}" \
  -a -installsuffix cgo \
  -o app .

# Runtime stage
FROM gcr.io/distroless/base-debian11:nonroot

# Copy SSL certificates for HTTPS
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

# Copy timezone data
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo

# Copy binary
COPY --from=builder /app/app /app

# Non-root user (security)
USER nonroot:nonroot

EXPOSE 8080

ENTRYPOINT ["/app"]
```

Build and push:
```bash
docker build \
  --build-arg VERSION=v1.2.3 \
  --build-arg BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ') \
  --build-arg COMMIT_SHA=$(git rev-parse --short HEAD) \
  -t gcr.io/myapp/booking-api:v1.2.3 \
  -t gcr.io/myapp/booking-api:latest \
  .

docker push gcr.io/myapp/booking-api:v1.2.3
```

### .dockerignore to reduce build context

```
.git
.gitignore
node_modules
.env
.env.*
*.log
.DS_Store
bin/
dist/
vendor/
.idea/
*.swp
*.swo
.vscode/
```

### Complete Kubernetes Manifests

```yaml
---
# Namespace
apiVersion: v1
kind: Namespace
metadata:
  name: booking-system

---
# ConfigMap for app config
apiVersion: v1
kind: ConfigMap
metadata:
  name: booking-config
  namespace: booking-system
data:
  LOG_LEVEL: "info"
  ENVIRONMENT: "production"
  PORT: "8080"

---
# Secret for sensitive config
apiVersion: v1
kind: Secret
metadata:
  name: booking-secrets
  namespace: booking-system
type: Opaque
stringData:
  DATABASE_URL: "postgres://user:pass@postgres.booking-system.svc.cluster.local:5432/bookings"
  JWT_SECRET: "your-secret-key-min-32-chars-long"
  PAYMENT_API_KEY: "sk_live_abc123"

---
# Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: booking-api
  namespace: booking-system
  labels:
    app: booking-api
    version: v1
spec:
  replicas: 5
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1        # Max 1 extra pod during update
      maxUnavailable: 0   # Zero downtime
  selector:
    matchLabels:
      app: booking-api
  template:
    metadata:
      labels:
        app: booking-api
        version: v1
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8080"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: booking-api
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000

      containers:
      - name: api
        image: gcr.io/myapp/booking-api:v1.2.3
        imagePullPolicy: IfNotPresent
        ports:
        - name: http
          containerPort: 8080
          protocol: TCP

        env:
        - name: POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: POD_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        - name: LOG_LEVEL
          valueFrom:
            configMapKeyRef:
              name: booking-config
              key: LOG_LEVEL
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: booking-secrets
              key: DATABASE_URL

        # Liveness: is container alive?
        livenessProbe:
          httpGet:
            path: /health
            port: http
            scheme: HTTP
          initialDelaySeconds: 15
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3

        # Readiness: is container ready for traffic?
        readinessProbe:
          httpGet:
            path: /ready
            port: http
            scheme: HTTP
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 2

        # Startup: has container finished starting?
        startupProbe:
          httpGet:
            path: /health
            port: http
          initialDelaySeconds: 0
          periodSeconds: 2
          timeoutSeconds: 3
          failureThreshold: 30 # 60s total startup time

        # Resource requests/limits
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"

        # Security context
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL

        # Volume mounts
        volumeMounts:
        - name: tmp
          mountPath: /tmp

      # Volumes
      volumes:
      - name: tmp
        emptyDir: {}

      # Termination grace period for graceful shutdown
      terminationGracePeriodSeconds: 30

      # Affinity: spread pods across nodes
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app
                  operator: In
                  values:
                  - booking-api
              topologyKey: kubernetes.io/hostname

---
# Service
apiVersion: v1
kind: Service
metadata:
  name: booking-api
  namespace: booking-system
  labels:
    app: booking-api
spec:
  type: ClusterIP
  selector:
    app: booking-api
  ports:
  - name: http
    port: 8080
    targetPort: http
    protocol: TCP
  sessionAffinity: None

---
# HorizontalPodAutoscaler
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: booking-api-hpa
  namespace: booking-system
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: booking-api
  minReplicas: 3
  maxReplicas: 100
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15

---
# Ingress
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: booking-api-ingress
  namespace: booking-system
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/rate-limit: "100"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - api.booking.example.com
    secretName: booking-api-cert
  rules:
  - host: api.booking.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: booking-api
            port:
              number: 8080

---
# ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: booking-api
  namespace: booking-system

---
# Role for RBAC
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: booking-api
  namespace: booking-system
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get"]

---
# RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: booking-api
  namespace: booking-system
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: booking-api
subjects:
- kind: ServiceAccount
  name: booking-api
  namespace: booking-system
```

Deploy:
```bash
kubectl apply -f manifests/

# Check deployment
kubectl get deployments -n booking-system
kubectl get pods -n booking-system
kubectl logs -n booking-system deployment/booking-api

# Rolling update
kubectl set image deployment/booking-api api=gcr.io/myapp/booking-api:v1.2.4 -n booking-system

# Check rollout status
kubectl rollout status deployment/booking-api -n booking-system

# Rollback if needed
kubectl rollout undo deployment/booking-api -n booking-system
```

### Go Application with Graceful Shutdown

```go
package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

var (
	Version    = "dev"
	BuildDate  = "unknown"
	CommitSHA  = "unknown"
)

type Server struct {
	httpServer *http.Server
	db *sql.DB
}

func (s *Server) RegisterHandlers(mux *http.ServeMux) {
	// Health checks
	mux.HandleFunc("GET /health", s.health)
	mux.HandleFunc("GET /ready", s.ready)

	// API endpoints
	mux.HandleFunc("POST /v1/bookings", s.postBooking)
	mux.HandleFunc("GET /v1/bookings", s.getBookings)

	// Metrics
	mux.Handle("/metrics", promhttp.Handler())
}

func (s *Server) health(w http.ResponseWriter, r *http.Request) {
	// Minimal check: is container alive?
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	if err := s.db.PingContext(ctx); err != nil {
		http.Error(w, "db unreachable", http.StatusServiceUnavailable)
		return
	}

	w.WriteHeader(http.StatusOK)
	fmt.Fprintf(w, "OK")
}

func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	// Is container ready for traffic?
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()

	if err := s.db.PingContext(ctx); err != nil {
		http.Error(w, "not ready", http.StatusServiceUnavailable)
		return
	}

	w.WriteHeader(http.StatusOK)
	fmt.Fprintf(w, "OK")
}

func (s *Server) postBooking(w http.ResponseWriter, r *http.Request) {
	// Implementation...
}

func (s *Server) getBookings(w http.ResponseWriter, r *http.Request) {
	// Implementation...
}

func (s *Server) Start(ctx context.Context, port int) error {
	mux := http.NewServeMux()
	s.RegisterHandlers(mux)

	s.httpServer = &http.Server{
		Addr:           fmt.Sprintf(":%d", port),
		Handler:        mux,
		ReadTimeout:    10 * time.Second,
		WriteTimeout:   10 * time.Second,
		MaxHeaderBytes: 1 << 20,
	}

	// Start server in goroutine
	go func() {
		log.Printf("starting server on %s", s.httpServer.Addr)
		if err := s.httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Printf("server error: %v", err)
		}
	}()

	return nil
}

func (s *Server) Stop(ctx context.Context) error {
	log.Println("stopping server")
	return s.httpServer.Shutdown(ctx)
}

func main() {
	log.Printf("booking-api version=%s buildDate=%s commitSHA=%s", Version, BuildDate, CommitSHA)

	// Database
	db, err := sql.Open("postgres", os.Getenv("DATABASE_URL"))
	if err != nil {
		log.Fatalf("database connection failed: %v", err)
	}
	defer db.Close()

	// Server
	server := &Server{db: db}

	// Start server
	ctx := context.Background()
	if err := server.Start(ctx, 8080); err != nil {
		log.Fatalf("server start failed: %v", err)
	}

	// Graceful shutdown on SIGTERM/SIGINT
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGTERM, syscall.SIGINT)

	sig := <-sigChan
	log.Printf("received signal: %v", sig)

	// Give in-flight requests 30 seconds to complete
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	if err := server.Stop(shutdownCtx); err != nil {
		log.Printf("shutdown error: %v", err)
	}

	log.Println("graceful shutdown complete")
}
```

## Tradeoffs and What Breaks

### OOMKilled

Pod uses more memory than limit. Kubernetes kills pod. Solution: set realistic limits (measure with `kubectl top`), or remove limits for non-prod.

### CrashLoop

Pod crashes on startup, Kubernetes restarts it, crashes again. Check logs: `kubectl logs <pod>`. Often: missing env var, database unreachable.

### Image Pull Errors

Image registry unreachable or image doesn't exist. Solution: ensure image is pushed, registry is accessible.

### Resource Contention

Pods on same node compete for CPU/memory. If one pod hogs, others starve. Solution: request resources accurately, use PodDisruptionBudgets.

### DNS Resolution Delays

Startup: pod waits for service DNS. Solution: implement retry loop with exponential backoff in app.

## Interview Corner

**Q1: Pod crashes with OOMKilled. How do you diagnose and fix?**

A: Check events: `kubectl describe pod <pod>` shows OOMKilled. Check memory usage: `kubectl top pod`. If actual > limit, either:
1. Increase limit: `resources.limits.memory = 1Gi`
2. Find memory leak in code (profile with pprof)

For development, remove limits (set only requests).

**Q2: Deployment has 5 replicas; one pod is stuck. What happens?**

A: If liveness probe fails 3 times, Kubernetes restarts pod. If readiness probe fails, pod is removed from load balancer (not receiving traffic). If both fail repeatedly, pod is in CrashLoop.

Fix: check logs, fix the issue, redeploy.

**Q3: You need to deploy with zero downtime. What's the strategy?**

A: Use rolling update with maxSurge=1, maxUnavailable=0. During update:
1. Start 1 new pod (6 total)
2. Wait for ready
3. Kill 1 old pod (5 total)
4. Repeat until all new

Gradual, no downtime. Slower (5 min for 5 pods) but safe.

**Q4: Graceful shutdown: how do you ensure in-flight requests complete?**

A: In code:
1. Catch SIGTERM
2. Stop accepting new requests (close listener or reject in middleware)
3. Wait for in-flight requests with timeout (10-30s)
4. Exit

In Kubernetes: set `terminationGracePeriodSeconds: 30`. Kubelet sends SIGTERM, waits 30s, force-kills if not exited.

**Q5: How do you limit resource usage across all pods in a namespace?**

A: Use ResourceQuota:
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: booking-quota
  namespace: booking-system
spec:
  hard:
    requests.memory: "100Gi"
    requests.cpu: "50"
    limits.memory: "200Gi"
    limits.cpu: "100"
    pods: "1000"  # Max 1000 pods in namespace
  scopeSelector:
    matchExpressions:
    - operator: In
      scopeName: PriorityClass
      values: ["default"]
```

All pods in namespace share this quota. If quota exceeded, new pod creation fails.

Also use LimitRange to set defaults and bounds:
```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: booking-limits
  namespace: booking-system
spec:
  limits:
  - max:
      memory: "512Mi"
      cpu: "500m"
    min:
      memory: "128Mi"
      cpu: "50m"
    default:
      memory: "256Mi"
      cpu: "100m"
    type: Container
```

Default memory 256Mi if not specified. Reject containers requesting > 512Mi.

**Q6: Deployment fails with ImagePullBackOff. How do you debug?**

A: Pod is trying to pull image but fails. Check:
1. Image exists in registry: `docker push gcr.io/myapp/booking-api:v1.2.3`
2. Registry credentials: image is private, need docker credentials
3. Network: pod can reach registry (DNS, firewall)

Debug:
```bash
kubectl describe pod <pod-name>
# Shows: image pull failure, event log with error
# E.g., "Failed to pull image 'gcr.io/myapp/booking-api:v1.2.3': rpc error: code = Unknown desc = Error response from daemon: manifest not found"

# If auth issue:
kubectl create secret docker-registry gcr-secret \
  --docker-server=gcr.io \
  --docker-username=_json_key \
  --docker-password="$(cat ~/key.json)"

# Update deployment to use secret:
spec:
  template:
    spec:
      imagePullSecrets:
      - name: gcr-secret
```

**Q7: Pod is stuck in CrashLoopBackOff. Startup probe is failing. What's wrong?**

A: Pod starts, fails healthcheck, gets restarted, fails again, loop. Check logs:
```bash
kubectl logs <pod-name>
# See error (e.g., "panic: database connection failed")

kubectl logs <pod-name> --previous
# See previous pod's logs (helpful if current pod is very new)
```

Common causes:
- Missing env variable: `DATABASE_URL` not set
- Dependency unreachable: trying to connect to database before it's up
- Port already in use: if container reuses host ports
- File permissions: config file not readable

Fix: add init container or init script to wait for dependencies:
```yaml
spec:
  initContainers:
  - name: wait-for-db
    image: busybox:1.28
    command: ['sh', '-c', 'until nc -z postgres.booking-system.svc:5432; do echo waiting for db; sleep 2; done']
  containers:
  - name: api
    ...
```

This waits for database to be reachable before starting main container.

## Exercise

Build and deploy a complete WhatsApp-like messaging service:

1. **Dockerfile**: multi-stage, distroless, < 50MB
2. **Go app**: graceful shutdown, health/ready probes
3. **Kubernetes manifests**: deployment, service, HPA, ingress
4. **Probes**: liveness (db ping), readiness (init complete), startup (wait for migrations)
5. **Security**: non-root, read-only filesystem, resource limits
6. **Deployment strategy**: rolling update with zero downtime
7. **Monitoring**: Prometheus metrics (/metrics), structured logging

Bonus: implement blue-green deployment with traffic switching. Deploy v2 alongside v1, switch ingress, rollback to v1 if issues.

---

