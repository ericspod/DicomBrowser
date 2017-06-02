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

import sys, os, threading, math
from operator import itemgetter
from Queue import Queue, Empty
from multiprocessing import Pool, Manager, cpu_count, freeze_support
from contextlib import closing
from StringIO import StringIO
import re

import numpy as np

from PyQt4 import QtGui, QtCore, uic
from PyQt4.QtCore import Qt
from .__init__ import __version__

scriptdir= os.path.dirname(os.path.abspath(__file__)) # path of the current file

# this allows the script to be run directly from the repository without having to install pydicom or pyqtgraph
if os.path.isdir(scriptdir+'/../pydicom'):
    sys.path.append(scriptdir+'/../pydicom')
    sys.path.append(scriptdir+'/../pyqtgraph')

import pyqtgraph as pg

from pydicom.dicomio import read_file
from pydicom.datadict import DicomDictionary
from pydicom.errors import InvalidDicomError

import Resources_rc4 # import resources manually since we have to do this to get the ui file

# load the ui file from the resource, removing the "resources" tag so that uic doesn't try (and fail) to load the resources
with closing(QtCore.QFile(':/layout/DicomBrowserWin.ui')) as layout:
    if layout.open(QtCore.QFile.ReadOnly):
        s=str(layout.readAll())
        s=re.sub('<resources>.*</resources>','',s,flags=re.DOTALL) # get rid of the resources section in the XML
        Ui_DicomBrowserWin,_=uic.loadUiType(StringIO(s)) # create a local type definition


# tag names of default columns in the series list, this can be changed to pull out different tag names for columns
seriesListColumns=('PatientName','SeriesDescription','SeriesNumber','NumImages')
# names of columns in tag tree, this shouldn't ever change
tagTreeColumns=('Name','Tag','Value')
# list of tags to initially load when a directory is scanned, loading only these speeds up scanning immensely
loadTags=('SeriesInstanceUID','TriggerTime','PatientName','SeriesDescription','SeriesNumber')

# keyword/full name pairs for extra properties not represented as Dicom tags
extraKeywords={
    'NumImages':'# Images',
    'TimestepSpec':'Timestep Info',
    'StartTime':'Start Time',
    'NumTimesteps':'# Timesteps',
    'TimeInterval':'Time Interval'
}

# maps keywords to their full names
keywordNameMap={v[4]:v[2] for v in DicomDictionary.values()}
keywordNameMap.update(extraKeywords)

fullNameMap={v:k for k,v in keywordNameMap.items()} # maps full names to keywords


def tableResize(table):
    '''Resizes table columns to contents, setting the last section to stretch.'''
    table.horizontalHeader().setStretchLastSection(False)
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)

        
def fillTagModel(model,dcm,regex=None):
    '''Fill a QStandardItemModel object `model' with a tree derived from tags in `dcm', filtering by pattern `regex'.'''
    try:
        regex=re.compile(str(regex),re.DOTALL)
    except:
        regex='' # no regex or bad pattern
            
    def matches(val):
        '''Returns True if `val' matches the supplied pattern or if no pattern is given.'''
        return not regex or re.search(regex,val) is not None

    def _datasetToItem(parent,d):
        '''Add every element in `d' to the QStandardItem object `parent', this will be recursive for list elements.'''
        for elem in d:
            value=_elemToValue(elem)
            parent1 = QtGui.QStandardItem(str(elem.name))
            tagitem = QtGui.QStandardItem('(%04x, %04x)'%(elem.tag.group,elem.tag.elem))
            
            if isinstance(value,str):
                try:
                    value=value.decode('ascii')
                    if '\n' in value or '\r' in value: # multiline text data should be shown as repr
                        value=repr(value)
                except:
                    value=repr(value)
                    
                if matches(str(elem.name)+value):
                    parent.appendRow([parent1,tagitem,QtGui.QStandardItem(value)])
                    
            elif value is not None and len(value)>0:
                parent.appendRow([parent1,tagitem])
                for v in value:
                    parent1.appendRow(v)
        
    def _elemToValue(elem):
        '''Return the value in `elem', which will be a string or a list of QStandardItem objects if elem.VR=='SQ'.'''
        value=None
        if elem.VR=='SQ':
            value=[]
            for i,item in enumerate(elem):
                if matches(str(elem.name)):
                    parent1 = QtGui.QStandardItem('%s %i'%(elem.name,i))
                    _datasetToItem(parent1,item)
                    value.append(parent1)
        elif elem.name!='Pixel Data':
            value=str(elem.value)

        return value        
                
    _datasetToItem(model,dcm)
    

def loadDicomFiles(filenames,queue):
    '''Load the Dicom files `filenames' and put an abbreviated tag->value map for each onto `queue'.'''
    for filename in filenames:
        try:
            dcm=read_file(filename,stop_before_pixels=True)
            tags={t:dcm.get(t) for t in loadTags if t in dcm}
            queue.put((filename,tags))
        except InvalidDicomError:
            pass


def loadDicomDir(rootdir,statusfunc=lambda s,c,n:None,numprocs=None):
    '''
    Load all the Dicom files from `rootdir' using `numprocs' number of processes. This will attempt to load each file
    found in `rootdir' and store from each file the tags defined in loadTags. The filenames and the loaded tags for
    Dicom files are stored in a DicomSeries object representing the acquisition series each file belongs to. The 
    `statusfunc' callback is used to indicate loading status, taking as arguments a status string, count of loaded 
    objects, and the total number to load. A status string of '' indicates loading is done. The default value causes 
    no status indication to be made. Return value is a sequence of DicomSeries objects in no particular order.
    '''
    allfiles=[]
    for root,_,files in os.walk(rootdir):
        allfiles+=[os.path.join(root,f) for f in files]
        
    numprocs=numprocs or cpu_count()
    m = Manager()
    queue=m.Queue()
#    allfiles=list(enumAllFiles(rootdir))
    numfiles=len(allfiles)
    res=[]
    series={}
    count=0
    
    if not numfiles:
        return []

    statusfunc('Loading DICOM files',0,0)
    
    try:
        pool=Pool(processes=numprocs)
        
        for i in range(numprocs):
            # partition the list of files amongst each processor
            partsize=numfiles/float(numprocs)
            start=int(math.floor(i*partsize))
            end=int(math.floor((i+1)*partsize))
            if (numfiles-end)<partsize:
                end=numfiles
                
            r=pool.apply_async(loadDicomFiles,(allfiles[start:end],queue))
            res.append(r)
    
        # loop so long as any process is busy or there are files on the queue to process
        while any(not r.ready() for r in res) or not queue.empty():
            try:
                filename,dcm=queue.get(False)
                seriesid=dcm.get('SeriesInstanceUID','???')
                if seriesid not in series:
                    series[seriesid]=DicomSeries(seriesid,rootdir)
    
                series[seriesid].addFile(filename,dcm)
                count+=1
                
                # update status only 100 times, doing it too frequently really slows things down
                if numfiles<100 or count%(numfiles/100)==0: 
                    statusfunc('Loading DICOM files',count,numfiles)
            except Empty: # from queue.get(), keep trying so long as the loop condition is true
                pass
    finally:
        pool.close()
        statusfunc('',0,0)

    return series.values()
    

class DicomSeries(object):
    '''
    This type represents a Dicom series as a list of Dicom files sharing a series UID. The assumption is that the images
    of a series were captured together and so will always have a number of fields in common, such as patient name, so
    Dicoms should be organized by series. This type will also cache loaded Dicom tags and images
    '''
    def __init__(self,seriesID,rootdir):
        self.seriesID=seriesID # ID of the series or ???
        self.rootdir=rootdir # the directory where Dicoms were loaded from, files for this series may be in subdirectories
        self.filenames=[] # list of filenames for the Dicom associated with this series
        self.dcms=[] # loaded abbreviated tag->(name,value) maps, 1 for each of self.filenames
        self.imgcache={} # cache of loaded image data, mapping index in self.filenames to ndarray objects or None for non-images files
        self.tagcache={} # cache of all loaded tag values, mapping index in self.filenames to OrderedDict of tag->(name,value) maps
        
    def addFile(self,filename,dcm):
        '''Add a filename and abbreviated tag map to the series.'''
        self.filenames.append(filename)
        self.dcms.append(dcm)
        
    def getTagObject(self,index):
        '''Get the object storing tag information from Dicom file at the given index.'''
        if index not in self.tagcache:
            dcm=read_file(self.filenames[index],stop_before_pixels=True)
            self.tagcache[index]=dcm
            
        return self.tagcache[index]

    def getExtraTagValues(self):
        '''Return the extra tag values calculated from the series tag info stored in self.dcms.'''
        start,interval,numtimes=self.getTimestepSpec()
        extravals={
            'NumImages':len(self.dcms),
            'TimestepSpec':'start: %i, interval: %i, # Steps: %i'%(start,interval,numtimes),
            'StartTime':start,
            'NumTimesteps':numtimes,
            'TimeInterval':interval
        }

        return extravals
        
    def getTagValues(self,names,index=0):
        '''Get the tag values for tag names listed in `names' for image at the given index.'''
        if not self.filenames:
            return ()

        dcm=self.getTagObject(index)
        extravals=self.getExtraTagValues()
        
        return tuple(str(dcm.get(n,extravals.get(n,''))) for n in names)

    def getPixelData(self,index):
        '''Get the pixel data Numpy array for file at position `index` in self.filenames, or None if there is no pixel data.'''
        if index not in self.imgcache:
            img=None
            try:
                dcm=read_file(self.filenames[index])
                if dcm.pixel_array is not None:
                    rslope=float(dcm.get('RescaleSlope',1))
                    rinter=float(dcm.get('RescaleIntercept',0))
                    img= dcm.pixel_array*rslope+rinter
            except Exception:
                pass
                
            self.imgcache[index]=img
            
        return self.imgcache[index]

    def addSeries(self,series):
        '''Add every loaded dcm file from DicomSeries object `series` into this series.'''
        for f,dcm in zip(series.filenames,series.dcms):
            self.addFile(f,dcm)

    def getTimestepSpec(self,tag='TriggerTime'):
        '''Returns (start time, interval, num timesteps) triple.'''
        times=sorted(set(int(dcm.get(tag,0)) for dcm in self.dcms))

        if not times or times==[0]:
            return 0.0,0.0,0.0
        else:
            if len(times)==1:
                times=times*2
            
            avgspan=np.average([b-a for a,b in zip(times,times[1:])])
            return times[0],avgspan,len(times)


class SeriesTableModel(QtCore.QAbstractTableModel):
    '''This manages the list of series with a sorting feature.'''
    def __init__(self, seriesTable, seriesColumns,parent=None):
        QtCore.QAbstractTableModel.__init__(self, parent)
        self.seriesTable=seriesTable
        self.seriesColumns=seriesColumns
        self.sortCol=0
        self.sortOrder=Qt.AscendingOrder

    def rowCount(self, parent):
        return len(self.seriesTable)

    def columnCount(self,parent):
        return len(self.seriesTable[0]) if self.seriesTable else 0

    def sort(self,column,order):
        self.layoutAboutToBeChanged.emit()
        self.sortCol=column
        self.sortOrder=order

        self.seriesTable.sort(key=itemgetter(column),reverse=order==Qt.DescendingOrder)
        self.layoutChanged.emit()

    def resort(self):
        self.sort(self.sortCol,self.sortOrder)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation==Qt.Horizontal:
            return keywordNameMap[self.seriesColumns[section]]

    def data(self, index, role):
        if index.isValid() and role == Qt.DisplayRole:
            return str(self.seriesTable[index.row()][index.column()])


class DicomBrowser(QtGui.QMainWindow,Ui_DicomBrowserWin):
    '''
    This is the window class for the app which implements the UI functionality and the directory loading thread. It 
    inherits from the type loaded from the .ui file in the resources. 
    '''
    statusSignal=QtCore.pyqtSignal(str,int,int) # signal for updating the status bar asynchronously

    def __init__(self,args,parent=None):
        QtGui.QMainWindow.__init__(self,parent)

        self.srclist=[] # list of source directories
        self.imageIndex=0 # index of selected image
        self.seriesTable=[] # list of loaded series, equals self.seriesMap.keys() but in a sorted ordering
        self.seriesMap={} # maps series table entry to DicomSeries object it was generated from
        self.seriesColumns=list(seriesListColumns) # keywords for columns
        self.selectedRow=-1 # selected series row
        self.lastDir='.' # last loaded directory root
        self.filterRegex='' # regular expression to filter tags by

        # create the directory queue and loading thread objects
        self.dirQueue=Queue() # queue of directories to load
        self.loadDirThread=threading.Thread(target=self._loadDirsThread)
        self.loadDirThread.daemon=True # clean shutdown possible with daemon threads
        self.loadDirThread.start() # start the thread now, it will wait until something is put on self.dirQueue
        
        # setup ui
        self.setupUi(self) # create UI elements based on the loaded .ui file
        self.setWindowTitle('DicomBrowser v%s (FOR RESEARCH ONLY)'%(__version__))
        self.setStatus('')
        
        # connect signals
        self.importButton.clicked.connect(self._openDirDialog)
        self.statusSignal.connect(self.setStatus)
        self.filterLine.textChanged.connect(self._setFilterString)
        self.imageSlider.valueChanged.connect(self.setSeriesImage)
        self.seriesView.clicked.connect(self._seriesTableClicked)

        # setup the list and table models
        self.srcmodel=QtGui.QStringListModel()
        self.seriesmodel=SeriesTableModel(self.seriesTable,self.seriesColumns,self)
        self.seriesmodel.layoutChanged.connect(lambda:tableResize(self.seriesView))
        self.tagmodel=QtGui.QStandardItemModel()

        # assign models to views
        self.sourceListView.setModel(self.srcmodel)
        self.seriesView.setModel(self.seriesmodel)
        self.tagView.setModel(self.tagmodel)

        # create the pyqtgraph object for viewing images
        self.imageview=pg.ImageView()
        layout=QtGui.QGridLayout(self.view2DGroup)
        layout.addWidget(self.imageview)
        
        # load the empty image placeholder into a ndarray
        qimg=QtGui.QImage(':/icons/noimage.png')
        bytedata=qimg.constBits().asstring(qimg.width()*qimg.height())
        self.noimg=np.ndarray((qimg.width(),qimg.height()),dtype=np.ubyte,buffer=bytedata)
        
        # add the directories passed as arguments to the directory queue to start loading
        for i in args:
            if os.path.isdir(i):
                self.addSourceDir(i)

    def keyPressEvent(self,e):
        '''Close the window if escape is pressed, otherwise do as inherited.'''
        if e.key() == QtCore.Qt.Key_Escape:
            self.close()
        else:
            QtGui.QMainWindow.keyPressEvent(self,e)

    def show(self):
        '''Calls the inherited show() method then sets the splitter positions.'''
        QtGui.QMainWindow.show(self)
        self.listSplit.moveSplitter(200,1)
        self.seriesSplit.moveSplitter(100,1)
        self.viewMetaSplitter.moveSplitter(800,1)

    def _loadDirsThread(self):
        '''
        This method is run in a daemon thread and continually checks self.dirQueue for a queued directory to scan for
        Dicom files. It calls loadDicomDir() for a given directory and adds the results the self.srclist member.
        '''
        while True:
            try:
                rootdir=self.dirQueue.get(True,0.5)
                series=loadDicomDir(rootdir,self.statusSignal.emit)
                if series and all(len(s.filenames)>0 for s in series):
                    for s in series:
                        s.filenames,s.dcms=zip(*sorted(zip(s.filenames,s.dcms))) # sort series contents by filename
                    self.srclist.append((rootdir,series))

                self._updateSeriesTable()
            except Empty:
                pass

    def _openDirDialog(self):
        '''Opens the open file dialog to choose a directory to scan for Dicoms.'''
        rootdir=str(QtGui.QFileDialog.getExistingDirectory(self,'Choose Source Directory',self.lastDir))
        if rootdir:
            self.addSourceDir(rootdir)

    def _updateSeriesTable(self):
        '''
        Updates the self.seriesTable and self.seriesMap objects, and refills the self.srcmodel object. This will refresh 
        the list of source directories and the table of available series.
        '''
        del self.seriesTable[:]
        self.seriesMap.clear()

        for _,series in self.srclist: # add each series in each source into the self.seriesMap and self.seriesTable objects
            for s in series:
                entry=s.getTagValues(self.seriesColumns)
                self.seriesMap[entry]=s
                self.seriesTable.append(entry)

        self.srcmodel.setStringList([s[0] for s in self.srclist])
        #self.seriesmodel.modelReset.emit()
        self.seriesmodel.layoutChanged.emit()

    def _seriesTableClicked(self,item):
        '''Called when a series is clicked on, set the viewed image to be from the clicked series.'''
        self.selectedRow=item.row()
        self.setSeriesImage(self.imageSlider.value(),True)
            
    def _setFilterString(self,regex):
        '''Set the filtering regex to be `regex'.'''
        self.filterRegex=regex
        self._fillTagView()
            
    def _fillTagView(self):
        '''Refill the Dicom tag view, this will rejig the columns and (unfortunately) reset column sorting.'''
        series=self.getSelectedSeries()
        vpos=self.tagView.verticalScrollBar().value()
        self.tagmodel.clear()
        self.tagmodel.setHorizontalHeaderLabels(tagTreeColumns)
        fillTagModel(self.tagmodel,series.getTagObject(self.imageIndex),self.filterRegex)
        self.tagView.expandAll()
        self.tagView.resizeColumnToContents(0)
        self.tagView.verticalScrollBar().setValue(vpos)
        
    def getSelectedSeries(self):
        '''Returns the DicomSeries object for the selected series, None if no series is selected.'''
        if 0<=self.selectedRow<len(self.seriesTable):
            rowvals=self.seriesTable[self.selectedRow]
            return self.seriesMap[rowvals]

    def setSeriesImage(self,i,autoRange=False):
        '''
        Set the view image to be that at index `i' of the selected series. The `autoRange' boolean value sets whether
        the data value range is reset or not when this is done. The tag table is also set to that of image `i'.
        '''
        series=self.getSelectedSeries()
        if series:
            maxindex=len(series.filenames)-1
            self.imageIndex=np.clip(i,0,maxindex)
            img=series.getPixelData(self.imageIndex) # image matrix
            interval=1 # tick interval on the slider
            
            # choose a more sensible tick interval if there's a lot of images
            if maxindex>=5000:
                interval=100
            elif maxindex>=500:
                interval=10
            
            if img is None: # if the image is None use the default "no image" object
                img=self.noimg
            elif len(img.shape)==3: # multi-channel or multi-dimensional image, use average of dimensions
                img=np.mean(img,axis=2)

            self.imageview.setImage(img.T,autoRange=autoRange,autoLevels=self.autoLevelsCheck.isChecked())
            self._fillTagView()
            self.imageSlider.setTickInterval(interval)
            self.imageSlider.setMaximum(maxindex)
            self.numLabel.setText(str(self.imageIndex))
            
    def setStatus(self,msg,progress=0,progressmax=0):
        '''
        Set the status bar with message `msg' with progress set to `progress' out of `progressmax', or hide the status 
        elements if `msg' is empty or None.
        '''
        if not msg:
            progress=0
            progressmax=0

        self.statusText.setText(msg)
        self.statusText.setVisible(bool(msg))
        self.importButton.setVisible(not bool(msg))
        self.statusProgressBar.setVisible(progressmax>0)
        self.statusProgressBar.setRange(0,progressmax)
        self.statusProgressBar.setValue(progress)

    def removeSourceDir(self,index):
        '''Remove the source directory at the given index.'''
        self.srclist.pop(index)
        self._updateSeriesTable()

    def addSourceDir(self,rootdir):
        '''Add the given directory to the queue of directories to load and set the self.lastDir value to its parent.'''
        self.dirQueue.put(rootdir)
        self.lastDir=os.path.dirname(rootdir)


def main(args=[],app=None):
    '''
    Default main program which starts Qt based on the command line arguments `args', sets the stylesheet if present, then
    creates the window object and shows it. The `args' list of command line arguments is also passed to the window object
    to pick up on specified directories. The `app' object would be the QApplication object if this was created elsewhere,
    otherwise it's created here. Returns the value of QApplication.exec_() if this object was created here otherwise 0.
    '''
    if not app:
        app = QtGui.QApplication(args)
        app.setAttribute(Qt.AA_DontUseNativeMenuBar) # in OSX, forces menubar to be in window
        app.setStyle('Plastique')
        
        # load the stylesheet included as a Qt resource
        with closing(QtCore.QFile(':/css/DefaultUIStyle.css')) as f:
            if f.open(QtCore.QFile.ReadOnly):
                app.setStyleSheet(str(f.readAll()))
            else:
                print('Failed to read %r'%f.fileName())

    browser=DicomBrowser(args)
    browser.show()

    return app.exec_() if app else 0


def mainargv():
    '''setuptools compatible entry point.'''
    freeze_support()
    sys.exit(main(sys.argv))
