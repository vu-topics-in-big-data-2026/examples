# Demo: IoT Temperature Monitoring

A hands-on tutorial that builds a real-time IoT anomaly detection pipeline using Docker, Docker Compose, and Kubernetes. You'll stream sensor readings through a message broker and flag temperature anomalies — then see how Kubernetes keeps the system running even when things break.

## Table of Contents

- [Background: Docker vs Kubernetes](#background-docker-vs-kubernetes)
- [The Pipeline](#the-pipeline)
- [Prerequisites](#prerequisites)
- [Files](#files)
- [Part A: Docker Compose (local dev)](#part-a-docker-compose-local)
- [Part B: Kubernetes (minikube)](#part-b-kubernetes-minikube)
  - [Why so many kubectl apply commands?](#why-so-many-kubectl-apply-commands)
  - [Step 1: Start minikube](#step-1-start-minikube)
  - [Step 2: Build and load images](#step-2-build-and-load-images)
  - [Step 3: Deploy the pipeline](#step-3-deploy-the-pipeline)
  - [Step 4: Watch the logs](#step-4-watch-the-logs)
  - [Step 5: Scaling and load balancing](#step-5-scaling-and-load-balancing)
  - [Step 6: Self-healing](#step-6-self-healing)
  - [Step 7: Clean up](#step-7-clean-up)
- [Troubleshooting](#troubleshooting)

---

## Background: Docker vs Kubernetes

Before diving into the demo, it helps to understand **why we use two different tools** and what problem each one solves.

### Docker and Docker Compose

**Docker** packages your application and all its dependencies into a **container** — a lightweight, portable unit that runs the same way on any machine. No more "works on my laptop" problems.

**Docker Compose** goes one step further: it lets you define **multiple containers** in a single `compose.yaml` file and start them all together with one command. Compose handles:
- **Networking**: containers can find each other by name (e.g., the producer connects to `redpanda:9092`)
- **Startup order**: services wait for dependencies to be healthy before starting
- **Convenience**: `docker compose up -d` starts everything; `docker compose down` tears it all down

Compose is great for **local development and testing**. But it has limits — it only runs on a single machine, and if a container crashes, it stays dead. There's no automatic recovery, no scaling, no rolling updates.

### Kubernetes (K8s)

Kubernetes is a **container orchestrator** — it manages containers across one or many machines and keeps your system running the way you declared it should be. You write YAML manifests that say "I want 3 copies of my analyzer running" and Kubernetes continuously works to make reality match that declaration.

What Kubernetes gives you that Compose doesn't:
- **Self-healing**: if a container crashes, K8s automatically replaces it within seconds
- **Scaling**: change `replicas: 3` and K8s spins up new instances, with load balanced across them automatically
- **Rolling updates**: deploy a new version with zero downtime
- **Resource management**: K8s decides which machine to place each container on based on available CPU/memory
- **Production-grade**: this is what Netflix, Uber, Spotify, and most tech companies use to run their systems

### Why learn both?

They solve different problems at different stages of the software lifecycle:

| | Docker Compose | Kubernetes |
|---|---|---|
| **Question it answers** | "Does my code work?" | "How do I run this reliably at scale?" |
| **Where it runs** | Your laptop (single machine) | Any cluster (local or cloud) |
| **What happens on crash** | Container stays dead | Auto-replaced in seconds |
| **Scaling** | Not supported | One command: `kubectl scale` |
| **Config files** | One `compose.yaml` | Separate manifests per resource |
| **Best for** | Local dev and testing | Staging and production |

In this demo, we run the **exact same pipeline** in both environments so you can see the progression: same code, same containers, but very different operational capabilities.

### minikube

minikube is a tool that runs a **single-node Kubernetes cluster on your laptop** inside a container or VM. It gives you a real K8s environment to experiment with — same APIs, same commands — without needing a cloud account or a fleet of servers. When you're done, `minikube stop` shuts everything down cleanly.

---

## The Pipeline

```
┌──────────────┐       ┌──────────┐       ┌──────────────┐
│   Producer   │──────>│ Redpanda │──────>│   Analyzer   │
│ reads CSV,   │       │ (Kafka   │       │ flags temps   │
│ sends 1/sec  │       │  broker) │       │ > 40C or < 5C │
└──────────────┘       └──────────┘       └──────────────┘
```

Three components:
1. **Redpanda** — A Kafka-compatible message broker (lightweight, no JVM). It receives messages from the producer and delivers them to the analyzer.
2. **Producer** — A Python script that reads `sensors.csv` and publishes one sensor reading per second to the `iot-sensors` topic. Loops continuously.
3. **Analyzer** — A Python script that consumes readings from the topic and flags temperature anomalies. In Kubernetes, you can scale this to multiple replicas for parallel processing.

All communication goes through the broker via the **Kafka protocol**. The producer and analyzer never talk to each other directly — this decoupling is what makes the system scalable.

## What this demonstrates

- Streaming real-world IoT data through a message broker
- Volume mounts for data files in Docker Compose
- ConfigMaps for data and configuration in Kubernetes
- **Scaling consumers** with partition-based load balancing
- **Self-healing** — Kubernetes automatically replaces crashed pods

## Prerequisites

### 1. Install Docker Desktop

Download from https://www.docker.com/products/docker-desktop/ and follow the installer. Docker Desktop includes **Docker Compose V2**.

Verify:

```bash
docker --version
docker compose version
```

### 2. Install minikube and kubectl (for Kubernetes steps only)

```bash
# macOS (Homebrew)
brew install minikube kubectl

# Verify
minikube version
kubectl version --client
```

Skip these if you only want the Docker Compose portion.

## Files

```
example-kubernetes/
├── data/
│   └── sensors.csv         # 200 rows, 5 sensors, ~10% anomalies
├── producer/
│   ├── Dockerfile
│   ├── requirements.txt    # kafka-python-ng
│   └── producer.py         # reads CSV, streams to Kafka
├── analyzer/
│   ├── Dockerfile
│   ├── requirements.txt    # kafka-python-ng
│   └── analyzer.py         # flags temp anomalies
├── compose.yaml             # runs everything locally (Docker)
├── k8s.yaml                 # single-file K8s manifest (all resources)
└── k8s/                     # same manifests, one file per resource
```

### About the data

`data/sensors.csv` contains 200 readings from 5 sensors:

| sensor_id | location | normal range | anomalies |
|-----------|----------|-------------|-----------|
| sensor-01 | rooftop | 15-30C | occasional spikes > 45C |
| sensor-02 | warehouse | 15-30C | occasional spikes > 45C |
| sensor-03 | server-room | 15-30C | occasional drops < 0C |
| sensor-04 | parking-lot | 15-30C | occasional drops < 0C |
| sensor-05 | cold-storage | 15-30C | mixed anomalies |

---

## Part A: Docker Compose (local)

**Goal:** Run the full pipeline on your laptop with a single command. Docker Compose handles networking between containers so the producer and analyzer can reach the broker by hostname — something a standalone `docker run` can't do. This is the fastest way to see the pipeline working end to end before moving to Kubernetes.

### Step 1: Build the images

Each service has its own `Dockerfile`. This step compiles them into container images that Docker can run. Think of an image as a snapshot of the app and all its dependencies frozen together.

```bash
cd example-kubernetes
docker build -t iot-producer:v1 ./producer
docker build -t iot-analyzer:v1 ./analyzer
```

`-t iot-producer:v1` tags the image with a name and version so we can reference it later. The Redpanda image is pulled automatically from Docker Hub — we don't need to build it.

### Step 2: Start the pipeline

```bash
docker compose up -d
```

`docker compose up` reads `compose.yaml` and starts all three services in the right order. The `-d` flag runs them in the background (detached) so you get your terminal back.

**What happens behind the scenes:**
1. Compose creates an isolated network for these containers
2. Redpanda starts first and exposes its health check endpoint
3. The producer and analyzer **wait** until Redpanda reports healthy (`depends_on` with `condition: service_healthy`)
4. Once healthy, the producer begins reading `sensors.csv` and publishing one reading per second to the `iot-sensors` topic
5. The analyzer subscribes to the same topic and prints each reading, flagging anomalies

This is the key Docker Compose concept: it **orchestrates startup order and networking** so your services can find each other by name (e.g., the producer connects to `redpanda:9092`).

### Step 3: Watch the output

```bash
docker compose logs -f analyzer
```

`logs -f` follows the analyzer's stdout in real time — the same output the Python `print()` statements produce. This is how you'd monitor a real streaming app: by tailing container logs.

Expected output:

```
analyzer-1  | OK:           sensor-01 | rooftop      | 19.17C | humidity 73.47%
analyzer-1  | ANOMALY HIGH: sensor-02 | warehouse    | 54.47C (> 40.0C) | humidity 58.87%
analyzer-1  | OK:           sensor-03 | server-room  | 18.23C | humidity 68.17%
analyzer-1  | ANOMALY LOW:  sensor-04 | parking-lot  | -11.74C (< 5.0C) | humidity 58.06%
analyzer-1  | OK:           sensor-05 | cold-storage | 18.97C | humidity 32.17%
```

Press `Ctrl+C` to stop following (containers keep running).

### Step 4: Stop and clean up

```bash
docker compose down
```

This stops all containers, removes them, and tears down the network. Everything is cleaned up — no leftover processes or state.

---

## Part B: Kubernetes (minikube)

**Goal:** Deploy the exact same pipeline to a Kubernetes cluster instead of Docker Compose. This shows how a real production deployment works: instead of one `compose.yaml`, you use separate manifest files that declare the desired state, and Kubernetes continuously works to make reality match that state. This is what gives you self-healing, scaling, and rolling updates — things Docker Compose can't do.

minikube runs a single-node Kubernetes cluster inside a container on your laptop, so you can experiment without needing a cloud account.

### Why so many `kubectl apply` commands?

In Part A, we deployed everything with a single `docker compose up`. Here in Part B, you'll see us running **7 separate `kubectl apply` commands** — one per resource. You might wonder: why can't we just do it all at once?

The short answer is: **we can.** We provide both options in this demo.

**Option A — Separate applies** (what Step 3 uses):
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/redpanda-statefulset.yaml
# ... one per resource
```

**Option B — Single file** (`k8s.yaml` at the demo root):
```bash
kubectl apply -f k8s.yaml
```

Both create the exact same resources. The difference is control vs convenience:

| | Separate applies (`k8s/`) | Single file (`k8s.yaml`) |
|---|---|---|
| **Deploy** | Multiple commands | One command |
| **Startup order** | You control the sequence — apply Redpanda first, wait for it, then deploy the apps | Everything is applied at once — no guaranteed order |
| **Update one thing** | Edit and re-apply just that one file | Edit the big file, re-apply everything |
| **Readability** | Open the file you care about | Scroll through one long file |
| **Team workflow** | Different people own different files, cleaner git diffs | One file means more merge conflicts |
| **Best for** | Production, CI/CD, learning | Quick demos, small projects |

**Why we use separate applies in this tutorial:** it lets you see each piece being created one at a time and understand what it does. It also lets us insert a `kubectl wait` command between deploying Redpanda and deploying the producer/analyzer — ensuring the broker is ready before the apps try to connect.

With the single-file approach, all resources are applied at once, so the producer and analyzer pods may start before Redpanda is ready. This is fine because our Python code has **retry logic** (5 attempts, 5 seconds apart) — the apps will keep trying until the broker comes up. In production, this retry pattern is standard practice because you can never fully guarantee startup order across services.

If you prefer the single-file approach, replace all of Step 3's commands with:

```bash
kubectl apply -f k8s.yaml
kubectl -n streaming-iot create configmap sensor-data --from-file=data/sensors.csv
kubectl -n streaming-iot wait --for=condition=Ready pod/redpanda-0 --timeout=60s
```

### Step 1: Start minikube

```bash
minikube start
```

This boots a local Kubernetes cluster. It takes 30-60 seconds the first time (downloads a VM image). Subsequent starts are faster.

### Step 2: Build and load images

```bash
docker build -t iot-producer:v1 ./producer
docker build -t iot-analyzer:v1 ./analyzer
minikube image load iot-producer:v1
minikube image load iot-analyzer:v1
```

Kubernetes needs access to your container images, but minikube runs its own Docker daemon separate from your host. `minikube image load` copies your locally built images into minikube's daemon so it can use them. (In production you'd push to a container registry like Docker Hub or AWS ECR instead.)

### Step 3: Deploy the pipeline

Each `kubectl apply` command tells Kubernetes "make this resource exist." Kubernetes reads the YAML manifest and creates or updates the resource to match. We apply them in order because some resources depend on others existing first.

```bash
# Create a namespace — a logical grouping that keeps this demo's
# resources isolated from anything else in the cluster.
kubectl apply -f k8s/namespace.yaml

# Upload the sensor CSV as a ConfigMap. A ConfigMap is how Kubernetes
# passes configuration data (or small files) into pods. This is the
# K8s equivalent of the Docker Compose volume mount (./data:/data).
kubectl -n streaming-iot create configmap sensor-data --from-file=data/sensors.csv

# Create shared config — broker address, topic name, thresholds.
# Both the producer and analyzer pods read from this ConfigMap via
# environment variables (envFrom in the Deployment YAML).
kubectl apply -f k8s/configmap.yaml

# Deploy Redpanda as a StatefulSet. A StatefulSet (instead of a
# Deployment) gives the pod a stable hostname (redpanda-0) that
# other pods can reliably connect to. The headless Service makes
# this hostname resolvable inside the cluster.
kubectl apply -f k8s/redpanda-statefulset.yaml
kubectl apply -f k8s/redpanda-service.yaml

# Wait for Redpanda's readiness probe to pass before continuing.
# Without this, the producer/analyzer pods would start and fail
# because the broker isn't ready yet.
kubectl -n streaming-iot wait --for=condition=Ready pod/redpanda-0 --timeout=60s

# Deploy the producer and analyzer as Deployments. A Deployment tells
# Kubernetes "keep N replicas of this pod running at all times."
# If a pod crashes, the Deployment controller automatically creates
# a replacement — this is the self-healing behavior.
kubectl apply -f k8s/producer-deployment.yaml
kubectl apply -f k8s/analyzer-deployment.yaml
kubectl apply -f k8s/analyzer-service.yaml
```

### Step 4: Watch the logs

```bash
kubectl -n streaming-iot logs -f deployment/analyzer
```

This is the K8s equivalent of `docker compose logs -f`. The `-n streaming-iot` flag tells kubectl to look in the right namespace. You should see the same anomaly output as in Part A.

### Step 5: Scaling and load balancing

**Why this matters:** In Docker Compose, you run one analyzer and that's it. In Kubernetes, you can scale to multiple replicas with a single command. The Kafka consumer group protocol automatically distributes partitions across replicas — no code changes needed.

The producer creates the topic with **3 partitions**, keyed by `sensor_id`. Each partition gets a subset of sensors. When you scale to 3 analyzers, Kafka assigns one partition per analyzer — true parallel processing.

```bash
# Tell Kubernetes to run 3 analyzer pods instead of 1
kubectl -n streaming-iot scale deployment analyzer --replicas=3

# Watch the new pods come up in real time (-w = watch mode)
kubectl -n streaming-iot get pods -w
```

Wait until all 3 pods show `Running`. Then tail each pod's logs in separate terminals to see the work being distributed:

```bash
# Get pod names
kubectl -n streaming-iot get pods -l app=analyzer

# Tail each one (replace with actual pod names)
kubectl -n streaming-iot logs -f analyzer-xxxxx-aaaaa
kubectl -n streaming-iot logs -f analyzer-xxxxx-bbbbb
kubectl -n streaming-iot logs -f analyzer-xxxxx-ccccc
```

You'll see each pod processing a **different subset** of sensors. This is Kafka consumer group rebalancing in action — each partition is assigned to exactly one consumer in the group.

### Step 6: Self-healing

**Why this matters:** In production, containers crash — out-of-memory errors, bugs, hardware failures. Kubernetes detects this and automatically replaces dead pods. You don't need to SSH into a server and restart things manually. This is the core value of an orchestrator.

```bash
# Terminal 1: watch pods continuously
kubectl -n streaming-iot get pods -w

# Terminal 2: kill an analyzer pod (simulates a crash)
kubectl -n streaming-iot delete pod -l app=analyzer --wait=false
```

In Terminal 1 you'll see:
1. One pod goes `Terminating`
2. A new pod appears with status `ContainerCreating`
3. Within seconds it's `Running` again
4. The consumer group rebalances — no data is lost

The Deployment controller noticed the actual state (2 pods) didn't match the desired state (3 pods) and immediately created a replacement. This loop — "observe, diff, act" — is how Kubernetes maintains your system 24/7 without human intervention.

### Step 7: Clean up

```bash
kubectl delete namespace streaming-iot
minikube stop
```

Deleting the namespace removes all resources inside it (pods, services, configmaps) in one shot. `minikube stop` shuts down the local cluster but preserves its state — `minikube start` will bring it back quickly.

## Troubleshooting

- **Producer says "No such file: /data/sensors.csv":** In Compose, check that you're running from the `example-kubernetes/` directory (the volume mount is `./data:/data`). In K8s, make sure you created the `sensor-data` ConfigMap (Step 3).
- **Analyzer shows no output:** Wait 5-10 seconds for the producer to start streaming. Check producer logs: `docker compose logs producer` or `kubectl -n streaming-iot logs deployment/producer`.
- **Port 29092 in use:** Check if another service is using the port with `lsof -i :29092`. Stop the conflicting service or edit ports in compose.yaml.
- **minikube image load hangs:** Try building inside minikube instead: `eval $(minikube docker-env)` then re-run the `docker build` commands.
