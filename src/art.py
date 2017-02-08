# Copyright (c) 2014-2016 Cedric Bellegarde <cedric.bellegarde@adishatz.org>
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

from gi.repository import Gdk, GdkPixbuf, Gio, GLib

from urllib.parse import urlparse
from hashlib import sha256


class Art:
    """
        Base art manager
    """
    if GLib.getenv("XDG_CACHE_HOME") is None:
        __CACHE_PATH = GLib.get_home_dir() + "/.cache/eolie"
    else:
        __CACHE_PATH = GLib.getenv("XDG_CACHE_HOME") + "/eolie"

    def __init__(self):
        """
            Init base art
        """
        self.__create_cache()

    def save_artwork(self, uri, surface, suffix):
        """
            Save artwork for uri with suffix
            @param uri as str
            @param surface as cairo.surface
            @param suffix as str
        """
        encoded = sha256(self.__strip_uri(uri)).hexdigest()
        filepath = "%s/%s_%s.png" % (self.__CACHE_PATH, encoded, suffix)
        pixbuf = Gdk.pixbuf_get_from_surface(surface, 0, 0,
                                             surface.get_width(),
                                             surface.get_height())
        pixbuf.savev(filepath, "png", [None], [None])
        del pixbuf

    def get_artwork(self, uri, suffix, scale_factor, width, heigth):
        """
            @param uri as str
            @param suffix as str
            @param scale factor as int
            @param width as int
            @param height as int
            @return cairo.surface
        """
        encoded = sha256(self.__strip_uri(uri)).hexdigest()
        filepath = "%s/%s_%s.png" % (self.__CACHE_PATH, encoded, suffix)
        f = Gio.File.new_for_path(filepath)
        if f.query_exists():
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(filepath,
                                                             width,
                                                             heigth,
                                                             True)
            surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf,
                                                           scale_factor, None)
            del pixbuf
            return surface
        return None

#######################
# PROTECTED           #
#######################

#######################
# PRIVATE             #
#######################
    def __strip_uri(self, uri):
        """
            Remove prefix from uri
            @param uri as str
            @return bytes
        """
        parsed = urlparse(uri)
        new_uri = "%s%s" % (parsed.netloc, parsed.path)
        return new_uri.encode("utf-8")

    def __create_cache(self):
        """
            Create cache dir
        """
        d = Gio.File.new_for_path(self.__CACHE_PATH)
        if not d.query_exists():
            try:
                d.make_directory_with_parents()
            except:
                print("Can't create %s" % self.__CACHE_PATH)
