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
'''
DicomBrowser - simple lightweight Dicom browsing application. 
'''

from __future__ import print_function
import sys, os, threading, re, zipfile
from operator import itemgetter
from multiprocessing import Pool, Manager, cpu_count, freeze_support
from contextlib import closing
from collections import OrderedDict
from io import BytesIO

try:  # Python 2 and 3 support
    from Queue import Queue, Empty
    from StringIO import StringIO
except ImportError:
    from queue import Queue, Empty
    from io import StringIO

try:  # PyQt4 and 5 support
    from PyQt5 import QtGui, QtCore, uic
    from PyQt5.QtCore import Qt, QStringListModel
    from . import Resources_rc5  # import resources manually since we have to do this to get the ui file
except ImportError:
    from PyQt4 import QtGui, QtCore, uic
    from PyQt4.QtCore import Qt
    from PyQt4.QtGui import QStringListModel
    from . import Resources_rc4  # import resources manually since we have to do this to get the ui file

scriptdir = os.path.dirname(os.path.abspath(__file__))  # path of the current file

# this allows the script to be run directly from the repository without having to install pydicom or pyqtgraph
if os.path.isdir(scriptdir + '/../pydicom'):
    sys.path.append(scriptdir + '/../pydicom')
    sys.path.append(scriptdir + '/../pyqtgraph')

import numpy as np
import pyqtgraph as pg
from pydicom import dicomio, datadict, errors

from .__init__ import __version__

# Load the ui file from the resource, removing the "resources" tag so that uic doesn't try (and fail) to load resources.
# This allows loading the UI at runtime rather than generating a .py file with pyuic not cross-compatible with PyQt4/5.
with closing(QtCore.QFile(':/layout/DicomBrowserWin.ui')) as uiFile:
    if uiFile.open(QtCore.QFile.ReadOnly):
        ui = bytes(uiFile.readAll()).decode('utf-8')
        ui = re.sub('<resources>.*</resources>', '', ui, flags=re.DOTALL)  # get rid of the resources section in the XML
        Ui_DicomBrowserWin, _ = uic.loadUiType(StringIO(ui))  # create a local type definition

# tag names of default columns in the series list, this can be changed to pull out different tag names for columns
seriesListColumns = ('NumImages', 'SeriesNumber', 'PatientName', 'SeriesInstanceUID', 'SeriesDescription')

# names of columns in tag tree, this shouldn't ever change
tagTreeColumns = ('Name', 'Tag', 'Value')

# list of tags to initially load when a directory is scanned, loading only these speeds up scanning immensely
loadTags = ('SeriesInstanceUID', 'TriggerTime', 'PatientName', 'SeriesDescription', 'SeriesNumber')

# keyword/full name pairs for extra properties not represented as Dicom tags
extraKeywords = {
    'NumImages': '# Images',
    'TimestepSpec': 'Timestep Info',
    'StartTime': 'Start Time',
    'NumTimesteps': '# Timesteps',
    'TimeInterval': 'Time Interval'
}

# maps keywords to their full names
keywordNameMap = {v[4]: v[2] for v in datadict.DicomDictionary.values()}
keywordNameMap.update(extraKeywords)

fullNameMap = {v: k for k, v in keywordNameMap.items()}  # maps full names to keywords


def fillTagModel(model, dcm, regex=None, maxValueSize=256):
    '''Fill a QStandardItemModel object `model' with a tree derived from tags in `dcm', filtering by pattern `regex'.'''
    try:
        regex = re.compile(str(regex), re.DOTALL)
    except:
        regex = ''  # no regex or bad pattern

    def _datasetToItem(parent, d):
        '''Add every element in `d' to the QStandardItem object `parent', this will be recursive for list elements.'''
        for elem in d:
            value = _elemToValue(elem)
            tag = '(%04x, %04x)' % (elem.tag.group, elem.tag.elem)
            parent1 = QtGui.QStandardItem(str(elem.name))
            tagitem = QtGui.QStandardItem(tag)

            if isinstance(value, str):
                origvalue = value

                if len(value) > maxValueSize:
                    origvalue = repr(value)
                    value = value[:maxValueSize] + '...'

                try:
                    value = value.decode('ascii')
                    if '\n' in value or '\r' in value:  # multiline text data should be shown as repr
                        value = repr(value)
                except:
                    value = repr(value)

                if not regex or re.search(regex, str(elem.name) + tag + value) is not None:
                    item = QtGui.QStandardItem(value)
                    # original value is stored directly or as repr() form for tag value item, used later when copying
                    item.setData(origvalue)

                    parent.appendRow([parent1, tagitem, item])

            elif value is not None and len(value) > 0:
                parent.appendRow([parent1, tagitem])
                for v in value:
                    parent1.appendRow(v)

    def _elemToValue(elem):
        '''Return the value in `elem', which will be a string or a list of QStandardItem objects if elem.VR=='SQ'.'''
        value = None
        if elem.VR == 'SQ':
            value = []

            for i, item in enumerate(elem):
                parent1 = QtGui.QStandardItem('%s %i' % (elem.name, i))
                _datasetToItem(parent1, item)

                if not regex or parent1.hasChildren():  # discard sequences whose children have been filtered out
                    value.append(parent1)

        elif elem.name != 'Pixel Data':
            value = str(elem.value)

        return value

    tparent = QtGui.QStandardItem('Tags')  # create a parent node every tag is a child of, used for copying all tag data
    model.appendRow([tparent])
    _datasetToItem(tparent, dcm)
    

def loadDicomFiles(filenames,queue):
    '''Load the Dicom files `filenames' and put an abbreviated tag->value map for each onto `queue'.'''
    for filename in filenames:
        try:
            dcm=dicomio.read_file(filename,stop_before_pixels=True)
            tags={t:dcm.get(t) for t in loadTags if t in dcm}
            queue.put((filename,tags))
        except errors.InvalidDicomError:
            pass


def loadDicomDir(rootdir, statusfunc=lambda s, c, n: None, numprocs=None):
    '''
    Load all the Dicom files from `rootdir' using `numprocs' number of processes. This will attempt to load each file
    found in `rootdir' and store from each file the tags defined in loadTags. The filenames and the loaded tags for
    Dicom files are stored in a DicomSeries object representing the acquisition series each file belongs to. The 
    `statusfunc' callback is used to indicate loading status, taking as arguments a status string, count of loaded 
    objects, and the total number to load. A status string of '' indicates loading is done. The default value causes 
    no status indication to be made. Return value is a sequence of DicomSeries objects in no particular order.
    '''
    allfiles = []
    for root, _, files in os.walk(rootdir):
        allfiles += [os.path.join(root, f) for f in files if f.lower() != 'dicomdir']

    numprocs = numprocs or cpu_count()
    m = Manager()
    queue = m.Queue()
    numfiles = len(allfiles)
    res = []
    series = {}
    count = 0

    if not numfiles:
        return []

    with closing(Pool(processes = numprocs)) as pool:
        for filesec in np.array_split(allfiles, numprocs):
            res.append(pool.apply_async(loadDicomFiles, (filesec, queue)))

        # loop so long as any process is busy or there are files on the queue to process
        while any(not r.ready() for r in res) or not queue.empty():
            try:
                filename, dcm = queue.get(False)
                seriesid = dcm.get('SeriesInstanceUID', '???')
                if seriesid not in series:
                    series[seriesid] = DicomSeries(seriesid, rootdir)

                series[seriesid].addFile(filename, dcm)
            except Empty:  # from queue.get(), keep trying so long as the loop condition is true
                pass

            count += 1
            # update status only 100 times, doing it too frequently really slows things down
            if numfiles < 100 or count % (numfiles // 100) == 0:
                statusfunc('Loading DICOM files', count, numfiles)

    statusfunc('', 0, 0)
    return list(series.values())


def loadDicomZip(filename, statusfunc=lambda s, c, n: None):
    '''
    Load Dicom images from given zip file `filename'. This uses the status callback `statusfunc' like loadDicomDir().
    Loaded files will have their pixel data thus avoiding the need to reload the zip file when an image is viewed but is
    at the expense of load time and memory. Return value is a sequence of DicomSeries objects in no particular order.
    '''
    series = {}
    count = 0

    with zipfile.ZipFile(filename) as z:
        names = z.namelist()
        numfiles = len(names)
        for n in names:
            nfilename = '%s?%s' % (filename, n)
            s = BytesIO(z.read(n))
            try:
                dcm = dicomio.read_file(s)
            except:
                pass  # ignore files which aren't Dicom files
            else:
                seriesid = dcm.get('SeriesInstanceUID', '???')

                if seriesid not in series:
                    series[seriesid] = DicomSeries(seriesid, nfilename)

                # need to load image data now since we don't want to reload the zip file later when an image is viewed
                try:  # attempt to create the image matrix, store None if this doesn't work
                    rslope = float(dcm.get('RescaleSlope', 1) or 1)
                    rinter = float(dcm.get('RescaleIntercept', 0) or 0)
                    img = dcm.pixel_array * rslope + rinter
                except:
                    img = None

                s = series[seriesid]
                s.addFile(nfilename, dcm)
                s.tagcache[len(s.filenames) - 1] = dcm
                s.imgcache[len(s.filenames) - 1] = img

            count += 1
            # update status only 100 times, doing it too frequently really slows things down
            if numfiles < 100 or count % (numfiles // 100) == 0:
                statusfunc('Loading DICOM files', count, numfiles)

    statusfunc('', 0, 0)

    return list(series.values())


class DicomSeries(object):
    '''
    This type represents a Dicom series as a list of Dicom files sharing a series UID. The assumption is that the images
    of a series were captured together and so will always have a number of fields in common, such as patient name, so
    Dicoms should be organized by series. This type will also cache loaded Dicom tags and images
    '''

    def __init__(self, seriesID, rootdir):
        self.seriesID = seriesID  # ID of the series or ???
        self.rootdir = rootdir  # directory Dicoms were loaded from, files for this series may be in subdirectories
        self.filenames = []  # list of filenames for the Dicom associated with this series
        self.loadtags = []  # loaded abbreviated tag->(name,value) maps, 1 for each of self.filenames
        self.imgcache = {}  # image data cache, mapping index in self.filenames to arrays or None for non-images files
        self.tagcache = {}  # tag values cache, mapping index in self.filenames to OrderedDict of tag->(name,value) maps

    def addFile(self, filename, loadtag):
        '''Add a filename and abbreviated tag map to the series.'''
        self.filenames.append(filename)
        self.loadtags.append(loadtag)

    def getTagObject(self, index):
        '''Get the object storing tag information from Dicom file at the given index.'''
        if index not in self.tagcache:
            dcm = dicomio.read_file(self.filenames[index], stop_before_pixels=True)
            self.tagcache[index] = dcm

        return self.tagcache[index]

    def getExtraTagValues(self):
        '''Return the extra tag values calculated from the series tag info stored in self.filenames.'''
        start, interval, numtimes = self.getTimestepSpec()
        extravals = {
            'NumImages': len(self.filenames),
            'TimestepSpec': 'start: %i, interval: %i, # Steps: %i' % (start, interval, numtimes),
            'StartTime': start,
            'NumTimesteps': numtimes,
            'TimeInterval': interval
        }

        return extravals

    def getTagValues(self, names, index=0):
        '''Get the tag values for tag names listed in `names' for image at the given index.'''
        if not self.filenames:
            return ()

        dcm = self.getTagObject(index)
        extravals = self.getExtraTagValues()

        # TODO: kludge? More general solution of telling series apart
        # dcm.SeriesDescription=dcm.get('SeriesDescription',dcm.get('SeriesInstanceUID','???'))

        return tuple(str(dcm.get(n, extravals.get(n, ''))) for n in names)

    def getPixelData(self, index):
        '''Get the pixel data array for file at position `index` in self.filenames, or None if no pixel data.'''
        if index not in self.imgcache:
            try:
                dcm = dicomio.read_file(self.filenames[index])
                rslope = float(dcm.get('RescaleSlope', 1) or 1)
                rinter = float(dcm.get('RescaleIntercept', 0) or 0)
                img = dcm.pixel_array * rslope + rinter
            except:
                img = None  # exceptions indicate that the pixel data doesn't exist or isn't readable so ignore

            self.imgcache[index] = img

        return self.imgcache[index]

    def addSeries(self, series):
        '''Add every loaded dcm file from DicomSeries object `series` into this series.'''
        for f, loadtag in zip(series.filenames, series.loadtags):
            self.addFile(f, loadtag)

    def getTimestepSpec(self, tag='TriggerTime'):
        '''Returns (start time, interval, num timesteps) triple.'''
        times = sorted(set(int(loadtag.get(tag, 0)) for loadtag in self.loadtags))

        if not times or times == [0]:
            return 0.0, 0.0, 0.0
        else:
            if len(times) == 1:
                times = times * 2

            avgspan = np.average([b - a for a, b in zip(times, times[1:])])
            return times[0], avgspan, len(times)


class SeriesTableModel(QtCore.QAbstractTableModel):
    '''This manages the list of series with a sorting feature.'''

    def __init__(self, seriesColumns, parent=None):
        QtCore.QAbstractTableModel.__init__(self, parent)
        self.seriesTable = []
        self.seriesColumns = seriesColumns
        self.sortCol = 0
        self.sortOrder = Qt.AscendingOrder

    def rowCount(self, parent):
        return len(self.seriesTable)

    def columnCount(self, parent):
        return len(self.seriesTable[0]) if self.seriesTable else 0

    def sort(self, column, order):
        self.layoutAboutToBeChanged.emit()
        self.sortCol = column
        self.sortOrder = order

        self.seriesTable.sort(key=itemgetter(column), reverse=order == Qt.DescendingOrder)
        self.layoutChanged.emit()

    def updateSeriesTable(self, seriesTable):
        self.seriesTable = list(seriesTable)
        self.sort(self.sortCol, self.sortOrder)  # sort using existing parameters

    def getRow(self, i):
        return self.seriesTable[i]

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return keywordNameMap[self.seriesColumns[section]]

    def data(self, index, role):
        if index.isValid() and role == Qt.DisplayRole:
            return str(self.seriesTable[index.row()][index.column()])


class DicomBrowser(QtGui.QMainWindow, Ui_DicomBrowserWin):
    '''
    The window class for the app which implements the UI functionality and the directory loading thread. It 
    inherits from the type loaded from the .ui file in the resources. 
    '''
    statusSignal = QtCore.pyqtSignal(str, int, int)  # signal for updating the status bar asynchronously
    updateSignal = QtCore.pyqtSignal()  # signal for updating the source list and series table

    def __init__(self, args, parent=None):
        QtGui.QMainWindow.__init__(self, parent)

        self.srcList = []  # list of source directories
        self.imageIndex = 0  # index of selected image
        self.seriesMap = OrderedDict()  # maps series table row tuples to DicomSeries object it was generated from
        self.seriesColumns = list(seriesListColumns)  # keywords for columns
        self.selectedRow = -1  # selected series row
        self.lastDir = '.'  # last loaded directory root
        self.filterRegex = ''  # regular expression to filter tags by

        # create the directory queue and loading thread objects
        self.srcQueue = Queue()  # queue of directories to load
        self.loadDirThread = threading.Thread(target=self._loadSourceThread)
        self.loadDirThread.daemon = True  # clean shutdown possible with daemon threads
        self.loadDirThread.start()  # start the thread now, it will wait until something is put on self.srcQueue

        # setup ui
        self.setupUi(self)  # create UI elements based on the loaded .ui file
        self.setWindowTitle('DicomBrowser v%s (FOR RESEARCH ONLY)' % (__version__,))
        self.setStatus('')

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
        self.tagModel = QtGui.QStandardItemModel()

        # assign models to views
        self.sourceListView.setModel(self.srcModel)
        self.seriesView.setModel(self.seriesModel)
        self.tagView.setModel(self.tagModel)

        # create the pyqtgraph object for viewing images
        self.imageView = pg.ImageView()
        layout = QtGui.QGridLayout(self.view2DGroup)
        layout.addWidget(self.imageView)

        # load the empty image placeholder into a ndarray
        qimg = QtGui.QImage(':/icons/noimage.png')
        bytedata = qimg.constBits().asstring(qimg.width() * qimg.height())
        self.noimg = np.ndarray((qimg.width(), qimg.height()), dtype=np.ubyte, buffer=bytedata)

        # add the directories passed as arguments to the directory queue to start loading
        for i in args[1:]:
            if os.path.exists(i):
                self.addSource(i)

        # override CTRL+C in the tag tree to copy a fuller set of tag data to the clipboard
        QtGui.QShortcut(QtGui.QKeySequence('Ctrl+c'), self.tagView).activated.connect(self._setClipboard)

    def keyPressEvent(self, e):
        '''Close the window if escape is pressed, otherwise do as inherited.'''
        if e.key() == Qt.Key_Escape:
            self.close()
        else:
            QtGui.QMainWindow.keyPressEvent(self, e)

    def show(self):
        '''Calls the inherited show() method then sets the splitter positions.'''
        QtGui.QMainWindow.show(self)
        self.listSplit.moveSplitter(120, 1)
        self.seriesSplit.moveSplitter(80, 1)
        self.viewMetaSplitter.moveSplitter(600, 1)

    def _loadSourceThread(self):
        '''
        This is run in a daemon thread and continually checks self.srcQueue for a queued directory or zip file to scan
        for Dicom files. It calls loadDicomDir() for a given directory or loadDicomZip() for a zip file and adds the
        results the self.srclist member.
        '''
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
        '''Opens the open file dialog to choose a directory to scan for Dicoms.'''
        rootdir = str(QtGui.QFileDialog.getExistingDirectory(self, 'Choose Source Directory', self.lastDir))
        if rootdir:
            self.addSource(rootdir)

    def _openZipDialog(self):
        '''Opens the open file dialog to choose a zip file to scan for Dicoms.'''
        zipfile = QtGui.QFileDialog.getOpenFileName(self, 'Choose Zip File', self.lastDir, 'Zip Files (*.zip)')
        if zipfile[0]:
            self.addSource(zipfile[0])

    def _updateSeriesTable(self):
        '''
        Updates the self.seriesMap object from self.srclist, and refills the self.srcmodel object. This will refresh 
        the list of source directories and the table of available series.
        '''
        self.seriesMap.clear()

        for _, series in self.srcList:  # add each series in each source into self.seriesMap
            for s in series:
                entry = s.getTagValues(self.seriesColumns)
                self.seriesMap[entry] = s

        self.srcModel.setStringList([s[0] for s in self.srcList])
        self.seriesModel.updateSeriesTable(self.seriesMap.keys())
        self.seriesModel.layoutChanged.emit()

    def _seriesTableClicked(self, item):
        '''Called when a series is clicked on, set the viewed image to be from the clicked series.'''
        self.selectedRow = item.row()
        self.setSeriesImage(self.imageSlider.value(), True)

    def _seriesTableResize(self):
        '''Resizes self.seriesView columns to contents, setting the last section to stretch.'''
        self.seriesView.horizontalHeader().setStretchLastSection(False)
        self.seriesView.resizeColumnsToContents()
        self.seriesView.horizontalHeader().setStretchLastSection(True)

    def _setFilterString(self, regex):
        '''Set the filtering regex to be `regex'.'''
        self.filterRegex = regex
        self._fillTagView()

    def _fillTagView(self):
        '''Refill the Dicom tag view, this will rejig the columns and (unfortunately) reset column sorting.'''
        series = self.getSelectedSeries()
        vpos = self.tagView.verticalScrollBar().value()
        self.tagModel.clear()
        self.tagModel.setHorizontalHeaderLabels(tagTreeColumns)
        fillTagModel(self.tagModel, series.getTagObject(self.imageIndex), self.filterRegex)
        self.tagView.expandAll()
        self.tagView.resizeColumnToContents(0)
        self.tagView.verticalScrollBar().setValue(vpos)

    def _setClipboard(self):
        '''Set the clipboard to contain fuller tag data when CTRL+C is applied to a tag line in the tree.'''

        def printChildren(child, level, out):
            for r in range(child.rowCount()):
                print('', file=out)

                for c in range(child.columnCount()):
                    cc = child.child(r, c)

                    if cc is not None:
                        print(' ' * level, cc.text(), file=out, end='')
                        if cc.hasChildren():
                            printChildren(cc, level + 1, out)

        clipout = StringIO()
        items = [self.tagModel.itemFromIndex(i) for i in self.tagView.selectedIndexes()]
        print(' '.join(i.data() or i.text() for i in items if i), end='', file=clipout)

        if items[0].hasChildren():
            printChildren(items[0], 1, clipout)

        QtGui.QApplication.clipboard().setText(clipout.getvalue())

    def getSelectedSeries(self):
        '''Returns the DicomSeries object for the selected series, None if no series is selected.'''
        if 0 <= self.selectedRow < len(self.seriesMap):
            return self.seriesMap[self.seriesModel.getRow(self.selectedRow)]

    def setSeriesImage(self, i, autoRange=False):
        '''
        Set the view image to be that at index `i' of the selected series. The `autoRange' boolean value sets whether
        the data value range is reset or not when this is done. The tag table is also set to that of image `i'.
        '''
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
            self.view2DGroup.setTitle('2D View - ' + os.path.basename(series.filenames[self.imageIndex]))
            self.view2DGroup.setToolTip(series.filenames[self.imageIndex])

    def setStatus(self, msg, progress=0, progressmax=0):
        '''
        Set the status bar with message `msg' with progress set to `progress' out of `progressmax', or hide the status 
        elements if `msg' is empty or None.
        '''
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
        '''Remove the source directory at the given index.'''
        self.srcList.pop(index)
        self.updateSignal.emit()

    def addSource(self, rootdir):
        '''Add the given directory to the queue of directories to load and set the self.lastDir value to its parent.'''
        self.srcQueue.put(rootdir)
        self.lastDir = os.path.dirname(rootdir)


def main(args=[], qapp=None):
    '''
    Default main program which starts Qt based on the command line arguments `args', sets the stylesheet if present,
    then creates the window object and shows it. The `args' command line arguments list is passed to the window object
    to pick up on specified directories. The `qapp' object would be the QApplication object if it's created elsewhere,
    otherwise it's created here. Returns the value of QApplication.exec_() if this object was created here otherwise 0.
    '''
    if qapp is None:
        app = QtGui.QApplication(args)
        app.setAttribute(Qt.AA_DontUseNativeMenuBar)  # in OSX, forces menubar to be in window
        app.setStyle('Plastique')

        # load the stylesheet included as a Qt resource
        with closing(QtCore.QFile(':/css/DefaultUIStyle.css')) as f:
            if f.open(QtCore.QFile.ReadOnly):
                app.setStyleSheet(bytes(f.readAll()).decode('UTF-8'))
            else:
                print('Failed to read %r' % f.fileName())

    browser = DicomBrowser(args)
    browser.show()

    return 0 if qapp is not None else app.exec_()


def mainargv():
    '''setuptools compatible entry point.'''
    freeze_support()
    sys.exit(main(sys.argv))


if __name__ == '__main__':
    mainargv()
