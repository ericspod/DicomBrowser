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

import os
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from io import BytesIO
from glob import glob
from warnings import warn

import numpy as np
from pydicom import dicomio, datadict, errors


# attribute names of default columns in the series list, this can be changed to pull out different attribute names for columns
SERIES_LIST_COLUMNS = (
    "SeriesInstanceUID",
    "SeriesNumber",
    "NumImages",
    "PatientName",
    "SeriesDescription",
    "StudyDescription",
)

# names of columns in attribute tree, this shouldn't ever change
ATTR_TREE_COLUMNS = ("Name", "Tag", "Value")

# list of attributes to initially load when a directory/file is scanned, loading only these speeds up scanning immensely
LOAD_ATTRS = (
    "SeriesInstanceUID",
    "TriggerTime",
    "PatientName",
    "SeriesDescription",
    "SeriesNumber",
    "StudyDescription",
)

# keyword/full name pairs for extra properties not represented as Dicom attributes
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


def get_2d_equivalent_image(img):
    """Given an array `img` of some arbitrary dimensions, attempt to choose a valid 2D gray/RGB/RGBA image from it."""
    ndim = img.ndim
    shape = img.shape
    color_dim = ndim > 2 and shape[-1] in (1, 3, 4)

    if ndim <= 2 or (ndim == 3 and color_dim):  # 0D array, 1D array, 2D grayscale or 2D RGB(A)
        if ndim < 2:
            warn(f"Image has unusual shape {shape}, attempting to visualise")

        return img
    elif ndim == 3:  # 3D grayscale
        warn(f"Image is volume with shape {shape}, using mid-slice")
    elif ndim == 4 and color_dim:
        warn(f"Image is RGB(A) volume with shape {shape}, using mid-slice")
    else:
        warn(f"Image is unknown volume with shape {shape}, using mid-slices")

    # attempt to slice the volume in every dimension that's not height, width, or the channels
    stop = 3 if color_dim else 2  # dimensions to not slice in, ie. (height,width) or (height,width,channels)
    slices = [s // 2 for s in shape[:-stop]] + [slice(None)] * stop
    return img[tuple(slices)]


def get_scaled_image(dcm):
    """Return image data from `dcm` scaled using slope and intercept values."""
    try:
        rslope = float(dcm.get("RescaleSlope", 1) or 1)
        rinter = float(dcm.get("RescaleIntercept", 0) or 0)
        img = dcm.pixel_array * rslope + rinter
        return img
    except (KeyError, ValueError, AttributeError):
        return None


def load_dicom_file(filename):
    """Load the Dicom file `filename`, returns the filename and an abbreviated attribute dictionary."""
    try:
        dcm = dicomio.read_file(filename, stop_before_pixels=True)
        attrs = {t: dcm.get(t) for t in LOAD_ATTRS if t in dcm}
        return filename, attrs
    except errors.InvalidDicomError:
        pass


def load_dicom_dir(rootdir, statusfunc=lambda s, c, n: None, numprocs=None):
    """
    Load all the Dicom files from `rootdir` using `numprocs` number of processes. This will attempt to load each file
    found in `rootdir` and store from each file the attributes defined in LOAD_ATTRS. The filenames and the loaded
    attributes for Dicom files are stored in a DicomSeries object representing the acquisition series each file belongs
    to. The `statusfunc` callback is used to indicate loading status, taking as arguments a status string, count of
    loaded objects, and the total number to load. A status string of '' indicates loading is done. The default value
    causes no status indication to be made. Return value is a sequence of DicomSeries objects in no particular order.
    """
    allfiles = list(filter(os.path.isfile, glob(rootdir + "/**", recursive=True)))

    numfiles = len(allfiles)
    series = {}
    count = 0

    if numfiles == 0:
        return []

    with ProcessPoolExecutor(max_workers=numprocs) as p:
        futures = [p.submit(load_dicom_file, f) for f in allfiles]

        for count, future in enumerate(as_completed(futures)):
            result = future.result()
            if result is not None:
                filename, dcm = result
                seriesid = dcm.get("SeriesInstanceUID", "???")
                if seriesid not in series:
                    series[seriesid] = DicomSeries(seriesid, rootdir)

                series[seriesid].add_file(filename, dcm)

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
            nfilename = f"{filename}?{n}"
            s = BytesIO(z.read(n))

            try:
                dcm = dicomio.read_file(s)
            except errors.InvalidDicomError:
                pass  # ignore files which aren't Dicom files, various exceptions raised so no concise way to do this
            else:
                seriesid = dcm.get("SeriesInstanceUID", "???")

                if seriesid not in series:
                    series[seriesid] = DicomSeries(seriesid, nfilename)

                # need to load image data now since we don't want to reload the zip file later when an image is viewed
                img = get_scaled_image(dcm)  # attempt to create the image array, store None if this doesn't work

                s = series[seriesid]
                s.add_file(nfilename, dcm, dcm, img)

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
    Dicoms should be organized by series. This type will also cache loaded Dicom attrs and images
    """

    def __init__(self, series_id, rootdir):
        self.series_id = series_id  # ID of the series or ???
        self.rootdir = rootdir  # directory Dicoms were loaded from, files for this series may be in subdirectories
        self.filenames = []  # list of filenames for the Dicom associated with this series
        self.loadattrs = []  # loaded abbreviated attr->(name,value) maps, 1 for each of self.filenames
        self.imgcache = {}  # image data cache, mapping index in self.filenames to arrays or None for non-images files
        self.attrcache = {}  # attribute cache, mapping index in self.filenames to dict of attr->(name,value) mappings

    def add_file(self, filename, loadattr, attrs=None, img=None):
        """
        Add a filename and abbreviated attribute map `loadattr` to the series. Further attributes and image data given
        in `attrs` and `img` will be be cached if provided.
        """
        self.filenames.append(filename)
        self.loadattrs.append(loadattr)

        if attrs is not None or img is not None:
            idx = len(self.filenames) - 1
            self.attrcache[idx] = attrs
            self.imgcache[idx] = img

    def sort_filenames(self):
        """Concurrently sort filenames and associated attributes lists."""
        self.filenames, self.loadattrs = zip(*sorted(zip(self.filenames, self.loadattrs)))

    def get_attr_object(self, index):
        """Get the object storing attr information from Dicom file at the given index."""
        if index not in self.attrcache:
            dcm = dicomio.read_file(self.filenames[index], stop_before_pixels=True)
            self.attrcache[index] = dcm

        return self.attrcache[index]

    def get_extra_attr_values(self):
        """Return the extra attr values calculated from the series attr info stored in self.filenames."""
        start, interval, numtimes = self.get_timestep_spec()
        extravals = {
            "NumImages": len(self.filenames),
            "TimestepSpec": f"start: {start}, interval: {interval}, # Steps: {numtimes}",
            "StartTime": start,
            "NumTimesteps": numtimes,
            "TimeInterval": interval,
        }

        return extravals

    def get_attr_values(self, names, index=0):
        """Get the attr values for attr names listed in `names` for image at the given index."""
        if not self.filenames:
            return ()

        dcm = self.get_attr_object(index)
        extravals = self.get_extra_attr_values()

        # TODO: kludge? More general solution of telling series apart
        # dcm.SeriesDescription=dcm.get('SeriesDescription',dcm.get('SeriesInstanceUID','???'))

        return tuple(str(dcm.get(n, extravals.get(n, ""))) for n in names)

    def get_pixel_data(self, index):
        """Get the pixel data array for file at position `index` in self.filenames, or None if no pixel data."""
        if index not in self.imgcache:
            dcm = dicomio.read_file(self.filenames[index])
            img = get_scaled_image(dcm)
            self.imgcache[index] = img

        return self.imgcache[index]

    def add_series(self, series):
        """Add every loaded dcm file from DicomSeries object `series` into this series."""
        for f, loadattr in zip(series.filenames, series.loadattrs):
            self.add_file(f, loadattr)

    def get_timestep_spec(self, attr="TriggerTime"):
        """Returns (start time, interval, num timesteps) triple."""
        times = sorted(set(int(loadattr.get(attr, 0)) for loadattr in self.loadattrs))

        if not times or times == [0]:
            return 0.0, 0.0, 0.0
        else:
            if len(times) == 1:
                times = times * 2

            avgspan = np.average([b - a for a, b in zip(times, times[1:])])
            return times[0], avgspan, len(times)
