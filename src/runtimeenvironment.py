import gettext
from dataclasses import dataclass
from typing import Callable

from gi.repository import GObject

_ = gettext.gettext

# Default namespace used for XDG directories, application identity, etc. A
# concrete RuntimeEnvironment should override APP_NAMESPACE.
DEFAULT_APP_NAMESPACE = 'breezy_gnome'


@dataclass
class ExtraTab:
    """Descriptor for a custom tab added to the connected-device view.

    Attributes:
        name:          Unique page name passed to AdwViewStack (must not clash
                       with built-in names 'general', 'shortcuts', 'advanced').
        title:         Localised tab label shown in the AdwViewSwitcher.
        icon_name:     Named icon for the tab (e.g. a symbolic icon name).
        build_widget:  Zero-argument callable that returns the Gtk.Widget to
                       use as the page content.  Called once at init time.
    """
    name: str
    title: str
    icon_name: str
    build_widget: Callable


@dataclass
class ExtraField:
    """Descriptor for a custom row injected into a built-in tab's column.

    The 'general' and 'advanced' tabs lay their AdwPreferencesGroups out
    horizontally — each group is a column.  This appends a row to the bottom of
    the group in the chosen column, so it adds a field without widening the tab
    (appending a whole new group would add a third column and overflow the
    window).  No positional anchoring within the column (which libadwaita's
    containers don't support cleanly anyway); the row goes at the bottom.

    Attributes:
        tab_name:      Name of the built-in tab ('general' or 'advanced').
        column:        Zero-based column index within that tab (0 or 1).
        build_widget:  Zero-argument callable returning the AdwPreferencesRow
                       to append.  Called once at init time.
    """
    tab_name: str
    column: int
    build_widget: Callable


class NullVirtualDisplayManager(GObject.GObject):
    """A no-op virtual display manager.

    Provides the same interface (the 'displays' property + change
    notifications, plus create/destroy methods) that the UI binds to, but
    never creates anything.  Runtime environments that don't support virtual
    displays can use this so the UI degrades gracefully.
    """
    __gproperties__ = {
        'displays': (object, 'Displays', 'A list of the displays', GObject.ParamFlags.READWRITE)
    }

    def __init__(self):
        GObject.GObject.__init__(self)
        # plain attribute (not _displays) so consumers can read `.displays`
        # directly, matching the real VirtualDisplayManager interface
        self.displays = []

    def create_virtual_display(self, width, height, framerate):
        return None

    def destroy_virtual_display(self, pid):
        return False

    def do_set_property(self, prop, value):
        if prop.name == 'displays':
            self.displays = value

    def do_get_property(self, prop):
        if prop.name == 'displays':
            return self.displays


class RuntimeEnvironment(GObject.GObject):
    """Abstraction over the host environment the UI is running in.

    A RuntimeEnvironment encapsulates everything that differs between the
    environments Breezy can run in (e.g. GNOME Shell vs. a headless Breezy Box):
    how the effect is enabled, how the installation is verified, whether/how
    updates are checked, how virtual displays are managed, and which optional
    views and fields the UI should present.

    The first concrete subclass discovered in the bundled ``runtimes`` package
    (see :mod:`breezydesktop.runtime`) is instantiated as the active
    environment, so a build can swap behavior simply by packaging a different
    implementation.

    Subclasses inherit the ``breezy-enabled`` GObject property; override
    :meth:`enable`/:meth:`disable`/:meth:`is_enabled` (and, if needed,
    ``do_set_property``/``do_get_property``) to back it with real state.
    """

    # The application/namespace identifier, e.g. 'breezy_gnome' or 'breezy_box'.
    # Used for namespacing XDG directories and similar.  Subclasses must set
    # this.
    APP_NAMESPACE = None

    __gproperties__ = {
        'breezy-enabled': (bool, 'Breezy Enabled', 'Whether the Breezy Desktop effect is enabled', False, GObject.ParamFlags.READWRITE)
    }

    _instance = None

    @classmethod
    def get_instance(cls):
        if RuntimeEnvironment._instance is None:
            from .runtime import get_runtime_class
            RuntimeEnvironment._instance = get_runtime_class()()
        return RuntimeEnvironment._instance

    def __init__(self):
        GObject.GObject.__init__(self)
        self._breezy_enabled = False
        self._virtual_display_manager = None
        self._extra_settings = None

    # --- identity ---------------------------------------------------------

    @classmethod
    def app_namespace(cls):
        return cls.APP_NAMESPACE or DEFAULT_APP_NAMESPACE

    # --- effect enablement (backs the 'breezy-enabled' property) ----------

    def is_installed(self):
        """Whether the supporting components for this environment are installed.

        Environments with no separate component to install (e.g. a headless
        box where the runtime is always present) should return True.
        """
        return True

    def is_enabled(self):
        return self._breezy_enabled

    def enable(self):
        self._breezy_enabled = True

    def disable(self):
        self._breezy_enabled = False

    # --- verification -----------------------------------------------------

    def verify(self):
        """Verify the installation. Return True when verification passes (or
        when the environment has no verification step)."""
        return True

    # --- update checking --------------------------------------------------

    def check_for_update(self, current_version, callback):
        """Asynchronously check for a newer version.

        Implementations that support updates should invoke
        ``callback(latest_version_str)`` when a newer version is available.
        The default is a no-op (no update prompt).
        """
        return None

    # --- connected-device UI customisation --------------------------------
    #
    # These hooks let subclasses tailor the connected-device view without
    # touching any GTK template.  Three concepts:
    #
    #   excluded_field_ids  — set of Gtk.Template.Child() names whose parent
    #                         AdwActionRow should be hidden in this environment.
    #
    #   excluded_tab_names  — set of AdwViewStackPage names (e.g. 'shortcuts',
    #                         'advanced') whose tab should be hidden entirely.
    #
    #   extra_tabs          — ordered list of ExtraTab descriptors that the
    #                         connected-device view appends after the built-in
    #                         tabs.  Each descriptor is a namedtuple-like object
    #                         with (name, title, icon_name, build_widget) where
    #                         build_widget() → Gtk.Widget is called once at init.
    #
    # Default: show everything, add nothing.

    @property
    def excluded_field_ids(self):
        """Return a frozenset of ConnectedDevice template-child names to hide.

        Each name must match a ``Gtk.Template.Child()`` attribute on
        ``ConnectedDevice``.  The connected-device view will call
        ``set_visible(False)`` on the parent ``AdwActionRow`` of each widget
        whose ID is listed here.

        The default set includes fields that are specific to a particular host
        environment (e.g. GNOME-only settings) and should be hidden unless the
        runtime explicitly wants them.

        Example::

            @property
            def excluded_field_ids(self):
                return frozenset(['effect_enable_switch'])
        """
        # text_scaling_scale is GNOME-specific (org.gnome.desktop.interface);
        # hidden by default, exposed only by runtimes that run under GNOME.
        return frozenset(['text_scaling_scale'])

    @property
    def excluded_tab_names(self):
        """Return a frozenset of AdwViewStackPage names to hide.

        Built-in page names are ``'general'``, ``'shortcuts'``, and
        ``'advanced'``.  The connected-device view sets each matching page's
        ``visible`` property to ``False`` so the tab does not appear in the
        switcher.

        Example::

            @property
            def excluded_tab_names(self):
                return frozenset(['shortcuts'])
        """
        return frozenset()

    @property
    def extra_tabs(self):
        """Return an ordered list of :class:`ExtraTab` descriptors to append.

        Each :class:`ExtraTab` is appended to the ``AdwViewStack`` after the
        built-in tabs.  The connected-device view calls ``build_widget()`` once
        during initialisation and passes the resulting widget to
        ``AdwViewStack.add_titled_with_icon``.

        Example::

            @property
            def extra_tabs(self):
                return [ExtraTab(
                    name='host_shortcuts',
                    title=_('Keyboard Shortcuts'),
                    icon_name='preferences-desktop-keyboard-shortcuts-symbolic',
                    build_widget=self._build_shortcuts_widget,
                )]
        """
        return []

    @property
    def extra_fields(self):
        """Return an ordered list of :class:`ExtraField` descriptors to inject.

        Each :class:`ExtraField` appends a row to the bottom of the preferences
        group in the given column of a built-in tab ('general' or 'advanced',
        each of which has two columns).  Use this to add a field where a
        built-in one was hidden, without widening the tab.  The connected-device
        view calls ``build_widget()`` once during initialisation.

        Example::

            @property
            def extra_fields(self):
                return [ExtraField(
                    tab_name='general',
                    column=0,
                    build_widget=self._build_virtual_displays_row,
                )]
        """
        return []

    def create_extra_settings(self):
        """Instantiate any additional Gio.Settings objects this runtime needs.

        Override to return a ``Gio.Settings`` instance (or any object with a
        compatible bind/reset interface) for settings schemas beyond the core
        Breezy schema.  The result is cached in :attr:`extra_settings` and
        passed to :meth:`bind_runtime_fields` and :meth:`reset_excluded_fields`.

        Return ``None`` (the default) if no extra settings are needed.

        Example::

            def create_extra_settings(self):
                return Gio.Settings.new("org.gnome.desktop.interface")
        """
        return None

    @property
    def extra_settings(self):
        """Cached result of :meth:`create_extra_settings`."""
        if self._extra_settings is None:
            self._extra_settings = self.create_extra_settings()
        return self._extra_settings

    def reset_excluded_fields(self, settings):
        """Reset any excluded fields to their appropriate locked values.

        Called by the connected-device view after hiding excluded rows.
        ``settings`` is the core Breezy ``Gio.Settings`` object.  Access any
        additional settings via :attr:`extra_settings`.

        Example::

            def reset_excluded_fields(self, settings):
                settings.reset('disable-physical-displays')
                settings.reset('use-optimal-monitor-config')
        """

    def bind_runtime_fields(self, settings, widget_map):
        """Bind any runtime-specific fields not wired in ConnectedDevice.

        Called once during initialisation, after the standard GSettings
        bindings have been established and before rows are hidden.  Use this
        to bind fields whose settings schema is environment-specific.
        ``settings`` is the core Breezy ``Gio.Settings`` object; access any
        additional settings via :attr:`extra_settings`.  ``widget_map`` is a
        ``{name: widget}`` dict of all ``Gtk.Template.Child()`` attributes on
        ``ConnectedDevice``.

        Example::

            def bind_runtime_fields(self, settings, widget_map):
                if self.extra_settings:
                    self.extra_settings.bind(
                        'text-scaling-factor',
                        widget_map['text_scaling_adjustment'], 'value',
                        Gio.SettingsBindFlags.DEFAULT,
                    )
        """

    # --- virtual displays -------------------------------------------------

    def is_virtual_display_supported(self):
        return False

    def _create_virtual_display_manager(self):
        """Build the virtual display manager for this environment. Override to
        provide a real implementation."""
        return NullVirtualDisplayManager()

    @property
    def virtual_display_manager(self):
        if self._virtual_display_manager is None:
            self._virtual_display_manager = self._create_virtual_display_manager()
        return self._virtual_display_manager

    # --- GObject property plumbing ----------------------------------------

    def do_set_property(self, prop, value):
        if prop.name == 'breezy-enabled' and value != self.is_enabled():
            self.enable() if value else self.disable()

    def do_get_property(self, prop):
        if prop.name == 'breezy-enabled':
            return self.is_enabled()
