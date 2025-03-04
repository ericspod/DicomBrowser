# DicomBrowser
# Copyright (C) 2016-22 Eric Kerfoot, King's College London, all rights reserved
#
# This file is part of DicomBrowser.
#
# DicomBrowser is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# DicomBrowser is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program (LICENSE.txt).  If not, see <http://www.gnu.org/licenses/>

__appname__ = "DicomBrowser"
__author__ = "Eric Kerfoot"
__author_email__ = "eric.kerfoot@kcl.ac.uk"
__copyright__ = (
    "Copyright (c) 2016-22 Eric Kerfoot, King's College London, "
    "all rights reserved. Licensed under the GPL (see LICENSE.txt)."
)

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("dicombrowser")
except PackageNotFoundError:
    try:
        from setuptools_scm import get_version
        __version__ = get_version()
    except Exception as e:
        import warnings
        warnings.warn(f"Unable to get version from `importlib` or `setuptools_scm`: {e}")
        __version__ = "???"
