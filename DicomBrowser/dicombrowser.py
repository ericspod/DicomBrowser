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

import sys, os, threading, re
from multiprocessing import freeze_support
from contextlib import closing
from collections import OrderedDict

from queue import Queue, Empty
from io import StringIO

from PyQt5 import QtGui, QtCore, QtWidgets, uic
from PyQt5.QtCore import Qt, QStringListModel
from . import Resources_rc  # import resources manually since we have to do this to get the ui file


import numpy as np
import pyqtgraph as pg


from .__init__ import __version__

from .dicom import loadDicomDir, loadDicomZip, seriesListColumns, tagTreeColumns
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

    def __init__(self, args, parent=None):
        super().__init__(parent)

        self.srcList = []  # list of source directories
        self.imageIndex = 0  # index of selected image
        self.seriesMap = OrderedDict()  # maps series table row tuples to DicomSeries object it was generated from
        self.seriesColumns = list(seriesListColumns)  # keywords for columns
        self.selectedRow = -1  # selected series row
        self.lastDir = "."  # last loaded directory root
        self.filterRegex = ""  # regular expression to filter tags by

        # create the directory queue and loading thread objects
        self.srcQueue = Queue()  # queue of directories to load
        self.loadDirThread = threading.Thread(target=self._loadSourceThread)
        self.loadDirThread.daemon = True  # clean shutdown possible with daemon threads
        self.loadDirThread.start()  # start the thread now, it will wait until something is put on self.srcQueue

        # setup ui
        self.setupUi(self)  # create UI elements based on the loaded .ui file
        self.setWindowTitle("DicomBrowser v%s (FOR RESEARCH ONLY)" % (__version__,))
        self.setStatus("")

        # connect signals
        self.importDirButton.clicked.connect(self._openDirDialog)
        self.importZipButton.clicked.connect(self._openZipDialog)
        self.statusSignal.connect(self.setStatus)
        self.updateSignal.connect(self._updateSeriesTable)
        self.filterLine.textChanged.connect(self._setFilterString)
        self.imageSlider.valueChanged.connect(self.setSeriesImage)
        self.seriesView.clicked.connect(self._seriesTableClicked)

        # setup the list and table models
        self.srcModel = QStringListModel()
        self.seriesModel = SeriesTableModel(self.seriesColumns)
        self.seriesModel.layoutChanged.connect(self._seriesTableResize)
        self.tagModel = TagItemModel()

        # assign models to views
        self.sourceListView.setModel(self.srcModel)
        self.seriesView.setModel(self.seriesModel)
        self.tagView.setModel(self.tagModel)

        # create the pyqtgraph object for viewing images
        self.imageView = pg.ImageView()
        layout = QtGui.QGridLayout(self.view2DGroup)
        layout.addWidget(self.imageView)

        # load the empty image placeholder into a ndarray
        qimg = QtGui.QImage(":/icons/noimage.png")
        bytedata = qimg.constBits().asstring(qimg.width() * qimg.height())
        self.noimg = np.ndarray((qimg.width(), qimg.height()), dtype=np.ubyte, buffer=bytedata)

        # add the directories passed as arguments to the directory queue to start loading
        for i in args[1:]:
            if os.path.exists(i):
                self.addSource(i)

        # override CTRL+C in the tag tree to copy a fuller set of tag data to the clipboard
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+c"), self.tagView).activated.connect(self._setClipboard)

    def keyPressEvent(self, e):
        """Close the window if escape is pressed, otherwise do as inherited."""
        if e.key() == Qt.Key_Escape:
            self.close()
        else:
            QtGui.QMainWindow.keyPressEvent(self, e)

    def show(self):
        """Calls the inherited show() method then sets the splitter positions."""
        QtGui.QMainWindow.show(self)
        self.listSplit.moveSplitter(120, 1)
        self.seriesSplit.moveSplitter(80, 1)
        self.viewMetaSplitter.moveSplitter(600, 1)

    def _loadSourceThread(self):
        """
        This is run in a daemon thread and continually checks self.srcQueue for a queued directory or zip file to scan
        for Dicom files. It calls loadDicomDir() for a given directory or loadDicomZip() for a zip file and adds the
        results the self.srclist member.
        """
        while True:
            try:
                src = self.srcQueue.get(True, 0.5)
                loader = loadDicomDir if os.path.isdir(src) else loadDicomZip
                series = loader(src, self.statusSignal.emit)

                if series and all(len(s.filenames) > 0 for s in series):
                    for s in series:
                        # sort series contents by filename
                        s.filenames, s.loadtags = zip(*sorted(zip(s.filenames, s.loadtags)))

                    self.srcList.append((src, series))

                self.updateSignal.emit()
            except Empty:
                pass

    def _openDirDialog(self):
        """Opens the open file dialog to choose a directory to scan for Dicoms."""
        rootdir = str(QtGui.QFileDialog.getExistingDirectory(self, "Choose Source Directory", self.lastDir))
        if rootdir:
            self.addSource(rootdir)

    def _openZipDialog(self):
        """Opens the open file dialog to choose a zip file to scan for Dicoms."""
        zipfile = QtGui.QFileDialog.getOpenFileName(self, "Choose Zip File", self.lastDir, "Zip Files (*.zip)")
        if zipfile[0]:
            self.addSource(zipfile[0])

    def _updateSeriesTable(self):
        """
        Updates the self.seriesMap object from self.srclist, and refills the self.srcmodel object. This will refresh 
        the list of source directories and the table of available series.
        """
        self.seriesMap.clear()

        for _, series in self.srcList:  # add each series in each source into self.seriesMap
            for s in series:
                entry = s.getTagValues(self.seriesColumns)
                self.seriesMap[entry] = s

        self.srcModel.setStringList([s[0] for s in self.srcList])
        self.seriesModel.updateSeriesTable(self.seriesMap.keys())
        self.seriesModel.layoutChanged.emit()

    def _seriesTableClicked(self, item):
        """Called when a series is clicked on, set the viewed image to be from the clicked series."""
        self.selectedRow = item.row()
        self.setSeriesImage(self.imageSlider.value(), True)

    def _seriesTableResize(self):
        """Resizes self.seriesView columns to contents, setting the last section to stretch."""
        self.seriesView.horizontalHeader().setStretchLastSection(False)
        self.seriesView.resizeColumnsToContents()
        self.seriesView.horizontalHeader().setStretchLastSection(True)

    def _setFilterString(self, regex):
        """Set the filtering regex to be `regex'."""
        self.filterRegex = regex
        self._fillTagView()

    def _fillTagView(self):
        """Refill the Dicom tag view, this will rejig the columns and (unfortunately) reset column sorting."""
        series = self.getSelectedSeries()
        vpos = self.tagView.verticalScrollBar().value()
        self.tagModel.fillTags(series.getTagObject(self.imageIndex), tagTreeColumns, self.filterRegex)
        self.tagView.expandAll()
        self.tagView.resizeColumnToContents(0)
        self.tagView.verticalScrollBar().setValue(vpos)

    def _setClipboard(self):
        """Set the clipboard to contain fuller tag data when CTRL+C is applied to a tag line in the tree."""

        def printChildren(child, level, out):
            for r in range(child.rowCount()):
                print("", file=out)

                for c in range(child.columnCount()):
                    cc = child.child(r, c)

                    if cc is not None:
                        print(" " * level, cc.text(), file=out, end="")
                        if cc.hasChildren():
                            printChildren(cc, level + 1, out)

        clipout = StringIO()
        items = [self.tagModel.itemFromIndex(i) for i in self.tagView.selectedIndexes()]
        print(" ".join(i.data() or i.text() for i in items if i), end="", file=clipout)

        if items[0].hasChildren():
            printChildren(items[0], 1, clipout)

        QtGui.QApplication.clipboard().setText(clipout.getvalue())

    def getSelectedSeries(self):
        """Returns the DicomSeries object for the selected series, None if no series is selected."""
        if 0 <= self.selectedRow < len(self.seriesMap):
            return self.seriesMap[self.seriesModel.getRow(self.selectedRow)]

    def setSeriesImage(self, i, autoRange=False):
        """
        Set the view image to be that at index `i' of the selected series. The `autoRange' boolean value sets whether
        the data value range is reset or not when this is done. The tag table is also set to that of image `i'.
        """
        series = self.getSelectedSeries()
        if series:
            maxindex = len(series.filenames) - 1
            self.imageIndex = np.clip(i, 0, maxindex)
            img = series.getPixelData(self.imageIndex)  # image matrix
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

            self.imageView.setImage(img.T, autoRange=autoRange, autoLevels=self.autoLevelsCheck.isChecked())
            self._fillTagView()
            self.imageSlider.setTickInterval(interval)
            self.imageSlider.setMaximum(maxindex)
            self.numLabel.setText(str(self.imageIndex))
            self.view2DGroup.setTitle("2D View - " + os.path.basename(series.filenames[self.imageIndex]))
            self.view2DGroup.setToolTip(series.filenames[self.imageIndex])

    def setStatus(self, msg, progress=0, progressmax=0):
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

    def removeSource(self, index):
        """Remove the source directory at the given index."""
        self.srcList.pop(index)
        self.updateSignal.emit()

    def addSource(self, rootdir):
        """Add the given directory to the queue of directories to load and set the self.lastDir value to its parent."""
        self.srcQueue.put(rootdir)
        self.lastDir = os.path.dirname(rootdir)


def main(args=[], qapp=None):
    """
    Default main program which starts Qt based on the command line arguments `args', sets the stylesheet if present,
    then creates the window object and shows it. The `args' command line arguments list is passed to the window object
    to pick up on specified directories. The `qapp' object would be the QApplication object if it's created elsewhere,
    otherwise it's created here. Returns the value of QApplication.exec_() if this object was created here otherwise 0.
    """
    if qapp is None:
        app = QtWidgets.QApplication(args)
        app.setAttribute(Qt.AA_DontUseNativeMenuBar)  # in OSX, forces menubar to be in window
        app.setStyle("Plastique")

        # load the stylesheet included as a Qt resource
        with closing(QtCore.QFile(":/css/DefaultUIStyle.css")) as f:
            if f.open(QtCore.QFile.ReadOnly):
                app.setStyleSheet(bytes(f.readAll()).decode("UTF-8"))
            else:
                print("Failed to read %r" % f.fileName())

    browser = DicomBrowser(args)
    browser.show()

    return 0 if qapp is not None else app.exec_()


def mainargv():
    """setuptools compatible entry point."""
    freeze_support()
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    mainargv()
