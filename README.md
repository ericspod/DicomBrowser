# DicomBrowser

This is a lightweight portable Dicom browser application written in Python.
It allows Dicom directories to be loaded, images and tag data viewed, and not much else aside.
This is intended to be a cross-platform utility suitable for previewing Dicom data rather than doing any sort of processing.

## Installation

DicomBrowser requires **Python 2.7**, **PyQt4**, **numpy**, **pydicom** and **pyqtgraph**, the latter two are submodules of this project.
Ensure these packages are installed, in the case of **pydicom** and **pyqtgraph** ensure the submodules are included in your clone:

    git clone --recursive https://github.com/ericspod/DicomBrowser.git

DicomBrowser can be installed using the **setup.py** script:

    python setup.py install

This will generate the necessary files for the UI and install the module but will not install other needed packages. 
Ensure the pydicom and pyqtgraph submodules have been checked out and then run the above command in each to install them.

PyQt4 must be acquired through your package manager or through its website. Numpy can be installed through your package manager, the website, or **pip**:

    pip install numpy

Generating the packaged executables requires **pyinstaller**, clone and install from https://github.com/pyinstaller/pyinstaller if you want to generate these yourself.

## Running

DicomBrowser can be run directly as a script from the project's directory:

    python DicomBrowser/DicomBrowser.py
    
or as a module:

    python -m DicomBrowser

The releases also include pre-built Windows and OSX standalone applications, allowing you to download these and run the
application without installing Python or the necessary packages.

## Authors

DicomBrowser is developed and maintained by Eric Kerfoot <eric.kerfoot@kcl.ac.uk>.

## License

Copyright (C) 2016 Eric Kerfoot, King's College London, all rights reserved

This file is part of DicomBrowser.

DicomBrowser is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

DicomBrowser is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with this program (LICENSE.txt).  If not, see <http://www.gnu.org/licenses/>

