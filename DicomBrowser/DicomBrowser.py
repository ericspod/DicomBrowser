#! /usr/bin/env python

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

import sys, os, threading, time, pickle, math
from operator import itemgetter
from collections import OrderedDict
from Queue import Queue, Empty
from multiprocessing import Pool, Manager, cpu_count, freeze_support
from functools import wraps

import numpy as np

from PyQt4 import QtGui, QtCore
from PyQt4.QtCore import Qt
from DicomBrowserWin import Ui_DicomBrowserWin

scriptdir= os.path.dirname(os.path.abspath(__file__)) # path of the current file

# this allows the script to be run directly from the repository without having to install pydicom or pyqtgraph
if os.path.isdir(scriptdir+'/../pydicom'):
	sys.path.append(scriptdir+'/../pydicom')
	sys.path.append(scriptdir+'/../pyqtgraph')

import pyqtgraph as pg

from pydicom.dicomio import read_file
from pydicom.datadict import DicomDictionary
from pydicom.errors import InvalidDicomError


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


def enumAllFiles(rootdir):
	'''Yields all absolute path regular files in the given directory.'''
	for root, dirs, files in os.walk(rootdir):
		for f in sorted(files):
			yield os.path.join(root,f)


def avgspan(vals):
	'''Returns the average difference between successive values derived from the given iterable.'''
	return np.average([b-a for a,b in zip(vals,vals[1:])])
	
	
def clamp(val,minv,maxv):
	'''Returns minv if val<minv, maxv if val>maxv, otherwise val.'''
	if val>maxv:
		return maxv
	if val<minv:
		return minv
	return val
	

def partitionSequence(maxval,part,numparts):
	'''
	Calculate the begin and end indices in the sequence [0,maxval) for partition `part' out of `numparts' total
	partitions. This is used to equally divide a sequence of numbers (eg. matrix rows or array indices) so that they
	may be assigned to multiple procs/threads. The result `start,end' defines a sequence [start,end) of numbers.
	'''
	partsize=maxval/float(numparts)
	start=math.floor(part*partsize)
	end=math.floor((part+1)*partsize)
	if (maxval-end)<partsize:
		end=maxval

	return long(start),long(end)


def tableResize(table):
	'''Resizes table columns to contents, setting the last section to stretch.'''
	table.horizontalHeader().setStretchLastSection(False)
	table.resizeColumnsToContents()
	table.horizontalHeader().setStretchLastSection(True)

		
def fillTagModel(model,dcm):
	'''Fill a QStandardItemModel object `model' with a tree derived from the tags in `dcm'.'''
	def _datasetToItem(parent,d):
		for elem in d:
			value=_elemToValue(elem)
			parent1 = QtGui.QStandardItem(str(elem.name))
			tagitem = QtGui.QStandardItem('(%04x, %04x)'%(elem.tag.group,elem.tag.elem))
			
			if isinstance(value,str):
				try:
					value=value.decode('ascii')
				except:
					value=repr(value)
					
				parent.appendRow([parent1,tagitem,QtGui.QStandardItem(value)])
			elif value is not None:
				parent.appendRow([parent1,tagitem])
				for v in value:
					parent1.appendRow(v)
		
	def _elemToValue(elem):
		value=None
		if elem.VR=='SQ':
			value=[]
			for i,item in enumerate(elem):
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
	numprocs=numprocs or cpu_count()
	m = Manager()
	queue=m.Queue()
	allfiles=list(enumAllFiles(rootdir))
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
			s,e=partitionSequence(numfiles,i,numprocs)
			r=pool.apply_async(loadDicomFiles,(allfiles[s:e],queue))
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
			except:
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
			return times[0],avgspan(times),len(times)


class SeriesTableModel(QtCore.QAbstractTableModel):
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

	statusSignal=QtCore.pyqtSignal(str,int,int)

	def __init__(self,args,parent=None):
		QtGui.QMainWindow.__init__(self,parent)
		self.setupUi(self)
		
		self.importButton.clicked.connect(self._openDirDialog)
		self.statusSignal.connect(self.setStatus)

		self.setStatus('')

		self.dirQueue=Queue()
		self.loadDirThread=threading.Thread(target=self._loadDirsThread)
		self.loadDirThread.daemon=True
		self.loadDirThread.start()

		self.srclist=[]
		self.seriesTable=[] # == self.seriesMap.keys()
		self.seriesMap={} # maps table entry to DicomSeries object it was generated from
		self.seriesColumns=list(seriesListColumns) # keywords for columns
		self.selectedRow=-1 # selected series row
		self.lastDir='.' # last loaded directory root

		self.srcmodel=QtGui.QStringListModel() #SourceListModel(self.srclist,self)
		self.listView.setModel(self.srcmodel)

		self.seriesmodel=SeriesTableModel(self.seriesTable,self.seriesColumns,self)
		self.tableView.setModel(self.seriesmodel)
		self.tableView.clicked.connect(self._tableClicked)
		
		self.seriesmodel.modelReset.connect(lambda:tableResize(self.tableView))
		
		self.tagmodel=QtGui.QStandardItemModel()
		self.tagView.setModel(self.tagmodel)

		self.imageSlider.valueChanged.connect(self.setSeriesImage)

		self.imageview=pg.ImageView()
		self.seriesTab.insertTab(0,self.imageview,'2D View')
		self.seriesTab.setCurrentIndex(0)
		
		# load the empty image placeholder into a ndarray
		qimg=QtGui.QImage(':/icons/noimage.png')
		bytedata=qimg.constBits().asstring(qimg.width()*qimg.height())
		self.noimg=np.ndarray((qimg.width(),qimg.height()),dtype=np.ubyte,buffer=bytedata)
		
		for i in args:
			if os.path.isdir(i):
				self.addSourceDir(i)

	def keyPressEvent(self,e):
		if e.key() == QtCore.Qt.Key_Escape:
			self.close()
		else:
			QtGui.QMainWindow.keyPressEvent(self,e)

	def show(self):
		QtGui.QMainWindow.show(self)
		self.listSplit.moveSplitter(200,1)
		self.seriesSplit.moveSplitter(200,1)

	def _loadDirsThread(self):
		while True:
			try:
				rootdir=self.dirQueue.get(True,0.5)
				series=loadDicomDir(rootdir,self.statusSignal.emit)
				if series and all(len(s.filenames)>0 for s in series):
					for s in series:
						s.filenames,s.dcms=zip(*sorted(zip(s.filenames,s.dcms))) # sort series contents by filename
					self.srclist.append((rootdir,series))

				self._updateTable()
			except Empty:
				pass

	def _openDirDialog(self):
		rootdir=str(QtGui.QFileDialog.getExistingDirectory(self,'Choose Source Directory',self.lastDir))
		if rootdir:
			self.addSourceDir(rootdir)

	def _updateTable(self):
		del self.seriesTable[:]
		self.seriesMap.clear()

		for _,series in self.srclist:
			for s in series:
				entry=s.getTagValues(self.seriesColumns)
				self.seriesMap[entry]=s
				self.seriesTable.append(entry)

		self.srcmodel.setStringList([s[0] for s in self.srclist])
		self.seriesmodel.modelReset.emit()

	def _tableClicked(self,item):
		self.selectedRow=item.row()
		self.setSeriesImage(self.imageSlider.value(),True)

	def setSeriesImage(self,i,autoRange=False):
		if 0<=self.selectedRow<len(self.seriesTable):
			rowvals=self.seriesTable[self.selectedRow]
			series=self.seriesMap[rowvals]
			maxindex=len(series.filenames)-1
			i=clamp(i,0,maxindex)
			interval=1
			
			if maxindex>=5000:
				interval=100
			elif maxindex>=500:
				interval=10
				
			self.imageSlider.setTickInterval(interval)
			self.imageSlider.setMaximum(maxindex)

			self.numLabel.setText(str(i))
			img=series.getPixelData(i)
			if img is None:
				img=self.noimg

			self.imageview.setImage(img.T,autoRange=autoRange,autoLevels=self.autoLevelsCheck.isChecked())
			
			vpos=self.tagView.verticalScrollBar().value()
			self.tagmodel.clear()
			self.tagmodel.setHorizontalHeaderLabels(tagTreeColumns)
			fillTagModel(self.tagmodel,series.getTagObject(i))
			self.tagView.expandAll()
			self.tagView.resizeColumnToContents(0)
			self.tagView.verticalScrollBar().setValue(vpos)
			
	def setStatus(self,msg,progress=0,progressmax=0):
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
		self.srclist.pop(index)
		self._updateTable()

	def addSourceDir(self,rootdir):
		self.dirQueue.put(rootdir)
		self.lastDir=os.path.dirname(rootdir)


def main(args=[],app=None):
	if not app:
		app = QtGui.QApplication(args)
		app.setAttribute(Qt.AA_DontUseNativeMenuBar) # in OSX, forces menubar to be in window
		app.setStyle('Plastique')
		
		# load the stylesheet included as a Qt resource
		f=QtCore.QFile(':/css/DefaultUIStyle.css')
		if f.open(QtCore.QFile.ReadOnly):
			app.setStyleSheet(str(f.readAll()))
			f.close()
		else:
			print ('Failed to read %r'%f.fileName())

	browser=DicomBrowser(args)
	browser.show()

	return app.exec_() if app else 0


def mainargv():
	'''setuptools compatible entry point.'''
<<<<<<< HEAD
	main(sys.argv)
=======
	freeze_support()
	sys.exit(main(sys.argv))
	
>>>>>>> Version update
