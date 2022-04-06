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

import os
import zipfile
from multiprocessing import Pool, Manager, Queue
from pydicom import dicomio, datadict, errors
from queue import Empty
from io import BytesIO

import numpy as np


# tag names of default columns in the series list, this can be changed to pull out different tag names for columns
SERIES_LIST_COLUMNS = (
    "NumImages",
    "SeriesNumber",
    "PatientName",
    "SeriesInstanceUID",
    "SeriesDescription",
)

# names of columns in tag tree, this shouldn't ever change
TAG_TREE_COLUMNS = ("Name", "Tag", "Value")

# list of tags to initially load when a directory is scanned, loading only these speeds up scanning immensely
LOAD_TAGS = (
    "SeriesInstanceUID",
    "TriggerTime",
    "PatientName",
    "SeriesDescription",
    "SeriesNumber",
)

# keyword/full name pairs for extra properties not represented as Dicom tags
EXTRA_KEYWORDS = {
    "NumImages": "# Images",
    "TimestepSpec": "Timestep Info",
    "StartTime": "Start Time",
    "NumTimesteps": "# Timesteps",
    "TimeInterval": "Time Interval",
}

# maps keywords to their full names
KEYWORD_NAME_MAP = {v[4]: v[2] for v in datadict.DicomDictionary.values()}
KEYWORD_NAME_MAP.update(EXTRA_KEYWORDS)

FULL_NAME_MAP = {v: k for k, v in KEYWORD_NAME_MAP.items()}  # maps full names to keywords


def load_dicom_file(filename, queue):
    """Load the Dicom file `filename` and put an abbreviated tag->value map onto `queue`."""
    try:
        dcm = dicomio.read_file(filename, stop_before_pixels=True)
        tags = {t: dcm.get(t) for t in LOAD_TAGS if t in dcm}
        queue.put((filename, tags))
    except errors.InvalidDicomError:
        pass


def load_dicom_dir(rootdir, statusfunc=lambda s, c, n: None, numprocs=None):
    """
    Load all the Dicom files from `rootdir' using `numprocs' number of processes. This will attempt to load each file
    found in `rootdir' and store from each file the tags defined in loadTags. The filenames and the loaded tags for
    Dicom files are stored in a DicomSeries object representing the acquisition series each file belongs to. The 
    `statusfunc' callback is used to indicate loading status, taking as arguments a status string, count of loaded 
    objects, and the total number to load. A status string of '' indicates loading is done. The default value causes 
    no status indication to be made. Return value is a sequence of DicomSeries objects in no particular order.
    """
    allfiles = []
    for root, _, files in os.walk(rootdir):
        allfiles += [os.path.join(root, f) for f in files if f.lower() != "dicomdir"]

    numfiles = len(allfiles)
    series = {}
    count = 0

    if not numfiles:
        return []

    with Manager() as m:
        queue = m.Queue()
        with Pool(processes=numprocs) as pool:
            res = pool.starmap_async(load_dicom_file, [(f,queue) for f in allfiles])
    
            # loop so long as any process is busy or there are files on the queue to process
            while not res.ready() or not queue.empty():
                try:
                    filename, dcm = queue.get(False)
                    seriesid = dcm.get("SeriesInstanceUID", "???")
                    if seriesid not in series:
                        series[seriesid] = DicomSeries(seriesid, rootdir)
    
                    series[seriesid].add_file(filename, dcm)
                except Empty:  # from queue.get(), keep trying so long as the loop condition is true
                    pass
    
                count += 1
                # update status only 100 times, doing it too frequently really slows things down
                if numfiles < 100 or count % (numfiles // 100) == 0:
                    statusfunc("Loading DICOM files", count, numfiles)

    statusfunc("", 0, 0)
    return list(series.values())


def load_dicom_zip(filename, statusfunc=lambda s, c, n: None):
    """
    Load Dicom images from given zip file `filename'. This uses the status callback `statusfunc' like load_dicom_dir().
    Loaded files will have their pixel data thus avoiding the need to reload the zip file when an image is viewed but is
    at the expense of load time and memory. Return value is a sequence of DicomSeries objects in no particular order.
    """
    series = {}
    count = 0

    with zipfile.ZipFile(filename) as z:
        names = z.namelist()
        numfiles = len(names)
        
        for n in names:
            nfilename = "%s?%s" % (filename, n)
            s = BytesIO(z.read(n))
            
            try:
                dcm = dicomio.read_file(s)
            except:
                pass  # ignore files which aren't Dicom files, various exceptions raised so no concise way to do this
            else:
                seriesid = dcm.get("SeriesInstanceUID", "???")

                if seriesid not in series:
                    series[seriesid] = DicomSeries(seriesid, nfilename)

                # need to load image data now since we don't want to reload the zip file later when an image is viewed
                try:  # attempt to create the image matrix, store None if this doesn't work
                    rslope = float(dcm.get("RescaleSlope", 1) or 1)
                    rinter = float(dcm.get("RescaleIntercept", 0) or 0)
                    img = dcm.pixel_array * rslope + rinter
                except:
                    img = None

                s = series[seriesid]
                s.add_file(nfilename, dcm)
                s.tagcache[len(s.filenames) - 1] = dcm
                s.imgcache[len(s.filenames) - 1] = img

            count += 1
            # update status only 100 times, doing it too frequently really slows things down
            if numfiles < 100 or count % (numfiles // 100) == 0:
                statusfunc("Loading DICOM files", count, numfiles)

    statusfunc("", 0, 0)

    return list(series.values())


class DicomSeries(object):
    """
    This type represents a Dicom series as a list of Dicom files sharing a series UID. The assumption is that the images
    of a series were captured together and so will always have a number of fields in common, such as patient name, so
    Dicoms should be organized by series. This type will also cache loaded Dicom tags and images
    """

    def __init__(self, series_id, rootdir):
        self.series_id = series_id  # ID of the series or ???
        self.rootdir = rootdir # directory Dicoms were loaded from, files for this series may be in subdirectories
        self.filenames = [] # list of filenames for the Dicom associated with this series
        self.loadtags = [] # loaded abbreviated tag->(name,value) maps, 1 for each of self.filenames
        self.imgcache = {} # image data cache, mapping index in self.filenames to arrays or None for non-images files
        self.tagcache = {} # tag values cache, mapping index in self.filenames to OrderedDict of tag->(name,value) maps

    def add_file(self, filename, loadtag):
        """Add a filename and abbreviated tag map to the series."""
        self.filenames.append(filename)
        self.loadtags.append(loadtag)

    def get_tag_object(self, index):
        """Get the object storing tag information from Dicom file at the given index."""
        if index not in self.tagcache:
            dcm = dicomio.read_file(self.filenames[index], stop_before_pixels=True)
            self.tagcache[index] = dcm

        return self.tagcache[index]

    def get_extra_tag_values(self):
        """Return the extra tag values calculated from the series tag info stored in self.filenames."""
        start, interval, numtimes = self.get_timestep_spec()
        extravals = {
            "NumImages": len(self.filenames),
            "TimestepSpec": "start: %i, interval: %i, # Steps: %i"
            % (start, interval, numtimes),
            "StartTime": start,
            "NumTimesteps": numtimes,
            "TimeInterval": interval,
        }

        return extravals

    def get_tag_values(self, names, index=0):
        """Get the tag values for tag names listed in `names' for image at the given index."""
        if not self.filenames:
            return ()

        dcm = self.get_tag_object(index)
        extravals = self.get_extra_tag_values()

        # TODO: kludge? More general solution of telling series apart
        # dcm.SeriesDescription=dcm.get('SeriesDescription',dcm.get('SeriesInstanceUID','???'))

        return tuple(str(dcm.get(n, extravals.get(n, ""))) for n in names)

    def get_pixel_data(self, index):
        """Get the pixel data array for file at position `index` in self.filenames, or None if no pixel data."""
        if index not in self.imgcache:
            try:
                dcm = dicomio.read_file(self.filenames[index])
                rslope = float(dcm.get("RescaleSlope", 1) or 1)
                rinter = float(dcm.get("RescaleIntercept", 0) or 0)
                img = dcm.pixel_array * rslope + rinter
            except:
                img = None # exceptions indicate that the pixel data doesn't exist or isn't readable so ignore

            self.imgcache[index] = img

        return self.imgcache[index]

    def add_series(self, series):
        """Add every loaded dcm file from DicomSeries object `series` into this series."""
        for f, loadtag in zip(series.filenames, series.loadtags):
            self.add_file(f, loadtag)

    def get_timestep_spec(self, tag="TriggerTime"):
        """Returns (start time, interval, num timesteps) triple."""
        times = sorted(set(int(loadtag.get(tag, 0)) for loadtag in self.loadtags))

        if not times or times == [0]:
            return 0.0, 0.0, 0.0
        else:
            if len(times) == 1:
                times = times * 2

            avgspan = np.average([b - a for a, b in zip(times, times[1:])])
            return times[0], avgspan, len(times)
