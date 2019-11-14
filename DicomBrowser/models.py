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
'''
DicomBrowser - simple lightweight Dicom browsing application. 
'''

from __future__ import print_function
import re
from operator import itemgetter


try:  # PyQt4 and 5 support
    from PyQt5 import QtGui, QtCore, uic
    from PyQt5.QtCore import Qt, QStringListModel
except ImportError:
    from PyQt4 import QtGui, QtCore, uic
    from PyQt4.QtCore import Qt
    from PyQt4.QtGui import QStringListModel
    
from .dicom import keywordNameMap
    

class SeriesTableModel(QtCore.QAbstractTableModel):
    """This manages the list of series with a sorting feature."""

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


class TagItemModel(QtGui.QStandardItemModel):
    """This manages a list of tags from a single Dicom file."""
    
    def fillTags(self,dcm, columns,regex=None, maxValueSize=256):
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

        self.clear()
        self.setHorizontalHeaderLabels(columns)
        tparent = QtGui.QStandardItem('Tags')  # create a parent node every tag is a child of, used for copying all tag data
        self.appendRow([tparent])
        _datasetToItem(tparent, dcm)
