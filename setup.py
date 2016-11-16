
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
import subprocess, sys, platform
from DicomBrowser import __appname__, __version__

if platform.system().lower()=='darwin':
	plat='osx'
elif platform.system().lower()=='windows':
	plat='win'
else:
	plat='linux'

# generate source files
subprocess.check_call('pyrcc4 res/Resources.qrc > DicomBrowser/Resources_rc.py', shell=True)
subprocess.check_call('python -c "import PyQt4.uic.pyuic" res/DicomBrowserWin.ui > DicomBrowser/DicomBrowserWin.py', shell=True)

if 'generate' in sys.argv: # generate only, quit at this point before setup
	sys.exit(0)
		
if 'app' in sys.argv:
	sys.argv.remove('app')
	appname='%s_%s'%(__appname__,__version__)
	icon='res/icon.icns' if platform.system().lower()=='darwin' else 'res/icon.ico'
	paths=['DicomBrowser','pydicom','pyqtgraph']
	hidden=['Queue']
	flags='yw'
	
	if plat=='win':
		icon='-i res/icon.ico'
	elif plat=='osx':
		icon='-i res/icon.icns'
	else:
		icon='-i res/icon.png' # does this even work?
		
	# multiprocessing has issues with Windows one-file packages (see https://github.com/pyinstaller/pyinstaller/wiki/Recipe-Multiprocessing)
	if plat!='win':
		flags+='F'
	
	paths=' '.join('-p %s'%p for p in paths)
	hidden=' '.join('--hidden-import %s'%h for h in hidden)
	flags=' '.join('-%s'%f for f in flags)
	
	cmd='pyinstaller %s %s -n %s %s %s DicomBrowser/__main__.py'%(flags,icon,appname,paths,hidden)
	subprocess.check_call(cmd,shell=True)
	
	if plat=='osx':
		cmd='cd dist && hdiutil create -volname %(name)s -srcfolder %(name)s.app -ov -format UDZO -imagekey zlib-level=9 %(name)s.dmg'%{'name':appname}
		subprocess.check_call(cmd,shell=True)
	
	sys.exit(0)
	
setup(
	name = __appname__,
	version = __version__,
	packages=['DicomBrowser'],
	author='Eric Kerfoot',
	author_email="eric.kerfoot@kcl.ac.uk",
	url="http://github.com/ericspod/DicomBrowser",
	license="GPLv3",
	install_requires=['numpy','PyQt4','pydicom','pyqtgraph'],
	description='Lightweight portable DICOM viewer with interface for images and tags',
	keywords="dicom python medical imaging pydicom pyqtgraph",
	long_description='''
	This is a lightweight portable Dicom browser application written in Python. It allows Dicom directories to be loaded, 
	images and tag data viewed, and not much else aside. This is intended to be a cross-platform utility suitable for 
	previewing Dicom data rather than doing any sort of processing.
	'''
)
