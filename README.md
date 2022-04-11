# DicomBrowser

This is a lightweight portable Dicom browser application written in Python.
It allows Dicom directories to be loaded, images and tag data viewed, and not much else aside.
This is intended to be a cross-platform utility suitable for previewing Dicom data rather than doing any sort of processing.

## Installation

DicomBrowser requires **Python 3.7+**, **PyQt5**, **numpy**, **pydicom** and **pyqtgraph**, the latter two are submodules of this project.
Ensure these packages are installed, in the case of **pydicom** and **pyqtgraph** ensure the submodules are included in your clone:

    git clone --recursive https://github.com/ericspod/DicomBrowser.git

DicomBrowser can be installed using the **setup.py** script (although this isn't necessary, see below):

    python setup.py install

This will generate the necessary files for the UI, install the module, and create a script to run the application from the command line called *DicomBrowser*, but will not install other needed packages. 
Ensure the pydicom and pyqtgraph submodules have been checked out and then run the above command in each to install them.

PyQt5 must be acquired through your package manager or through its website. Numpy can be installed through your package manager, the website, or **pip**:

    pip install numpy

Generating the packaged executables requires **pyinstaller**, clone and install from https://github.com/pyinstaller/pyinstaller if you want to generate these yourself.

## Running

DicomBrowser can be run directly as a module from the project's directory:

    python -m DicomBrowser

The releases also include pre-built Windows and OSX standalone applications, allowing you to download these and run the
application without installing Python or the necessary packages.

Directories provided as command line arguments will be imported, any other arguments or files will be ignored.


## Docker

A Dockerfile is included, to build the image with the following command:
```
docker build . --tag dicombrowser:latest
```
and then to run the created image "dicombrowser" on a X Windows host use a command like the following:
```
docker run -ti --rm --net=host --env="DISPLAY" --volume="$HOME/.Xauthority:/root/.Xauthority:rw" dicombrowser
```

Running `xhost +local:docker` may be necessary to add permissions and allow the container to access the X network ports.

## Authors

DicomBrowser is developed and maintained by Eric Kerfoot <eric.kerfoot@kcl.ac.uk>.

## License

Copyright (C) 2016-9 Eric Kerfoot, King's College London, all rights reserved

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

