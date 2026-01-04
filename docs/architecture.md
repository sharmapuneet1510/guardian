# GUARDIAN — Architecture

**Project:** GUARDIAN  
**Domain:** Caregiver & Building Safety Monitoring Platform  
**Primary Goal:** Multi-camera, AI-powered safety monitoring with incident workflow, escalation, and auditability — deployable on a local PC/home server.

---

## 1. Vision

GUARDIAN is a local-first monitoring platform that:
- Runs multiple cameras simultaneously (USB / RTSP / IP)
- Detects people, known/unknown identities, activities, objects, and risk signals
- Creates incidents (not noisy raw alerts)
- Supports escalation (timers + sound + routing) and full accountability (audit trail)
- Provides admin controls for cameras, users, permissions, storage, and rules
- Preserves privacy with configurable retention, recording modes, and optional blurring

---

## 2. Core Principles

1. **Incident-driven, not alert-driven**
   - AI outputs become structured events → incidents → workflows.
2. **Per-camera isolation**
   - Each camera runs in its own worker (crash containment, restartability).
3. **Config-driven behavior**
   - Cameras/users/rules live in config files, not hardcoded.
4. **Auditability by default**
   - Every sensitive action (add user/camera, acknowledge/ignore/escalate) is logged.
5. **Local-first deployment**
   - Designed to run on a small PC (CPU-first, optional GPU acceleration later).
6. **Modularity**
   - UI, camera ingestion, vision pipeline, incidents, audit, storage are separate modules.

---

## 3. High-Level Architecture

### 3.1 Logical Layers

- **UI Layer**
  - Dashboard, Admin Console, Incident Panel, Search, Reports
- **Application Layer**
  - Camera Manager, Identity Resolver, Incident Manager, Escalation Engine, Notifier, Audit Logger
- **Vision Layer**
  - Face detection/recognition, object detection, activity detection, emotion detection, tracking
- **Ingestion Layer**
  - Camera workers (USB/RTSP/IP), frame sampling, health status
- **Storage Layer**
  - Events, incidents, snapshots, clips, audit logs, configs

### 3.2 Data Flow (Simplified)

1. Camera Worker reads frames
2. Vision Pipeline produces detections (faces/objects/activity/emotion)
3. App Layer converts detections → events → incidents
4. Escalation Engine triggers notifications (UI + sound + integrations)
5. UI displays live view + incidents + people + status
6. Audit Logger records user/system actions
7. Storage persists the full timeline

---

## 4. Modules & Responsibilities

### 4.1 UI (`src/ui/`)
- Multi-camera grid view
- Focus view (camera/person)
- People table (building-wide)
- Incident queue + incident detail drawer (timeline, evidence, actions)
- Admin panels (cameras, users, rules, storage, roles)
- Login/session awareness + role-based UI

### 4.2 Camera (`src/camera/`)
- **Camera Registry:** persist camera configs (USB index / RTSP URL / labels)
- **Camera Manager:** starts/stops workers; maintains status/health metrics
- **Camera Worker:** reads frames, throttles FPS, emits frames/events, recovers on transient failure

### 4.3 Vision (`src/vision/`)
- **Face**
  - Detect faces and produce embeddings
  - Recognize known identities; assign temporary unknown IDs
- **Objects**
  - YOLO / YOLO-World detection (weapons, common objects, wearables)
- **Activity**
  - Pose/activity detection (standing, walking, running, falling, inactivity)
- **Emotion**
  - Background inference + smoothing
- **Tracking**
  - Maintain stable track IDs per camera; help identity continuity

### 4.4 Incidents (`src/incidents/`)
- **Incident Manager**
  - Create incidents from events; update lifecycle state
- **Escalation Engine**
  - Escalation matrix, timers, auto-escalation if not acknowledged
- **Notifier**
  - UI banner updates, sound alerts, and optional outbound notifications (Slack/email/webhook)

### 4.5 Identity (`src/identity/`)
- **Identity Resolver**
  - Link unknown → known when user is registered
  - Retroactive relabeling of history (without corrupting audit)
- **Watchlist**
  - High-priority monitoring for selected people

### 4.6 Audit (`src/audit/`)
- Append-only audit events:
  - who logged in/out
  - who added/changed camera/user
  - who acknowledged/ignored/escalated/resolved incidents
  - who changed settings

### 4.7 Storage (`src/storage/` and `storage/`)
- Events: JSONL
- Incidents: JSON
- Audit: JSONL
- Snapshots: JPG
- Clips (optional): MP4
- Config: JSON/YAML
- Retention jobs to clean old data

---

## 5. Suggested Repo Layout
```
project-root/
├── src/
│   └── main.py
├── ui/
│   ├── components/
│   │   ├── video_tile.py
│   │   ├── people_table.py
│   │   └── alert_banner.py
│   ├── dashboard.py
│   ├── admin_panel.py
│   ├── incident_panel.py
│   └── login.py
├── camera/
│   ├── camera_worker.py
│   ├── camera_manager.py
│   └── camera_registry.py
├── vision/
│   ├── face/
│   │   ├── detector.py
│   │   ├── recognizer.py
│   │   └── face_store.py
│   ├── objects/
│   │   └── yolo_detector.py
│   ├── activity/
│   │   └── activity_detector.py
│   ├── emotion/
│   │   └── emotion_detector.py
│   └── tracking/
│       └── person_tracker.py
├── incidents/
│   ├── incident_manager.py
│   ├── escalation_engine.py
│   └── notifier.py
├── identity/
│   ├── identity_resolver.py
│   └── watchlist.py
├── audit/
│   └── audit_logger.py
├── config/
│   ├── cameras.json
│   ├── users.json
│   ├── escalation.json
│   └── system.json
├── utils/
│   ├── time.py
│   ├── logging.py
│   └── hashing.py
└── storage/
    ├── events/
    ├── incidents/
    ├── audit/
    └── snapshots/
```
---

## 6. Key Workflows

### 6.1 Camera Registration
1. Admin adds camera in Admin Console
2. `camera_registry` persists camera config
3. `camera_manager` starts worker automatically if enabled
4. Worker health shown on dashboard

### 6.2 User Registration (Known Identity)
1. Admin uploads photo or captures from a camera
2. Face embeddings saved in `face_store`
3. `identity_resolver` links unknown tracks to the new user
4. Past events/incidents can display “Previously Unknown → Now Known”

### 6.3 Incident Lifecycle
**States**
- OPEN → ACKNOWLEDGED → (SNOOZED) → ESCALATED → RESOLVED / FALSE_POSITIVE

**Actions**
- Acknowledge / Snooze / Escalate / Resolve / Mark False Positive
- Each action creates:
  - incident timeline entry
  - audit log entry (who performed it)

### 6.4 Escalation Matrix
- Config-driven rules determine:
  - when to raise sound alerts
  - who to notify
  - when to auto-escalate
  - whether to capture snapshot/clip
- Quiet hours override supported

---

## 7. Configuration (Minimum Required)

### 7.1 Cameras (`config/cameras.json`)
- id, name, type (USB/RTSP), source, enabled
- detection rates and sensitivity
- zones and privacy options
- recording mode + retention

### 7.2 Users (`config/users.json`)
- id, name, role, metadata
- face samples list
- watchlist flag and rule overrides

### 7.3 Escalation (`config/escalation.json`)
- per severity: sound, routing, auto-escalation timers, auto-actions

### 7.4 System (`config/system.json`)
- global toggles (sound enabled, quiet hours, privacy defaults)
- storage paths and retention defaults

---

## 8. Security & Privacy

- Role-based access:
  - Admin / Caregiver / Viewer / Supervisor
- Session tracking:
  - logins, timeouts, lock screen
- Privacy modes:
  - optional face blurring for non-watchlist users
  - recording disabled by default (events-only optional)
- Retention:
  - automatic cleanup based on policy

---

## 9. Non-Goals (For Initial Releases)

- Cloud dependency as a requirement (optional later)
- Heavy distributed microservices architecture
- Real-time external emergency service integration (phase later)
- Full ML model training pipelines (use pretrained models initially)

---

## 10. Roadmap (Phased Delivery)

### Phase 1 — Foundation
- Camera registry & workers
- Single dashboard
- Basic storage and logging

### Phase 2 — Intelligence
- Face detection/recognition
- Object detection
- Activity detection
- Threat scoring + snapshots

### Phase 3 — Incidents & Escalation
- Incident manager and lifecycle
- Escalation matrix
- Sound alerts & UI actions

### Phase 4 — Admin & Audit
- Admin console for cameras/users
- Audit trail UI + export
- Unknown → Known relabeling

### Phase 5 — Multi-Camera Analytics
- Building-wide people search and last-seen
- Movement trail across cameras
- Analytics and heatmaps

---

## 11. Glossary

- **Event:** Raw AI output normalized into a structured record (e.g., “knife detected near person”)
- **Incident:** A workflow object created from events that requires acknowledgment/resolution
- **Escalation Matrix:** Rules controlling timing, routing, and alert behavior by severity
- **Watchlist:** People needing higher monitoring priority and stricter rules

---

## 12. Ownership & Branching (Suggested)

- `main`: stable releases
- `develop`: integration
- `feature/guardian-<jira>-<desc>`: feature branches per JIRA feature
- Optional: `epic/guardian-<epic>` for larger bodies of work

---