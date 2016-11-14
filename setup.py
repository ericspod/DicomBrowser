
# DicomBrowser
# Copyright (C) 2016 Eric Kerfoot, King's College London, all rights reserved
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

from setuptools import setup
import subprocess,sys
from DicomBrowser import __appname__, __version__

# generate source files
subprocess.check_call('pyrcc4 res/Resources.qrc > DicomBrowser/Resources_rc.py', shell=True)
subprocess.check_call('python -c "import PyQt4.uic.pyuic" res/DicomBrowserWin.ui > DicomBrowser/DicomBrowserWin.py', shell=True)

if 'generate' in sys.argv: # generate only, quit at this point before setup
	sys.exit(0)
		
setup(
	name = __appname__,
	version = __version__,
	packages = ['DicomBrowser']
)
