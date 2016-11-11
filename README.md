# DicomBrowser

This is a lightweight portable Dicom browser application written in Python.
It allows Dicom directories to be loaded, images and tag data viewed, and not much else aside.
This is intended to be a cross-platform utility suitable for previewing Dicom data rather than doing any sort of processing.

## Running

DicomBrowser can be run directly as a script from the project's directory:

    python DicomBrowser/DicomBrowser.py
    
or as a module:

    python -m DicomBrowser
    
DicomBrowser requires **Python 2.7**, **PyQt4**, **numpy**, **pydicom** and **pyqtgraph**, the latter two are submodules of this project.
Ensure these packages are installed, in the case of **pydicom&& and **pyqtgraph** ensure the submodules are included in your clone.

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

