#
# Copyright 2020 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#

from vdsm.common import errors
from vdsm.storage import bitmaps
from vdsm.storage import constants as sc
from vdsm.storage import guarded
from vdsm.storage import qemuimg

from vdsm.storage.sdm.volume_info import VolumeInfo

from . import base


class Error(errors.Base):
    msg = ("Cannot add bitmap {self.bitmap} to "
           "volume {self.vol_id}: {self.reason}")

    def __init__(self, vol_id, bitmap, reason):
        self.vol_id = vol_id
        self.reason = reason
        self.bitmap = bitmap


class Job(base.Job):

    def __init__(self, job_id, host_id, vol_info, bitmap):
        super(Job, self).__init__(job_id, 'add_bitmap', host_id)
        self._vol_info = VolumeInfo(vol_info, host_id)
        self.bitmap = bitmap

    def _validate(self):
        if self._vol_info.volume.getFormat() != sc.COW_FORMAT:
            raise Error(
                self._vol_info.vol_id,
                self.bitmap,
                "volume is not in COW format")

        # validate that the bitmap doesn't exists on any volume on the chain
        for info in qemuimg.info(self._vol_info.path, backing_chain=True):
            if "format-specific" in info:
                bitmaps = info["format-specific"]["data"].get("bitmaps", [])
                bitmaps_names = {bitmap["name"] for bitmap in bitmaps}
                if self.bitmap in bitmaps_names:
                    raise Error(
                        self._vol_info.vol_id,
                        self.bitmap,
                        "Volume already contains the requested bitmap")

    def _run(self):
        with guarded.context(self._vol_info.locks):
            with self._vol_info.prepare():
                self._validate()
                with self._vol_info.volume_operation():
                    bitmaps.add_bitmap(self._vol_info.path, self.bitmap)
