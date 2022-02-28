
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

import os
import sys
from subprocess import check_call
from setuptools import setup, find_packages
from pkg_resources import parse_requirements

source_dir = os.path.abspath(os.path.dirname(__file__))

# read the version and other data from _version.py
with open(os.path.join(source_dir, "dicombrowser/_version.py")) as o:
    exec(o.read())
    
# read install requirements from requirements.txt
with open(os.path.join(source_dir, "requirements.txt")) as o:
    requirements = [str(r) for r in parse_requirements(o.read())]

long_description = """
This is a lightweight portable Dicom browser application written in Python. It allows Dicom directories to be loaded, 
images and tag data viewed, and not much else aside. This is intended to be a cross-platform utility suitable for 
previewing Dicom data rather than doing any sort of processing.
"""

if "generate" in sys.argv:  # generate resource file for PyQt5 only, quit at this point before setup
    check_call("pyrcc5 res/Resources.qrc > dicombrowser/resources_rc.py", shell=True)
else:
    setup(
        name=__appname__,
        version=__version__,
        packages=find_packages(),
        author=__author__,
        author_email=__author_email__,
        url="http://github.com/ericspod/DicomBrowser",
        license="GPLv3",
        description="Lightweight portable DICOM viewer with interface for images and tags",
        keywords="dicom python medical imaging pydicom pyqtgraph",
        long_description=long_description.strip(),
        entry_points={"console_scripts": ["dicombrowser = dicombrowser:mainargv"]},
        install_requires=requirements,
        python_requires='>=3.7',
    )
