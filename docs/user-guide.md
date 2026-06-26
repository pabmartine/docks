# User Guide

## Overview

`Docks` lets you manage the local Docker engine from a GNOME desktop interface with four main areas:

- Containers
- Images
- Networks
- Volumes

## Navigation

- Use the sidebar to switch sections.
- The right panel header shows the current view title and available actions.
- `Ctrl+F` opens search for the active section.
- `F5` and `Ctrl+R` trigger a manual refresh.

## Search

- Search is independent per section.
- Text entered in one section does not affect the others.
- The search bar is shown at the bottom of the right panel.

## Containers

From the container view you can:

- sort by columns,
- open details,
- open logs,
- start,
- stop,
- restart,
- pause,
- unpause,
- remove,
- use multi-selection for bulk actions.

### Logs

In the log view you can:

- follow output in real time,
- pause following,
- copy the text,
- save it to a file,
- change the initial `tail`.

## Images

From the image view you can:

- sort by columns,
- search by tag or identifier,
- view details,
- pull a specific image,
- prune unused images,
- remove an image.

## Networks

From the network view you can:

- sort and search,
- create a network,
- choose the driver and basic local network options,
- prune unused networks,
- view details,
- remove it.

## Volumes

From the volume view you can:

- sort and search,
- create a volume,
- prune unused volumes,
- view details,
- remove it.

## Prune Actions

Images, networks, and volumes expose `Prune` actions from the section header.

- Prune actions always ask for confirmation first.
- They run in the background.
- If resources are removed, the app shows a summary dialog.
- If nothing can be removed, the app shows a lightweight toast instead.

## Details

The detail view shows readable information for each resource and lets you go back to the list using the header back button.

If a resource disappears while the view is open, the application shows an error state instead of breaking the UI.

## Preferences

From the application menu you can change:

- interface language,
- color scheme.

## Common Errors

### Docker unavailable

If the local engine does not respond, `Docks` shows an error page with a retry action.

### External changes

If a resource changes or disappears outside the application, views can update automatically after engine events or when you trigger a manual refresh.
