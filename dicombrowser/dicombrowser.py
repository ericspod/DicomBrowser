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
"""
DicomBrowser - simple lightweight Dicom browsing application. 
"""

import sys
import os
import threading
import re
from multiprocessing import freeze_support
from contextlib import closing
from collections import OrderedDict

from queue import Queue, Empty
from io import StringIO

import numpy as np
import pyqtgraph as pg

from PyQt5 import QtGui, QtCore, QtWidgets, uic
from PyQt5.QtCore import Qt, QStringListModel
from dicombrowser import resources_rc  # import resources manually since we have to do this to get the ui file

from ._version import __version__

from .dicom import load_dicom_dir, load_dicom_zip, SERIES_LIST_COLUMNS, TAG_TREE_COLUMNS
from .models import SeriesTableModel, TagItemModel


# Load the ui file from the resource, removing the "resources" tag so that uic doesn't try (and fail) to load resources.
# This allows loading the UI at runtime rather than generating a .py file with pyuic not cross-compatible with PyQt4/5.
with closing(QtCore.QFile(":/layout/DicomBrowserWin.ui")) as uiFile:
    if uiFile.open(QtCore.QFile.ReadOnly):
        ui = bytes(uiFile.readAll()).decode("utf-8")
        ui = re.sub("<resources>.*</resources>", "", ui, flags=re.DOTALL)  # get rid of the resources section in the XML
        Ui_DicomBrowserWin, _ = uic.loadUiType(StringIO(ui))  # create a local type definition


class DicomBrowser(QtWidgets.QMainWindow, Ui_DicomBrowserWin):
    """
    The window class for the app which implements the UI functionality and the directory loading thread. It 
    inherits from the type loaded from the .ui file in the resources. 
    """

    statusSignal = QtCore.pyqtSignal(str, int, int)  # signal for updating the status bar asynchronously
    updateSignal = QtCore.pyqtSignal()  # signal for updating the source list and series table

    def __init__(self, parent=None):
        super().__init__(parent)

        self.src_list = []  # list of source directories
        self.image_index = 0  # index of selected image
        self.series_map = OrderedDict()  # maps series table row tuples to DicomSeries object it was generated from
        self.series_columns = list(SERIES_LIST_COLUMNS)  # keywords for columns
        self.selected_row = -1  # selected series row
        self.last_dir = "."  # last loaded directory root
        self.filter_regex = ""  # regular expression to filter tags by

        # create the directory queue and loading thread objects
        self.src_queue = Queue()  # queue of directories to load
        self.load_dir_thread = threading.Thread(target=self._load_source_thread)
        self.load_dir_thread.daemon = True  # clean shutdown possible with daemon threads
        self.load_dir_thread.start()  # start the thread now, it will wait until something is put on self.srcQueue

        # setup ui
        self.setupUi(self)  # create UI elements based on the loaded .ui file
        self.setWindowTitle("DicomBrowser v%s (FOR RESEARCH ONLY)" % (__version__,))
        self.set_status("")

        # connect signals
        self.importDirButton.clicked.connect(self._open_dir_dialog)
        self.importZipButton.clicked.connect(self._open_zip_dialog)
        self.statusSignal.connect(self.set_status)
        self.updateSignal.connect(self._update_series_table)
        self.filterLine.textChanged.connect(self._set_filter_string)
        self.imageSlider.valueChanged.connect(self.set_series_image)
        self.seriesView.clicked.connect(self._series_table_clicked)

        # setup the list and table models
        self.src_model = QStringListModel()
        self.series_model = SeriesTableModel(self.series_columns)
        self.series_model.layoutChanged.connect(self._series_table_resize)
        self.tagModel = TagItemModel()

        # assign models to views
        self.sourceListView.setModel(self.src_model)
        self.seriesView.setModel(self.series_model)
        self.tagView.setModel(self.tagModel)

        # create the pyqtgraph object for viewing images
        self.image_view = pg.ImageView()
        layout = QtWidgets.QGridLayout(self.view2DGroup)
        layout.addWidget(self.image_view)

        # load the empty image placeholder into a ndarray
        qimg = QtGui.QImage(":/icons/noimage.png")
        bytedata = qimg.constBits().asstring(qimg.width() * qimg.height())
        self.noimg = np.ndarray((qimg.width(), qimg.height()), dtype=np.ubyte, buffer=bytedata)

        # override CTRL+C in the tag tree to copy a fuller set of tag data to the clipboard
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+c"), self.tagView).activated.connect(self._set_clipboard)

    def keyPressEvent(self, e):
        """Close the window if escape is pressed, otherwise do as inherited."""
        if e.key() == QtCore.Qt.Key_Escape:
            self.close()
        else:
            QtWidgets.QMainWindow.keyPressEvent(self, e)

    def show(self):
        """Calls the inherited show() method then sets the splitter positions."""
        QtWidgets.QMainWindow.show(self)
        self.listSplit.moveSplitter(120, 1)
        self.seriesSplit.moveSplitter(80, 1)
        self.viewMetaSplitter.moveSplitter(600, 1)

    def _load_source_thread(self):
        """
        This is run in a daemon thread and continually checks self.srcQueue for a queued directory or zip file to scan
        for Dicom files. It calls loadDicomDir() for a given directory or loadDicomZip() for a zip file and adds the
        results the self.srclist member.
        """
        while True:
            try:
                src = self.src_queue.get(True, 0.5)
                loader = load_dicom_dir if os.path.isdir(src) else load_dicom_zip
                series = loader(src, self.statusSignal.emit)

                if series and all(len(s.filenames) > 0 for s in series):
                    for s in series:
                        # sort series contents by filename
                        s.filenames, s.loadtags = zip(*sorted(zip(s.filenames, s.loadtags)))

                    self.src_list.append((src, series))

                self.updateSignal.emit()
            except Empty:
                pass

    def _open_dir_dialog(self):
        """Opens the open file dialog to choose a directory to scan for Dicoms."""
        rootdir = str(QtWidgets.QFileDialog.getExistingDirectory(self, "Choose Source Directory", self.last_dir))
        if rootdir:
            self.add_source(rootdir)

    def _open_zip_dialog(self):
        """Opens the open file dialog to choose a zip file to scan for Dicoms."""
        zipfile = QtWidgets.QFileDialog.getOpenFileName(self, "Choose Zip File", self.last_dir, "Zip Files (*.zip)")
        if zipfile[0]:
            self.add_source(zipfile[0])

    def _update_series_table(self):
        """
        Updates the self.seriesMap object from self.srclist, and refills the self.srcmodel object. This will refresh 
        the list of source directories and the table of available series.
        """
        self.series_map.clear()

        for _, series in self.src_list:  # add each series in each source into self.seriesMap
            for s in series:
                entry = s.get_tag_values(self.series_columns)
                self.series_map[entry] = s

        self.src_model.setStringList([s[0] for s in self.src_list])
        self.series_model.updateSeriesTable(self.series_map.keys())
        self.series_model.layoutChanged.emit()

    def _series_table_clicked(self, item):
        """Called when a series is clicked on, set the viewed image to be from the clicked series."""
        self.selected_row = item.row()
        self.set_series_image(self.imageSlider.value(), True)

    def _series_table_resize(self):
        """Resizes self.seriesView columns to contents, setting the last section to stretch."""
        self.seriesView.horizontalHeader().setStretchLastSection(False)
        self.seriesView.resizeColumnsToContents()
        self.seriesView.horizontalHeader().setStretchLastSection(True)

    def _set_filter_string(self, regex):
        """Set the filtering regex to be `regex'."""
        self.filter_regex = regex
        self._fill_tag_view()

    def _fill_tag_view(self):
        """Refill the Dicom tag view, this will rejig the columns and (unfortunately) reset column sorting."""
        series = self.get_selected_series()
        vpos = self.tagView.verticalScrollBar().value()
        self.tagModel.fill_tags(series.get_tag_object(self.image_index), TAG_TREE_COLUMNS, self.filter_regex)
        self.tagView.expandAll()
        self.tagView.resizeColumnToContents(0)
        self.tagView.verticalScrollBar().setValue(vpos)

    def _set_clipboard(self):
        """Set the clipboard to contain fuller tag data when CTRL+C is applied to a tag line in the tree."""

        def print_children(child, level, out):
            for r in range(child.rowCount()):
                print("", file=out)

                for c in range(child.columnCount()):
                    cc = child.child(r, c)

                    if cc is not None:
                        print(" " * level, cc.text(), file=out, end="")
                        if cc.hasChildren():
                            print_children(cc, level + 1, out)

        clipout = StringIO()
        items = [self.tagModel.itemFromIndex(i) for i in self.tagView.selectedIndexes()]
        print(" ".join(i.data() or i.text() for i in items if i), end="", file=clipout)

        if items[0].hasChildren():
            print_children(items[0], 1, clipout)

        QtWidgets.QApplication.clipboard().setText(clipout.getvalue())

    def get_selected_series(self):
        """Returns the DicomSeries object for the selected series, None if no series is selected."""
        if 0 <= self.selected_row < len(self.series_map):
            return self.series_map[self.series_model.getRow(self.selected_row)]

    def set_series_image(self, i, autoRange=False):
        """
        Set the view image to be that at index `i' of the selected series. The `autoRange' boolean value sets whether
        the data value range is reset or not when this is done. The tag table is also set to that of image `i'.
        """
        series = self.get_selected_series()
        if series:
            maxindex = len(series.filenames) - 1
            self.image_index = np.clip(i, 0, maxindex)
            img = series.get_pixel_data(self.image_index)  # image matrix
            interval = 1  # tick interval on the slider

            # choose a more sensible tick interval if there's a lot of images
            if maxindex >= 5000:
                interval = 100
            elif maxindex >= 500:
                interval = 10

            if img is None:  # if the image is None use the default "no image" object
                img = self.noimg
            # elif len(img.shape)==3: # multi-channel or multi-dimensional image, use average of dimensions
            #    img=np.mean(img,axis=2)

            self.image_view.setImage(img.T, autoRange=autoRange, autoLevels=self.autoLevelsCheck.isChecked())
            self._fill_tag_view()
            self.imageSlider.setTickInterval(interval)
            self.imageSlider.setMaximum(maxindex)
            self.numLabel.setText(str(self.image_index))
            self.view2DGroup.setTitle("2D View - " + os.path.basename(series.filenames[self.image_index]))
            self.view2DGroup.setToolTip(series.filenames[self.image_index])

    def set_status(self, msg, progress=0, progressmax=0):
        """
        Set the status bar with message `msg' with progress set to `progress' out of `progressmax', or hide the status 
        elements if `msg' is empty or None.
        """
        if not msg:
            progress = 0
            progressmax = 0

        self.statusText.setText(msg)
        self.statusText.setVisible(bool(msg))
        self.importDirButton.setVisible(not bool(msg))
        self.importZipButton.setVisible(not bool(msg))
        self.statusProgressBar.setVisible(progressmax > 0)
        self.statusProgressBar.setRange(0, progressmax)
        self.statusProgressBar.setValue(progress)

    def remove_source(self, index):
        """Remove the source directory at the given index."""
        self.src_list.pop(index)
        self.updateSignal.emit()

    def add_source(self, rootdir):
        """Add the given directory to the queue of directories to load and set the self.lastDir value to its parent."""
        self.src_queue.put(rootdir)
        self.last_dir = os.path.dirname(rootdir)


def main(args=[]):
    """
    Default main program which starts Qt based on the command line arguments `args`, sets the stylesheet if present,
    then creates the window object and shows it. The `args` command line arguments list is used to load given 
    directories or zip files. Returns the value of QApplication.exec_() for the created QApplication object.
    """
    app = QtWidgets.QApplication(args)
    app.setAttribute(Qt.AA_DontUseNativeMenuBar)  # in macOS, forces menubar to be in window
    app.setStyle("Plastique")

    # load the stylesheet included as a Qt resource
    with closing(QtCore.QFile(":/css/DefaultUIStyle.css")) as f:
        if f.open(QtCore.QFile.ReadOnly):
            app.setStyleSheet(bytes(f.readAll()).decode("UTF-8"))
        else:
            print("Failed to read %r" % f.fileName(), file=sys.stderr)

    browser = DicomBrowser()

    # add the directories passed as arguments to the directory queue to start loading
    for i in args[1:]:
        if os.path.exists(i):
            browser.add_source(i)

    browser.show()

    return app.exec()


def mainargv():
    """setuptools compatible entry point."""
    freeze_support()
    sys.exit(main(sys.argv))
