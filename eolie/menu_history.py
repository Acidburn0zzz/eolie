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

from gi.repository import Gio, GLib

from hashlib import sha256

from eolie.define import El


class HistoryMenu(Gio.Menu):
    """
        Menu showing closed page
    """

    def __init__(self, items):
        """
            Init menu
            @param items as [WebKit2.BackForwardListItem]
        """
        Gio.Menu.__init__(self)
        for item in items[:10]:
            uri = item.get_uri()
            if uri is None:
                continue
            title = item.get_title()
            if not title:
                title = uri
            encoded = "HISTORY_" + sha256(uri.encode("utf-8")).hexdigest()
            action = El().lookup_action(encoded)
            if action is not None:
                El().remove_action(encoded)
            action = Gio.SimpleAction(name=encoded)
            El().add_action(action)
            action.connect('activate',
                           self.__on_action_clicked,
                           item)
            item = Gio.MenuItem.new(title, "app.%s" % encoded)
            item.set_attribute_value("uri", GLib.Variant("s", uri))
            if uri == "populars://":
                item.set_icon(Gio.ThemedIcon.new("emote-love-symbolic"))
            else:
                icon = None
                # Try to set icon
                for favicon in ["favicon", "favicon_alt"]:
                    filepath = El().art.get_path(uri, favicon)
                    f = Gio.File.new_for_path(filepath)
                    if f.query_exists():
                        icon = Gio.FileIcon.new(f)
                        break
                if icon is not None:
                    item.set_icon(icon)
                else:
                    item.set_icon(Gio.ThemedIcon.new("applications-internet"))
            self.append_item(item)

    def remove_actions(self):
        """
            Remove actions for menu
        """
        for i in range(0, self.get_n_items()):
            uri = self.get_item_attribute_value(i, "uri").get_string()
            encoded = "HISTORY_" + sha256(uri.encode("utf-8")).hexdigest()
            action = El().lookup_action(encoded)
            if action is not None:
                El().remove_action(encoded)

#######################
# PRIVATE             #
#######################
    def __on_action_clicked(self, action, variant, item):
        """
            Load history
            @param Gio.SimpleAction
            @param GVariant
            @param item as WebKit2.BackForwardListItem
        """
        El().active_window.\
            container.current.webview.go_to_back_forward_list_item(item)
