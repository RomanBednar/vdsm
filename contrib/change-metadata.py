#!/usr/bin/python3
"""
Ugly script to help verify a patch for metadata missing/invalid keys.
"""

import argparse
import logging
import os
import pprint
import stat
import sys

from vdsm.storage.blockSD import METADATA_BASE_V5, METADATA_SLOT_SIZE_V5
from vdsm.storage import constants as sc
from vdsm.storage import directio
from vdsm.storage import misc
from vdsm.storage import volumemetadata
from vdsm import client

_fieldmap = dict(format=sc.FORMAT, type=sc.TYPE, voltype=sc.VOLTYPE,
                 disktype=sc.DISKTYPE, capacity=sc.CAPACITY, ctime=sc.CTIME,
                 domain=sc.DOMAIN, image=sc.IMAGE, description=sc.DESCRIPTION,
                 parent=sc.PUUID, legality=sc.LEGALITY,
                 generation=sc.GENERATION)

pp = pprint.PrettyPrinter(indent=4)

def metadata_offset(slot):
    return METADATA_BASE_V5 + slot * METADATA_SLOT_SIZE_V5

def format(md_dict, domain):
    md_dict['domain'] = domain
    lines = []
    for key in sorted(md_dict.keys()):
        try:
            lines.append("%s=%s\n" % (_fieldmap[key], md_dict[key]))
        except KeyError:
            # Intentionally removed key should be just skipped here.
            pass
    lines.append("EOF\n")
    data = "".join(lines).encode("utf-8")
    data = data.ljust(METADATA_SLOT_SIZE_V5, b"\0")

    return data

def write_metadata_block(slot, data, path):
    with directio.open(path, "r+") as f:
        f.seek(metadata_offset(slot))
        f.write(data)


def parse_var(s):
    """
    Parse a key, value pair, separated by '='
    That's the reverse of ShellArgs.

    On the command line (argparse) a declaration will typically look like:
        foo=hello
    or
        foo="hello world"
    """
    items = s.split('=')
    # Remove blanks around keys.
    key = items[0].strip()
    if len(items) > 1:
        # Rejoin the rest.
        value = '='.join(items[1:])
    return (key, value)


def parse_vars(items):
    """
    Parse a series of key-value pairs and return a dictionary
    """
    d = {}

    if items:
        for item in items:
            key, value = parse_var(item)
            d[key] = value
    return d

def is_block(path):
    mode = os.stat(path).st_mode
    return stat.S_ISBLK(mode)

parser = argparse.ArgumentParser(description="...")

parser.add_argument("--write",
                    metavar="KEY=VALUE",
                    nargs='+',
                    help="Set a number of key-value pairs "
                         "(do not put spaces before or after the = sign). "
                         "If a value contains spaces, you should define "
                         "it with double quotes: foo='this is a sentence' "
                         "Note that values are always treated as strings."
                         "To remove a key use empty value: foo=''"
                         "Valid keys:{}".format([x for x in _fieldmap.keys()]))

parser.add_argument("--read",
                    dest="read",
                    action="store_true",
                    help="Read and dump metadata only.",
                    )


parser.add_argument("--sd_id",
                    dest="sd_id",
                    required=True,
                    help="Storage domain ID/Volume group name",
                    )

parser.add_argument("--vol_id",
                    dest="vol_id",
                    required=True,
                    help="Volume ID (not image ID!)",
)

args = parser.parse_args()

if args.read and args.write:
    logging.error("Read and write is mutually exclusive.")
    parser.print_usage()
    sys.exit(1)
elif not args.read and not args.write:
    logging.error("Choose from read or write actions.")
    parser.print_usage()
    sys.exit(1)

# Dict of user requested key=value pairs to be written.
values_dict = parse_vars(args.write)

# Path to metadata device.
# TODO: this will not work for file SD
meta_path = "/dev/{}/metadata".format(args.sd_id)

if is_block(meta_path):

    logging.info("Block storage domain detected.")

    # Get storage domain dump output using vdsm client.
    serv = client.connect(host="localhost")
    sd_dump = serv.StorageDomain.dump(sd_id=args.sd_id)

    # Find a metadata slot for given volume.
    try:
        slot = sd_dump['volumes'][args.vol_id]['mdslot']
    except KeyError:
        logging.error("Can not get slot number for image.")
        sys.exit(1)

    # Get offset of metadata slot, read data, and parse.
    start_offset = metadata_offset(slot)
    raw_md = misc.readblock(meta_path, start_offset, METADATA_SLOT_SIZE_V5)
    md_lines = raw_md.rstrip(b"\0").splitlines()
    parsed_md = volumemetadata.dump(md_lines)

else:
    logging.error("File storage domain not supported yet.")
    sys.exit(1)

if args.read:
    pp.pprint(parsed_md)
    sys.exit(0)

# Write only if we have some values from user.
if bool(values_dict):
    for k, v in values_dict.items():
        # User specified emtpy value - remove this key.
        if not v:
            parsed_md.pop(k, None)
        else:
            # Set the value in dict to one specified by user.
            parsed_md[k] = v

    # Flip md dict to storage format and add domain info.
    fmt = format(parsed_md, args.sd_id)

    # Write data.
    write_metadata_block(slot, fmt, meta_path)


