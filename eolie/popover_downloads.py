# Copyright (c) 2017 Cedric Bellegarde <cedric.bellegarde@adishatz.org>
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from gi.repository import Gtk, GLib, Gio, WebKit2

from time import time
from gettext import gettext as _

from eolie.define import El


class DownloadRow(Gtk.ListBoxRow):
    """
        A Download row row
    """
    def __init__(self, download, finished):
        """
            Init row
            @param download as WebKit2.Download
            @param finished as bool
        """
        Gtk.ListBoxRow.__init__(self)
        self.__download = download
        self.__finished = finished
        self.__download_previous_time = None
        self.__download_bytes = 0
        self.__avg_download_rates = []
        self.__uri = self.__download.get_request().get_uri()
        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/Eolie/RowDownload.ui")
        builder.connect_signals(self)
        self.__preview = builder.get_object("preview")
        self.__progress = builder.get_object("progress")
        self.__label = builder.get_object("label")
        self.__sublabel = builder.get_object("sublabel")
        destination = download.get_destination()
        self.__label.set_label(destination.split("/")[-1])
        self.__button = builder.get_object("button")
        self.__button_image = builder.get_object("button_image")
        if finished:
            self.__on_finished(download)
        else:
            progress = download.get_estimated_progress()
            self.__progress.set_fraction(progress)
        self.add(builder.get_object("row"))
        self.connect("map", self.__on_map)
        self.connect("unmap", self.__on_unmap)

    @property
    def finished(self):
        """
            True if download is finished
        """
        return self.__finished

    @property
    def download(self):
        """
            Get row download
            @return WebKit2.Download
        """
        return self.__download

#######################
# PROTECTED           #
#######################
    def _on_cancel_button_clicked(self, button):
        """
            Cancel download
            @param button as Gtk.Button
        """
        if self.__button_image.get_icon_name()[0] == "window-close-symbolic":
            self.__download.cancel()
            self.get_style_context().add_class("download-failed")
        elif self.__button_image.get_icon_name()[0] == "view-refresh-symbolic":
            webview = self.__download.get_web_view()
            El().download_manager.remove(self.__download)
            if webview is None:
                WebKit2.WebContext.get_default().download_uri(self.__uri)
            else:
                webview.download_uri(self.__uri)
            self.destroy()

#######################
# PRIVATE             #
#######################
    def __human_bytes_per_sec(self, bytes_per_sec):
        """
            Convert bytes per seconds to human visible string
            @param bytes_per_sec as float
        """
        prefix = _("Download speed:")
        if bytes_per_sec < 1024:
            suffix = _("bytes/s")
            string = "%s" % round(bytes_per_sec, 2)
        elif bytes_per_sec / 1024 < 1024:
            suffix = _("KiB/s")
            string = "%s" % round(bytes_per_sec / 1024, 2)
        else:
            suffix = _("MiB/s")
            string = "%s" % round(bytes_per_sec / 1024 / 1024, 2)
        return "%s\n%s %s %s" % (self.__label.get_text(),
                                 prefix,
                                 string,
                                 suffix)

    def __human_seconds(self, seconds):
        """
            Convert time in seconds to human visible string
            @param seconds as int
            @return str
        """
        seconds_str = ""
        minutes_str = ""
        hours_str = ""
        hours = -1
        minutes = -1
        seconds_wanted = True
        # Make seconds string
        if seconds < 60:
            if seconds < 2:
                seconds_str = _("%s second") % seconds
            else:
                seconds_str = _("%s seconds") % seconds
        else:
            _seconds = seconds % 60
            if _seconds < 2:
                seconds_str = _("%s second") % _seconds
            else:
                seconds_str = _("%s seconds") % _seconds

        # Make minutes string
        if seconds > 59:
            minutes = int(seconds / 60)
            if minutes < 2:
                minutes_str = _("%s minute") % minutes
            elif minutes < 60:
                seconds_wanted = False
                minutes_str = _("%s minutes") % minutes
            else:
                seconds_wanted = False
                _minutes = minutes % 60
                if _minutes < 2:
                    minutes_str = _("%s minute") % _minutes
                else:
                    minutes_str = _("%s minutes") % _minutes

        # Make hour string
        if minutes > 59:
            hours = int(minutes / 60)
            if hours < 2:
                hours_str = _("%s hours") % hours
            else:
                hours_str = _("%s hour") % hours
        string = _("Remaining time:") + " "
        if hours_str:
            string += hours_str + ", "
        if minutes_str:
            string += minutes_str
        if seconds_wanted and minutes_str:
            string += ", "
        if seconds_wanted and seconds_str:
            string += seconds_str
        return string

    def __on_map(self, widget):
        """
            Connect signals
            @param widget as Gtk.Widget
        """
        self.__download_previous_time = None
        self.__download.connect("finished", self.__on_finished)
        self.__download.connect("received-data", self.__on_received_data)
        self.__download.connect("failed", self.__on_failed)
        response = self.__download.get_response()
        if response is None:
            return
        destination = self.__download.get_destination()
        try:
            f = GLib.filename_from_uri(destination)[0]
            (mime, uncertain) = Gio.content_type_guess(f, None)
            if uncertain:
                self.__preview.set_from_icon_name("text-x-generic",
                                                  Gtk.IconSize.DIALOG)
            else:
                icon = Gio.content_type_get_icon(mime)
                self.__preview.set_from_gicon(icon, Gtk.IconSize.DIALOG)
        except:
            self.__preview.set_from_icon_name("text-x-generic",
                                              Gtk.IconSize.DIALOG)

    def __on_unmap(self, widget):
        """
            Disconnect signals
            @param widget as Gtk.Widget
        """
        self.__download.disconnect_by_func(self.__on_finished)
        self.__download.disconnect_by_func(self.__on_received_data)
        self.__download.disconnect_by_func(self.__on_failed)

    def __on_received_data(self, download, length):
        """
            @param download as WebKit2.Download
            @param length as int
        """
        try:
            response = download.get_response()
            incoming = response.get_content_length() - length
            new_time = time()
            self.__download_bytes += length
            if self.__download_previous_time is not None:
                delta = new_time - self.__download_previous_time
                # Update every 1 seconds
                if delta > 1:
                    bytes_per_second = 1 * self.__download_bytes /\
                                        delta
                    self.__avg_download_rates.append(bytes_per_second)
                    self.set_tooltip_text(self.__human_bytes_per_sec(
                                                             bytes_per_second))
                    # Calculate average for last 10 rates
                    avg = 0
                    for rate in self.__avg_download_rates:
                        avg += rate
                    if len(self.__avg_download_rates) > 10:
                        self.__avg_download_rates.pop(0)
                    avg /= len(self.__avg_download_rates)
                    if incoming > 0:
                        seconds = incoming / avg
                        self.__sublabel.set_label(
                                            self.__human_seconds(int(seconds)))
                    self.__download_bytes = 0
                    self.__download_previous_time = new_time
            else:
                self.__download_previous_time = new_time
            self.__progress.set_fraction(download.get_estimated_progress())
        except Exception as e:
            print("DownloadPopover::__on_received_data():", e)

    def __on_finished(self, download):
        """
            @param download as WebKit2.Download
        """
        self.__sublabel.set_label("")
        self.set_tooltip_text(self.__label.get_text())
        self.__finished = True
        self.__progress.set_opacity(0)
        parent = self.get_parent()
        if parent is not None:
            parent.invalidate_sort()
        if self.__button_image.get_icon_name()[0] == "view-refresh-symbolic":
            return True
        else:
            self.__button.hide()

    def __on_failed(self, download, error):
        """
            @param download as WebKit2.Download
            @param error as GLib.Error
        """
        self.__button_image.set_from_icon_name("view-refresh-symbolic",
                                               Gtk.IconSize.MENU)
        self.get_style_context().add_class("download-failed")


class DownloadsPopover(Gtk.Popover):
    """
        Show current downloads
    """

    def __init__(self, window):
        """
            Init popover
            @param window as Window
        """
        Gtk.Popover.__init__(self)
        self.set_modal(False)
        window.register(self)
        builder = Gtk.Builder()
        builder.add_from_resource("/org/gnome/Eolie/PopoverDownloads.ui")
        builder.connect_signals(self)
        self.__listbox = builder.get_object("downloads_box")
        self.__listbox.connect("row-activated", self.__on_row_activated)
        self.__listbox.set_placeholder(builder.get_object("placeholder"))
        self.__listbox.set_sort_func(self.__sort)
        self.__scrolled = builder.get_object("scrolled")
        self.__clear_button = builder.get_object("clear_button")
        self.add(builder.get_object("widget"))
        self.connect("map", self.__on_map)
        self.connect("unmap", self.__on_unmap)
        self.__populate()

#######################
# PROTECTED           #
#######################
    def _on_open_clicked(self, button):
        """
            Open download folder
            @param button as Gtk.button
        """
        directory_uri = El().settings.get_value("download-uri").get_string()
        if not directory_uri:
            directory = GLib.get_user_special_dir(
                                         GLib.UserDirectory.DIRECTORY_DOWNLOAD)
            directory_uri = GLib.filename_to_uri(directory, None)
        Gtk.show_uri(None, directory_uri, int(time()))
        self.hide()

    def _on_clear_clicked(self, button):
        """
            Clear finished downloads
            @param button as Gtk.button
        """
        self.__clear_button.set_sensitive(False)
        for child in self.__listbox.get_children():
            if isinstance(child, DownloadRow):
                if child.finished:
                    El().download_manager.remove(child.download)
                    child.destroy()

#######################
# PRIVATE             #
#######################
    def __sort(self, row1, row2):
        """
            Sort listbox
            @param row1 as Row
            @param row2 as Row
        """
        if row1.finished:
            return True
        elif row2.finished or row1.download.get_estimated_progress() >\
                row2.download.get_estimated_progress():
            return False

    def __populate(self):
        """
            Populate listbox
        """
        clear = False
        for download in El().download_manager.get():
            if download.get_destination() is None:
                continue
            child = DownloadRow(download, False)
            child.connect("size-allocate",
                          lambda x, y: self.__calculate_height())
            child.connect("destroy",
                          lambda x: self.__calculate_height())
            child.show()
            self.__listbox.add(child)
        for download in El().download_manager.get_finished():
            if download.get_destination() is None:
                continue
            child = DownloadRow(download, True)
            child.connect("size-allocate",
                          lambda x, y: self.__calculate_height())
            child.connect("destroy",
                          lambda x: self.__calculate_height())
            clear = True
            child.show()
            self.__listbox.add(child)
        self.__clear_button.set_sensitive(clear)

    def __calculate_height(self):
        """
            Update popover height request
        """
        height = 0
        for child in self.__listbox.get_children():
            if child.is_visible():
                height += child.get_allocated_height()
        size = self.get_ancestor(Gtk.Window).get_size()
        if height > size[1] * 0.6:
            height = size[1] * 0.6
        self.__scrolled.set_size_request(400, height)

    def __on_row_activated(self, listbox, row):
        """
            Launch row if download finished
            @param listbox as Gtk.ListBox
            @param row as Row
        """
        try:
            if row.finished:
                Gtk.show_uri(None, row.download.get_destination(), int(time()))
                self.hide()
        except:  # Destination not found
            pass

    def __on_map(self, widget):
        """
            Setup widget
            @param widget as Gtk.Widget
        """
        El().download_manager.connect("download-start",
                                      self.__on_download_start)
        El().download_manager.connect("download-finish",
                                      self.__on_download_finish)
        self.set_size_request(400, -1)

    def __on_unmap(self, widget):
        """
            Clean up widget
            @param widget as Gtk.Widget
        """
        for child in self.__listbox.get_children():
            child.destroy()
        El().download_manager.disconnect_by_func(self.__on_download_start)
        El().download_manager.disconnect_by_func(self.__on_download_finish)

    def __on_download_start(self, download_manager, download_name):
        """
            Add download
            @param download manager as Download Manager
            @param download_name as str
        """
        for download in El().download_manager.get():
            if download.get_destination() is None:
                continue
            if str(download) == download_name:
                child = DownloadRow(download, False)
                child.connect("size-allocate",
                              lambda x, y: self.__calculate_height())
                child.connect("destroy",
                              lambda x: self.__calculate_height())
                child.show()
                self.__listbox.add(child)
                break

    def __on_download_finish(self, download_manager):
        """
            Update clear button
            @param download manager as Download Manager
        """
        self.__clear_button.set_sensitive(True)
