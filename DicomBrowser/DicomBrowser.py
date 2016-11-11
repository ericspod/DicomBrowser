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

import sys, os, platform, mmap, threading, time, pickle,math
from operator import itemgetter
from collections import OrderedDict
from Queue import Queue, Empty
from StringIO import StringIO
from multiprocessing import Pool,Manager,cpu_count
from functools import wraps

import numpy as np

from PyQt4 import QtGui,QtCore, uic
from PyQt4.QtCore import QDir,Qt
import Resources_rc
from DicomBrowserWin import Ui_DicomBrowserWin

scriptdir= os.path.dirname(os.path.abspath(__file__)) # path of the current file

sys.path.append(scriptdir+'/../pydicom')
sys.path.append(scriptdir+'/../pyqtgraph')

import pyqtgraph as pg

from pydicom.dicomio import read_file
from pydicom.datadict import DicomDictionary
from pydicom.errors import InvalidDicomError
	
	
isDarwin=platform.system().lower()=='darwin'

emptyImage=np.asarray([
[  0,   0,   0,   0,   0,   0,   0,   0,   0],
[  0,   0,   1,   2,   2,   2,   1,   0,   0],
[  0,   0,   2,   1,   0,   1,   2,   0,   0],
[  0,   0,   0,   0,   0,   1,   2,   0,   0],
[  0,   0,   0,   0,   1,   2,   1,   0,   0],
[  0,   0,   0,   1,   2,   1,   0,   0,   0],
[  0,   0,   0,   0,   0,   0,   0,   0,   0],
[  0,   0,   0,   1,   2,   1,   0,   0,   0],
[  0,   0,   0,   0,   0,   0,   0,   0,   0]
])

# tag names of default columns
defaultColumns=('PatientName','SeriesDescription','SeriesNumber','NumImages')

# list of tags to initially load when a directory is scanned
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

# maps full names to keywords
fullNameMap={v:k for k,v in keywordNameMap.items()} #{v[2]:v[4] for v in DicomDictionary.values()}


def enumAllFiles(rootdir):
	'''Yields all absolute path regular files in the given directory.'''
	for root, dirs, files in os.walk(rootdir):
		for f in sorted(files):
			yield os.path.join(root,f)
			
			
def isPicklable(obj):
	'''Returns True if `obj' can be pickled.'''
	try:
		pickle.dumps(obj)
		return True
	except:
		return False


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
	
	
def printFlush(*args):
	sys.stdout.write(' '.join(map(str,args))+'\n')
	sys.stdout.flush()
	
	
def timing(func):
	'''This decorator prints to stdout the original function's execution time in seconds.'''
	@wraps(func)
	def timingwrap(*args,**kwargs):
		printFlush(func.__name__)
		start=time.time()
		res=func(*args,**kwargs)
		end=time.time()
		printFlush(func.__name__, 'dT (s) =',(end-start))
		return res

	return timingwrap
	

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
	
	
def convertToDict(dcm):
	def _datasetToDict(dcm):
		result=OrderedDict()
		for elem in dcm:
			name=elem.name
			value=_elemToValue(elem)
			tag=(elem.tag.group,elem.tag.elem)

			if value:
				result[tag]=(name,value)
				#result[tag]=(fullNameMap.get(name,name),value)
				
		return result

	def _elemToValue(elem):
		value=None
		if elem.VR=='SQ':
			value=OrderedDict()
			for i,item in enumerate(elem):
				value['item_%i'%i]=_datasetToDict(item)
		elif elem.name!='Pixel Data':
			value=elem.value
			if not isPicklable(value):
				value=str(value)

		return value

	return _datasetToDict(dcm)
	

def loadDicomFiles(filenames,queue):
	for filename in filenames:
		try:
			dcm=read_file(filename,stop_before_pixels=True)
			#dcm=convertToDict(dcm)
			dcm={t:dcm.get(t) for t in loadTags if t in dcm}
			queue.put((filename,dcm))
		except InvalidDicomError:
			pass


def loadDicomDir(rootdir,statusfunc=lambda *args:None,numprocs=None):
	numprocs=numprocs or cpu_count()
	pool=Pool(processes=numprocs)
	m = Manager()
	queue=m.Queue()
	allfiles=list(enumAllFiles(rootdir))
	numfiles=len(allfiles)
	res=[]
	series={}
	count=0

	statusfunc('Loading DICOM files',0,0)

	for i in range(numprocs):
		s,e=partitionSequence(numfiles,i,numprocs)
		r=pool.apply_async(loadDicomFiles,(allfiles[s:e],queue))
		res.append(r)

	while any(not r.ready() for r in res) or not queue.empty():
		try:
			filename,dcm=queue.get(False)
			seriesid=dcm.get('SeriesInstanceUID','???')
			if seriesid not in series:
				series[seriesid]=DicomSeries(seriesid,rootdir)

			series[seriesid].addFile(filename,dcm)
			count+=1
			statusfunc('Loading DICOM files',count,numfiles)
		except Empty:
			pass

	statusfunc('',0,0)

	return series.values()


class DicomSeries(object):
	def __init__(self,seriesID,rootdir):
		self.seriesID=seriesID
		self.rootdir=rootdir
		self.filenames=[]
		self.dcms=[]
		self.imgcache={}
		self.tagcache={}
		
	def addFile(self,filename,dcm):
		self.filenames.append(filename)
		self.dcms.append(dcm)
		
	def getTagDict(self,index):
		if index not in self.tagcache:
			dcm=read_file(self.filenames[index],stop_before_pixels=True)
			self.tagcache[index]=dcm #convertToDict(dcm)
			
		return self.tagcache[index]

	def getExtraTagValues(self):
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
		if not self.filenames:
			return ()

		dcm=self.getTagDict(index)
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


class SourceListModel(QtCore.QAbstractListModel):
	def __init__(self, srclist, parent=None):
		QtCore.QAbstractListModel.__init__(self, parent)
		self.srclist = srclist

	def rowCount(self, parent=QtCore.QModelIndex()):
		return len(self.srclist)

	def data(self, index, role):
		if index.isValid() and role == Qt.DisplayRole:
			return self.srclist[index.row()][0]


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


class TagTableModel(QtCore.QAbstractTableModel):
	def __init__(self,parent=None):
		QtCore.QAbstractTableModel.__init__(self, parent)
		self.columns=('Tag','Name','Value')
		self.tagList=[]
		self.sortCol=0
		self.sortOrder=Qt.AscendingOrder
		
	def setDicomTags(self,tagdict):
		tagdict=convertToDict(tagdict)
		self.tagList=[('(%x, %x)'%t,str(n).strip(),repr(v).strip()) for t,(n,v) in tagdict.items()]
		
		self.resort()
		
	def rowCount(self, parent):
		return len(self.tagList)
		
	def columnCount(self,parent):
		return len(self.columns)
		
	def sort(self,column,order):
		self.sortCol=column
		self.sortOrder=order
		self.resort()
		
	def resort(self):
		self.layoutAboutToBeChanged.emit()
		self.tagList.sort(key=itemgetter(self.sortCol),reverse=self.sortOrder==Qt.DescendingOrder)
		self.layoutChanged.emit()
		
	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole and orientation==Qt.Horizontal:
			return self.columns[section]
			
	def data(self, index, role):
		if index.isValid() and role == Qt.DisplayRole:
			return self.tagList[index.row()][index.column()]
		

class DicomBrowser(QtGui.QMainWindow,Ui_DicomBrowserWin):

	statusSignal=QtCore.pyqtSignal(str,int,int)

	def __init__(self,argv,parent=None):
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
		self.seriesColumns=list(defaultColumns) # keywords for columns
		self.selectedRow=-1 # selected series row

		self.srcmodel=SourceListModel(self.srclist,self)
		self.listView.setModel(self.srcmodel)

		self.seriesmodel=SeriesTableModel(self.seriesTable,self.seriesColumns,self)
		self.tableView.setModel(self.seriesmodel)
		self.tableView.clicked.connect(self._tableClicked)
		
		self.tagmodel=TagTableModel()
		self.tagView.setModel(self.tagmodel)

		self.imageSlider.valueChanged.connect(self.setSeriesImage)

		self.imageview=pg.ImageView()
		self.seriesTab.insertTab(0,self.imageview,'2D View')
		self.seriesTab.setCurrentIndex(0)

		for i in argv:
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
		rootdir=str(QtGui.QFileDialog.getExistingDirectory(self,'Choose Source Directory','.'))
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

		self.srcmodel.modelReset.emit()
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
				img=emptyImage

			self.imageview.setImage(img.T,autoRange=autoRange,autoLevels=self.autoLevelsCheck.isChecked())
			self.tagmodel.setDicomTags(series.getTagDict(i))
			
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


def main(args,app=None):
	if not app:
		app = QtGui.QApplication(args)
		app.setAttribute(Qt.AA_DontUseNativeMenuBar) # in OSX, forces menubar to be in window
		app.setStyle('Plastique')
		app.setStyleSheet(open(scriptdir+'/DefaultUIStyle.css').read())

	browser=DicomBrowser(args)
	browser.show()

	return app.exec_()

if __name__ == '__main__':
	sys.exit(main(sys.argv))
	