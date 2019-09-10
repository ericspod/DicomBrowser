
# DicomBrowser
# Copyright (C) 2016-8 Eric Kerfoot, King's College London, all rights reserved
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
import subprocess, sys, platform, glob, shutil
from DicomBrowser import __appname__, __version__, __author__

# determine platfrom
if platform.system().lower() == 'darwin':
    plat = 'osx'
elif platform.system().lower() == 'windows':
    plat = 'win'
else:
    plat = 'linux'

# determine PyQt version    
try:
    import PyQt5

    qtversion = 5
except:
    import PyQt4

    qtversion = 4

long_description = '''
This is a lightweight portable Dicom browser application written in Python. It allows Dicom directories to be loaded, 
images and tag data viewed, and not much else aside. This is intended to be a cross-platform utility suitable for 
previewing Dicom data rather than doing any sort of processing.
'''

if 'generate' in sys.argv:  # generate only, quit at this point before setup
    # generate resource file for PyQt4 or 5
    cmd = 'pyrcc%(ver)i res/Resources.qrc > DicomBrowser/Resources_rc%(ver)i.py'
    subprocess.check_call(cmd % {'ver': qtversion}, shell=True)

elif 'app' in sys.argv:
    sys.argv.remove('app')
    appname = '%s_%s' % (__appname__, __version__)
    icon = 'res/icon.icns' if platform.system().lower() == 'darwin' else 'res/icon.ico'
    paths = ['DicomBrowser', 'pydicom', 'pyqtgraph']
    hidden = ['Queue']
    flags = 'yw'

    if plat == 'win':
        icon = '-i res/icon.ico'
    elif plat == 'osx':
        icon = '-i res/icon.icns'
    else:
        icon = '-i res/icon.png'  # does this even work?

    # multiprocessing has issues with Windows one-file packages
    # (see https://github.com/pyinstaller/pyinstaller/wiki/Recipe-Multiprocessing)
    #    if plat!='win':
    #        flags+='F'

    paths = ' '.join('-p %s' % p for p in paths)
    hidden = ' '.join('--hidden-import %s' % h for h in hidden)
    flags = ' '.join('-%s' % f for f in flags)

    cmd = 'pyinstaller %s %s -n %s %s %s DicomBrowser/__main__.py'
    subprocess.check_call(cmd % (flags, icon, appname, paths, hidden), shell=True)

    if plat == 'osx':
        cmd = 'cd dist && hdiutil create -size 1000000k -volname %(name)s -srcfolder %(name)s.app -ov -format UDZO -imagekey zlib-level=9 %(name)s.dmg'
        subprocess.check_call(cmd % {'name': appname}, shell=True)
    elif plat == 'win':
        for f in glob.glob('dist/%s/mkl_*.dll' % appname):  # remove unnecessary MKL libraries
            shutil.rmtree(f,ignore_errors=True)
    else:
        shutil.rmtree('dist/%s/share/icons' % appname,ignore_errors=True)
        for f in ['libstdc++.so.6', 'libglib-2.0.so.0', 'libgobject-2.0.so.0', 'libgpg-error.so.0']:
            shutil.rmtree('dist/%s/%s' % (appname, f),ignore_errors=True)
else:
    setup(
        name=__appname__,
        version=__version__,
        packages=['DicomBrowser'],
        author=__author__,
        author_email="eric.kerfoot@kcl.ac.uk",
        url="http://github.com/ericspod/DicomBrowser",
        license="GPLv3",
        description='Lightweight portable DICOM viewer with interface for images and tags',
        keywords="dicom python medical imaging pydicom pyqtgraph",
        long_description=long_description.strip(),
        entry_points={'console_scripts': ['DicomBrowser = DicomBrowser:mainargv']},
        install_requires=['pyqtgraph', 'pydicom']
    )
