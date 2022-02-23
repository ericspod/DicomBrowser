# DicomBrowser
# Copyright (C) 2016-9 Eric Kerfoot, King's College London, all rights reserved
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

# from DicomBrowser import *

__appname__ = "DicomBrowser"
__version_info__ = (1, 3, 0)  # global application version, major/minor/patch
__version__ = "%i.%i.%i" % __version_info__
__author__ = "Eric Kerfoot"
__copyright__ = "Copyright (c) 2016-9 Eric Kerfoot, King's College London, all rights reserved. Licensed under the GPL (see LICENSE.txt)."


import os, sys

scriptdir = os.path.dirname(os.path.abspath(__file__))  # path of the current file

# this allows the script to be run directly from the repository without having to install pydicom or pyqtgraph
if os.path.isdir(scriptdir + "/../pydicom"):
    sys.path.append(scriptdir + "/../pydicom")
    sys.path.append(scriptdir + "/../pyqtgraph")
