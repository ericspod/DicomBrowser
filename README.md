# DicomBrowser

This is a lightweight portable Dicom browser application written in Python.
It allows Dicom directories to be loaded, images and tag data viewed, and not much else aside.
This is intended to be a cross-platform utility suitable for previewing Dicom data rather than doing any sort of processing.

## Installation

DicomBrowser requires **Python 3.7+**, **PyQt5**, **numpy**, **pydicom** and **pyqtgraph**, and optionally the libraries for pydicom used to load JPEG data.

Installation through **pip**:

    pip install dicombrowser

Installation from repo:

    git clone https://github.com/ericspod/DicomBrowser.git
    cd DicomBrowser
    pip install .

This will create the entry point **dicombrowser** which accepts DICOM directories or zip files containing them:

    dicombrowser MAGIX.zip
    
DicomBrowser can be run directly as a module from the repo:

    python -m dicombrowser

## Docker

A Dockerfile is included, to build the image with the following command:

    docker build . -t dicombrowser:latest

and then to run the created image "dicombrowser" on a X Windows host use a command like the following:

    docker run -ti --rm --net=host -e DISPLAY -v "$HOME/.Xauthority:/root/.Xauthority:rw" dicombrowser


Running `xhost +local:docker` may be necessary to add permissions and allow the container to access the X network ports.

## Authors

DicomBrowser is developed and maintained by Eric Kerfoot <eric.kerfoot@kcl.ac.uk>.

## License

Copyright (C) 2016-22 Eric Kerfoot, King's College London, all rights reserved

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

