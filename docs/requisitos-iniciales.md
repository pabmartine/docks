# Docks - Initial Requirements Document

Date: 2026-03-13

## 1. Goal

`Docks` is intended to be a GNU/Linux desktop application for GNOME, written in Python with a `GTK4 + libadwaita` interface, focused on managing Docker resources through a native desktop experience aligned with GNOME design guidelines.

This document records:

- The functional requirements identified from the analysis of the `Pods` application.
- The proposed incremental development approach for building a useful first version while keeping a solid base for future expansion.

## 2. Product Vision

`Docks` should make it possible to manage a local or remote Docker instance from a modern graphical application, prioritizing:

- Strong visual integration with GNOME.
- Clear visibility into container, image, and volume state.
- Common Docker actions without needing the terminal for everyday cases.
- An architecture prepared for events, near-real-time updates, and gradual growth.

## 3. Design Principles

- A `libadwaita` interface that is adaptive and consistent with GNOME Human Interface Guidelines.
- A simple navigation flow: connection -> main views -> details -> actions.
- Terminology aligned with Docker.
- Clear separation between:
  - UI layer,
  - Docker access layer,
  - state/model layer,
  - configuration persistence.
- The first version should focus on essentials; parity with `Pods` should arrive in phases.

## 4. Functional Analysis of Pods

The current `Pods` application includes, among others, the following capabilities:

- Local and remote connection management.
- Connection persistence and last-used connection restore.
- Engine availability detection on connect.
- Main view with side panels and section navigation.
- Management of images, containers, pods, and volumes.
- Container and pod lifecycle actions such as start, stop, pause, restart, and remove.
- Creation of containers, pods, and volumes.
- Image pull, build, push, and prune.
- Logs, interactive terminal, inspection, processes, and metrics/statistics.
- Long-running actions with progress tracking and textual output.
- Search, filtering, sorting, and multi-selection.
- Keyring integration for registry credentials.

Not all of this needs to be in `Docks` from the beginning, but it should be considered as part of the longer-term roadmap.

## 5. Target Functional Scope for Docks

### 5.1 Platform and Technology Requirements

- The application should be written in Python.
- The UI should use `GTK4 + libadwaita` through `PyGObject`.
- The application should target Linux/GNOME first.
- Docker communication should preferably use the Docker API through:
  - a local Unix socket,
  - configurable remote endpoints,
  - TLS support if secure remote connections are implemented.

### 5.2 User Experience Requirements

- Adaptive main window, usable on desktop and reduced sizes.
- Clear sidebar navigation for the main sections.
- Well-resolved empty states.
- Understandable error messages.
- Visible loading and in-progress operation indicators.
- Search support where it makes sense.
- Basic keyboard shortcuts aligned with GNOME where applicable.

### 5.3 Connection Requirements

- Detect local Docker automatically on startup or when opening the application.
- Allow configuring one or more Docker connections.
- Support at minimum:
  - local Unix socket,
  - remote endpoint by URL.
- Validate the connection through `ping` or an equivalent query before activating it.
- Save connections to disk.
- Remember the last used connection.
- Show whether the connection is active, connecting, or failed.

### 5.4 Initial Data Model Requirements

The application should organize its state around one active connection and, at minimum, these collections:

- Containers.
- Images.
- Volumes.

Later, this may expand to:

- Networks.
- Ongoing builds.
- Events.
- Registry credentials.

### 5.5 Synchronization and Refresh Requirements

- Load initial data on connect.
- Refresh information manually.
- Design the architecture to support:
  - periodic refresh,
  - engine event listening,
  - incremental state updates.
- Avoid blocking the UI during Docker or network operations.

### 5.6 Container Requirements

Minimum target:

- List containers.
- Show state, name, associated image, and short identifier.
- Show basic container details.
- Start a stopped container.
- Stop a running container.
- Restart a container.
- Remove a container.
- Container creation in a near follow-up phase.
- Log viewing in a near follow-up phase.

Desired future:

- Pause and unpause.
- Rename.
- JSON inspection.
- Metrics/statistics.
- Processes.
- Interactive terminal.
- Copy files to and from the container.
- Commit to image.
- Bulk actions on multiple containers.

### 5.7 Image Requirements

Minimum target:

- List images.
- Show tags/repository, size, and identifier.
- Show basic details.
- Remove an image.
- Pull an image.

Desired future:

- Build from context and Dockerfile.
- Push to registry.
- History.
- Registry search.
- Additional tagging.
- Prune unused images.

### 5.8 Volume Requirements

Minimum target:

- List volumes.
- Show name and basic metadata.
- Show basic details.
- Remove a volume.
- Create a volume.

Desired future:

- Show associated containers.
- Prune unused volumes.

### 5.9 Network Requirements

This is not part of the very first target, but the architecture should account for it early so it can be added later:

- Network listing.
- Network details.
- Create and remove networks.
- Association between containers and networks.

### 5.10 Actions and Long-Running Operation Requirements

- Any potentially slow operation should run in the background.
- The UI should reflect:
  - operation in progress,
  - success,
  - error.
- There should be a base for a future action/activity view.
- Streaming operations such as `pull`, `build`, or logs should support incremental output.

### 5.11 Persistence Requirements

- Save application configuration in a user directory.
- Save the connection list.
- Save basic UI preferences:
  - last view,
  - window size,
  - last used connection.

### 5.12 Security and Credentials Requirements

- In later phases, integrate secure storage for registry credentials through the system keyring.
- Do not store secrets in plain text except through an explicit, temporary development decision.

## 6. Proposed Incremental Development

### Phase 0 - Project Foundation

Goal: establish a clean and maintainable base.

Deliverables:

- Initial Python project structure.
- GTK4/libadwaita application starting correctly.
- Adaptive main window.
- Base styles and minimal resources.
- Initial architecture separated into:
  - `app`,
  - `ui`,
  - `docker`,
  - `models`,
  - `storage`.

### Phase 1 - GNOME Interface Shell

Goal: build the base experience before broader functional parity.

Deliverables:

- Main window using `Adw.Application`.
- `Adw.NavigationSplitView` or equivalent pattern.
- Sidebar/menu with sections:
  - Containers,
  - Images,
  - Volumes.
- Welcome or empty-state view.
- Connection management dialog or page.
- Reusable components for lists, details, and messages.

This phase should be completed before aiming for broader parity with `Pods`.

### Phase 2 - Docker Connectivity

Goal: detect and activate a usable connection.

Deliverables:

- Local Docker detection.
- Manual connection to a remote endpoint.
- Connectivity verification.
- Connection persistence.
- Active connection selection.
- Initial loading of basic engine information.

### Phase 3 - Minimum Management of Containers, Images, and Volumes

Goal: deliver a first useful version.

Deliverables:

- Container listing.
- Image listing.
- Volume listing.
- Basic detail views.
- Core lifecycle actions.
- Initial error handling.

## Note

This file is intentionally preserved as the original planning document. It does not fully match the current product direction anymore. For the live scope, see [status.md](./status.md) and [roadmap.md](./roadmap.md).
