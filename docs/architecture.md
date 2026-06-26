# Architecture

## Overview

`Docks` is structured as a `GTK4 + libadwaita` desktop application with a simple separation between UI, services, models, and lightweight persistence.

## Main Structure

- `src/docks/app.py`
  - `Adw.Application` integration point.
  - Defines global actions such as preferences, language, about, and quit.
- `src/docks/ui/window.py`
  - Main window.
  - UI construction.
  - Selection, sorting, search, detail, and log state.
  - Background operation orchestration.
- `src/docks/services/docker_service.py`
  - Lightweight Docker API client over the local Unix socket.
  - Listing, detail, action, and event operations.
- `src/docks/services/connection_service.py`
  - Activates the configured connection.
- `src/docks/repositories/connection_repository.py`
  - Connection persistence.
- `src/docks/core/config.py`
  - Preferences and lightweight app state persistence.
- `src/docks/models/`
  - Container, image, network, volume, and connection models.

## Main Flow

1. `DocksApplication` creates `DocksWindow`.
2. The window loads configuration and activates the last selected connection.
3. The UI is built with `Adw.NavigationSplitView`.
4. Initial Docker data loading runs in the background.
5. Results are pushed back to the GTK main thread through `GLib.idle_add`.
6. The window rebuilds sidebar, content, and header state based on the latest data.

## UI Model

The window is composed of:

- A sidebar with its own `HeaderBar`.
- A right panel with a single dynamic `HeaderBar`.
- Rebuildable main content for list and detail states.
- A bottom search bar scoped to the right panel.
- An overlay for loading indicators.
- A toast overlay for result messages.

## Concurrency

Potentially slow operations must not run on the main GTK thread. The window uses a helper based on `threading.Thread` for:

- initial loading,
- refresh,
- detail loading,
- resource actions,
- log polling,
- event polling.

All GTK updates return to the main thread through `GLib.idle_add`.

## Refresh and Events

UI state is fed by two mechanisms:

- manual refresh,
- Docker event polling to trigger automatic refreshes.

This reduces the need to manually refresh after external changes.

## Persistence

Configuration is stored in user JSON files using atomic writes through a temporary file and replace operation.

## Deliberate Technical Scope

`DockerService` is focused on the local Unix socket. Even though a connection abstraction exists, the current architecture should not be interpreted as complete remote/TLS support.
