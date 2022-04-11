# DicomBrowser
# Copyright (C) 2016-22 Eric Kerfoot, King's College London, all rights reserved
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


import re
from operator import itemgetter

from PyQt5 import QtGui, QtCore
from PyQt5.QtCore import Qt

from .dicom import KEYWORD_NAME_MAP


def fill_tags(model, dcm, columns, regex=None, maxValueSize=256):
    """Fill the model with the tags from `dcm`."""
    try:
        regex = re.compile(str(regex), re.DOTALL)
    except:
        regex = ""  # no regex or bad pattern

    def _dataset_to_item(parent, d):
        """Add every element in `d' to the QStandardItem object `parent', this will be recursive for list elements."""
        for elem in d:
            value = _elem_to_value(elem)
            tag = "(%04x, %04x)" % (elem.tag.group, elem.tag.elem)
            parent1 = QtGui.QStandardItem(str(elem.name))
            tagitem = QtGui.QStandardItem(tag)

            if isinstance(value, str):
                origvalue = value

                if len(value) > maxValueSize:
                    origvalue = repr(value)
                    value = value[:maxValueSize] + "..."

                try:
                    value = value.decode("ascii")
                    if "\n" in value or "\r" in value:  # multiline text data should be shown as repr
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

    def _elem_to_value(elem):
        """Return the value in `elem', which will be a string or a list of QStandardItem objects if elem.VR=='SQ'."""
        value = None
        if elem.VR == "SQ":
            value = []

            for i, item in enumerate(elem):
                parent1 = QtGui.QStandardItem("%s %i" % (elem.name, i))
                _dataset_to_item(parent1, item)

                if not regex or parent1.hasChildren():  # discard sequences whose children have been filtered out
                    value.append(parent1)

        elif elem.name != "Pixel Data":
            value = str(elem.value)

        return value

    tparent = QtGui.QStandardItem("Tags") # create a parent node every tag is a child of, used for copying all tag data
    model.appendRow([tparent])
    _dataset_to_item(tparent, dcm)


class SeriesTableModel(QtCore.QAbstractTableModel):
    """This manages the list of series with a sorting feature."""

    def __init__(self, series_columns, parent=None):
        super().__init__(parent)
        self.series_table = []
        self.series_columns = series_columns
        self.sortCol = 0
        self.sortOrder = Qt.AscendingOrder

    def rowCount(self, parent):
        return len(self.series_table)

    def columnCount(self, parent):
        return len(self.series_table[0]) if self.series_table else 0

    def sort(self, column, order):
        self.layoutAboutToBeChanged.emit()
        self.sortCol = column
        self.sortOrder = order

        self.series_table.sort(key=itemgetter(column), reverse=order == Qt.DescendingOrder)
        self.layoutChanged.emit()

    def updateSeriesTable(self, series_table):
        self.series_table = list(series_table)
        self.sort(self.sortCol, self.sortOrder)  # sort using existing parameters

    def getRow(self, i):
        return self.series_table[i]

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return KEYWORD_NAME_MAP[self.series_columns[section]]

    def data(self, index, role):
        if index.isValid() and role == Qt.DisplayRole:
            return str(self.series_table[index.row()][index.column()])


class TagItemModel(QtGui.QStandardItemModel):
    """This manages a list of tags from a single Dicom file."""

    def fill_tags(self, dcm, columns, regex=None, maxValueSize=256):
        self.clear()
        self.setHorizontalHeaderLabels(columns)
        fill_tags(self, dcm, columns, regex, maxValueSize) # actual code in a separate function to be usable elsewhere
