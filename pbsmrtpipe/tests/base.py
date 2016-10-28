import os
import unittest
import platform
import tempfile
import logging
import shutil
import getpass
from pbsmrtpipe.engine import backticks

from pbcommand.utils import which

TEST_DIR = os.path.dirname(__file__)
TEST_DATA_DIR = os.path.join(TEST_DIR, 'data')
SIV_TEST_DATA_DIR = '/pbi/dept/secondary/siv/testdata'
# this is necessary for test jobs to write a tmp shared space for jobs that
# are submitted to the cluster
CLUSTER_SHARED_TMP_DIR = '/mnt/secondary/Share/tmp/'
IS_PACBIO_CLUSTER = os.path.exists(CLUSTER_SHARED_TMP_DIR) and "PB_USE_CLUSTER" in os.environ

DEBUG = True
SLOW_ATTR = 'slow'
CLUSTER_CMD = "qsub"
NO_CLUSTER_COMMAND_MESSAGE = "Unable to find cluster exe '{c}'".format(c=CLUSTER_CMD)

_log = logging.getLogger(__name__)


def was_backticks_successful(cmd):
    rcode, _, _, _ = backticks(cmd, )
    return rcode == 0


def _is_qsub_accessible():
    cluster_exe = which(CLUSTER_CMD)
    if cluster_exe is None:
        m = "Unable to find '{c}'. Cluster tests will be skipped.".format(c=CLUSTER_CMD)
        _log.warn(m)
        print m
    else:
        m = "Found cluster exe '{e}'. Cluster tests will run. (This is setup for pacbio SGE 'production' queue).".format(e=cluster_exe)
        print m
        _log.warn(m)
    return cluster_exe is not None

HAS_CLUSTER_QSUB = _is_qsub_accessible() and "PB_USE_CLUSTER" in os.environ


def get_data_file(file_name):
    # Can't have 'test' in the name or nose will think it's a test
    x = os.path.join(TEST_DATA_DIR, file_name)

    if os.path.exists(x):
        return x
    else:
        raise IOError("Unable to find test file '{x}'".format(x=x))


def _is_local_dev_mk():
    return platform.system() == 'Darwin' and getpass.getuser() == 'mkocher'


def _get_temp_file(suffix, dir_):
    t = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir=dir_)
    t.close()
    return t.name


def get_temp_file(suffix="", dir_=None):
    return _get_temp_file(suffix, dir_=dir_)


def get_temp_file_name(dir_name, suffix):
    return _get_temp_file(suffix, dir_name)


def get_temp_dir(suffix=""):
    """This will make subdir in the root tmp dir"""
    return tempfile.mkdtemp(dir=None, suffix=suffix)


def get_temp_cluster_dir(suffix=None):
    # Safe guard
    d = CLUSTER_SHARED_TMP_DIR if IS_PACBIO_CLUSTER else None
    return tempfile.mkdtemp(dir=d, suffix=suffix)


def get_temp_cluster_file(suffix):
    return _get_temp_file(suffix, dir_=CLUSTER_SHARED_TMP_DIR)


def _write_temp_file(dir_name, s, suffix=None):
    n = get_temp_file_name(dir_name, suffix)
    with open(n, 'w') as f:
        f.write(s)
    _log.debug("writing to {n}".format(n=n))


class TestDirBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        temp_dir = get_temp_dir()
        cls.temp_dir = temp_dir
        _log.debug("creating temp_dir {t}".format(t=cls.temp_dir))

    @classmethod
    def tearDownClass(cls):
        if not DEBUG:
            if hasattr(cls, 'temp_dir'):
                if os.path.exists(cls.temp_dir):
                    if not _is_local_dev_mk():
                        _log.debug("removing temp dir {d}".format(d=cls.temp_dir))
                        shutil.rmtree(cls.temp_dir)
