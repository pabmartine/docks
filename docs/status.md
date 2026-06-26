# Current Status

Reference date: 2026-03-15

## Current Scope

`Docks` is a GTK4/libadwaita GNOME application focused on managing a local Docker engine through the local Unix socket.

The application is not currently aimed at remote connections, TLS, or multiple active engines. The internal connection model still exists, but the product should currently be understood as a "local Docker client for GNOME".

## Available Features

- Local Docker engine detection on startup.
- Container, image, network, and volume listing.
- Column-based sorting in the main views.
- Search scoped to the active section.
- Detail views for containers, images, networks, and volumes.
- Container actions:
  - start,
  - stop,
  - restart,
  - pause,
  - unpause,
  - remove,
  - basic bulk actions.
- Container logs:
  - follow,
  - pause,
  - copy,
  - save to file,
  - configurable initial `tail`.
- Image actions:
  - view details,
  - remove,
  - per-image `pull`,
  - prune unused images.
- Network actions:
  - create,
  - view details,
  - remove,
  - prune unused networks.
- Volume actions:
  - create,
  - view details,
  - remove,
  - prune unused volumes.
- Manual refresh and automatic refresh through local engine events.
- Language and color scheme preferences.

## Current Product Decisions

- Local Docker only.
- No JSON inspection view.
- No container creation from the image view.
- No quick status filters; the primary interaction model is sorting and searching.
- Resource creation is intentionally scoped:
  - volumes use a simple name-only dialog,
  - networks expose a small local-focused set of options,
  - image pulls are triggered per row instead of from a global input.

## Local Persistence

The application stores configuration in:

- `~/.config/docks/settings.json`
- `~/.config/docks/connections.json`

At minimum, it currently persists:

- window size,
- last opened view,
- last used connection,
- language,
- color scheme.

## Known Limitations

- The main automated validation is `unittest`; there are no end-to-end UI tests.
- The application is still focused on common local workflows; more advanced Docker operations are not exposed yet.
- [requisitos-iniciales.md](./requisitos-iniciales.md) contains future-facing scope that does not fully match the current product direction anymore.
