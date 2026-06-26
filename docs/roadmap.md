# Roadmap

## Current Direction

The roadmap follows the active product decision:

- focus on local Docker,
- keep the GNOME experience simple,
- prioritize useful day-to-day actions,
- avoid exposing unnecessary technical complexity.

## High Priority

- Improve relationship visibility:
  - which containers use an image,
  - which containers use a network,
  - which containers mount a volume.
- Improve the `pull` UX:
  - clearer progress feedback,
  - better final result messages.
- Continue refining resource creation dialogs:
  - clearer validation messages,
  - better defaults and hints,
  - visual consistency across all modals.
- Refine logs:
  - better follow control,
  - better scroll handling,
  - clearer visual state transitions.

## Medium Priority

- Better Compose project grouping and visibility.
- Basic container metrics and process information.
- Optional labels and advanced local driver options where they add real value.

## Lower Priority

- Strengthen automated coverage for window logic and UI-adjacent behavior.
- Improve packaging and distribution documentation.
- Keep the root `README.md` aligned with `docs/`.

## Out of Scope for Now

- Remote connections.
- TLS.
- Multiple active engines.
- JSON inspection view.
- Container creation from the image view.
- Interactive terminal.
- Activity history.
