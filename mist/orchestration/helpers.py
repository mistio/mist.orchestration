import os
import glob
import copy
import urllib.request
import urllib.parse
import urllib.error
import tarfile
import zipfile
import logging

from mist.api import config

logging.basicConfig(level=config.PY_LOG_LEVEL,
                    format=config.PY_LOG_FORMAT,
                    datefmt=config.PY_LOG_FORMAT_DATE)
log = logging.getLogger(__name__)


def download(url, path=None):
    """Download a file over HTTP"""
    log.debug("Downloading %s.", url)
    name, headers = urllib.request.urlretrieve(url, path)
    log.debug("Downloaded to %s.", name)
    return name


def unpack(path, dirname='.'):
    """Unpack a tar or zip archive"""
    if tarfile.is_tarfile(path):
        log.debug("Unpacking '%s' tarball in directory '%s'.", path, dirname)
        tfile = tarfile.open(path)
        if hasattr(tfile, 'extractall'):
            tfile.extractall(dirname)
        else:
            for tarinfo in tfile:
                if tarinfo.isdir():
                    tarinfo = copy.copy(tarinfo)
                    tarinfo.mode = 0o700
                tfile.extract(tarinfo, dirname)
    elif zipfile.is_zipfile(path):
        log.debug("Unpacking '%s' zip archive in directory '%s'.",
                  path, dirname)
        zfile = zipfile.ZipFile(path)
        if hasattr(zfile, 'extractall'):
            zfile.extractall(dirname)
        else:
            for member_path in zfile.namelist():
                dirname, filename = os.path.split(member_path)
                if dirname and not os.path.exists(dirname):
                    os.makedirs(dirname)
                zfile.extract(member_path, dirname)
    else:
        raise Exception("File '%s' is not a valid tar or zip archive." % path)


def find_path(dirname='.', filename=''):
    """Find absolute path of script"""
    dirname = os.path.abspath(dirname)
    if not os.path.isdir(dirname):
        log.warning("Directory '%s' doesn't exist, will search in '%s'.",
                    dirname, os.getcwd())
        dirname = os.getcwd()
    while True:
        log.debug("Searching for entrypoint '%s' in directory '%s'.",
                  filename or 'main.*', dirname)
        ldir = os.listdir(dirname)
        if not ldir:
            raise Exception("Directory '%s' is empty." % dirname)
        if len(ldir) == 1:
            path = os.path.join(dirname, ldir[0])
            if os.path.isdir(path):
                dirname = path
                continue
            break
        if filename:
            path = os.path.join(dirname, filename)
            if os.path.isfile(path):
                break
        paths = glob.glob(os.path.join(dirname, 'main.*'))
        if not paths:
            raise Exception("No files match 'main.*' in '%s'." % dirname)
        if len(paths) > 1:
            log.warning("Multiple files match 'main.*' in '%s'.", dirname)
        path = paths[0]
        break
    log.info("Found entrypoint '%s'.", path)
    return path
