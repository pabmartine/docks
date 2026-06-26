import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk


CSS = """
.sidebar-header-title {
  font-weight: 700;
}

.eyebrow {
  opacity: 0.72;
  font-size: 0.85rem;
  font-weight: 600;
}

.hero-title {
  font-size: 1.8rem;
  font-weight: 800;
}

.resource-title {
  font-size: 1.05rem;
  font-weight: 700;
}

.resource-subtitle {
  opacity: 0.75;
}

.sidebar-row {
  min-height: 42px;
  padding: 2px 6px;
  border-radius: 9px;
}

.sidebar-row-label {
  font-weight: 400;
}

.nav-row-active {
  background: alpha(currentColor, 0.08);
}

.count-badge {
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
  color: @accent_fg_color;
  background: alpha(@accent_color, 0.22);
}

.count-badge.muted {
  color: alpha(currentColor, 0.90);
  background: alpha(currentColor, 0.12);
}

.status-chip {
  border-radius: 999px;
  padding: 3px 10px;
  background: alpha(currentColor, 0.12);
  font-size: 0.82rem;
  font-weight: 600;
}

.status-chip.running {
  color: @success_color;
  background: alpha(@success_color, 0.14);
}

.status-chip.exited {
  color: alpha(currentColor, 0.8);
  background: alpha(currentColor, 0.10);
}

.status-chip.available,
.status-chip.ready,
.status-chip.active {
  color: @accent_color;
  background: alpha(@accent_color, 0.14);
}

.metric-card {
  border-radius: 18px;
  padding: 16px;
  background: alpha(currentColor, 0.04);
}

.metric-value {
  font-size: 1.9rem;
  font-weight: 800;
}

.metric-label {
  opacity: 0.72;
  font-size: 0.95rem;
}

.action-pill {
  min-width: 30px;
  min-height: 30px;
  border-radius: 999px;
  padding: 0;
}

.table-shell {
  border-radius: 16px;
  background: @card_bg_color;
}

.table-header {
  padding: 10px 14px;
  border-bottom: 1px solid alpha(currentColor, 0.08);
}

.table-row {
  padding: 12px 14px;
  border-bottom: 1px solid alpha(currentColor, 0.06);
}

.table-row:last-child {
  border-bottom: none;
}

.table-heading {
  font-size: 0.92rem;
  font-weight: 700;
}

.table-primary {
  font-weight: 600;
}

.dialog-field-label {
  font-size: 0.92rem;
  font-weight: 600;
}

.sort-header-button {
  padding: 0;
}

.panel-card {
  margin: 12px;
}

.detail-summary-card {
  padding: 20px;
}

.detail-summary-title {
  font-size: 1.35rem;
  font-weight: 800;
}

.detail-summary-subtitle {
  opacity: 0.72;
}

.detail-facts {
  margin-top: 4px;
}

.detail-fact {
  border-radius: 12px;
  padding: 12px 14px;
  background: alpha(currentColor, 0.04);
}

.detail-fact-title {
  opacity: 0.72;
  font-size: 0.82rem;
  font-weight: 600;
}

.detail-fact-value {
  font-weight: 700;
}

.loading-indicator {
  box-shadow: 0 8px 24px alpha(black, 0.08);
}
"""


def apply_custom_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
