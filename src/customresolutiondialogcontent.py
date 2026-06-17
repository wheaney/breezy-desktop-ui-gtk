from gi.repository import Gtk, Gio
from .settingsmanager import SettingsManager

import gettext

_ = gettext.gettext


@Gtk.Template(resource_path='/com/xronlinux/BreezyDesktop/gtk/custom-resolution-dialog-content.ui')
class CustomResolutionDialogContent(Gtk.Box):
    __gtype_name__ = 'CustomResolutionDialogContent'

    custom_resolution_width_scale = Gtk.Template.Child()
    custom_resolution_width_adjustment = Gtk.Template.Child()
    custom_resolution_height_scale = Gtk.Template.Child()
    custom_resolution_height_adjustment = Gtk.Template.Child()

    def __init__(self, add_button, on_add_callback, max_width=None, max_height=None):
        super(Gtk.Box, self).__init__()
        self.init_template()

        self.on_add_callback = on_add_callback

        # Optionally cap the resolution sliders (e.g. the Breezy Box limits
        # custom resolutions to 1080p). Clamp the adjustment's upper bound, pull
        # the current value down if it sits above the new cap, and drop any
        # scale marks that now fall outside the range.
        # Marks come from the .ui template; mirror them here so we can re-add
        # only the ones still in range after capping.
        if max_width is not None:
            self._cap_scale(self.custom_resolution_width_scale,
                            self.custom_resolution_width_adjustment,
                            max_width, (640, 1280, 1920, 2560, 3840))
        if max_height is not None:
            self._cap_scale(self.custom_resolution_height_scale,
                            self.custom_resolution_height_adjustment,
                            max_height, (480, 720, 1080, 1440, 2160))

        add_button.connect('clicked', self._on_add_button_clicked)

    def _cap_scale(self, scale, adjustment, max_value, marks):
        adjustment.set_upper(max_value)
        if adjustment.get_value() > max_value:
            adjustment.set_value(max_value)

        # Re-add only the in-range marks so the scale shows no labels past the cap.
        scale.clear_marks()
        for value in marks:
            if value <= max_value:
                scale.add_mark(value, Gtk.PositionType.BOTTOM, str(int(value)))

    def _on_add_button_clicked(self, button):
        self.on_add_callback(self.custom_resolution_width_adjustment.get_value(), self.custom_resolution_height_adjustment.get_value())