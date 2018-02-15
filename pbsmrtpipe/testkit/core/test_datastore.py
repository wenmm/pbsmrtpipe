
import unittest
import os
import logging
import re

from pbcommand.pb_io import (load_report_from_json, load_report_spec_from_json)
from pbcommand.validators import validate_report
from pbcommand.models import FileTypes, DataStore
from pbcore.io import getDataSetUuid

from .base import TestBase
from pbsmrtpipe.testkit.base import monkey_patch
from pbsmrtpipe.testkit.validators2 import (ValidateFasta, ValidateJsonReport)

try:
    import pbreports
    HAS_PBREPORTS = True
except ImportError:
    HAS_PBREPORTS = False

log = logging.getLogger(__name__)


def _to_ds_json(job_dir):
    return os.path.join(job_dir, "workflow", "datastore.json")


@monkey_patch
class TestDataStore(TestBase):

    """
    Test to see of the core job directory structure and files exist
    """
    DIRS = ('html', 'workflow', 'tasks')

    def test_load_datastore_from_file(self):
        """
        Can load Datastore from Json
        :return:
        """
        ds = DataStore.load_from_json(_to_ds_json(self.job_dir))
        self.assertIsInstance(ds, DataStore)


@monkey_patch
class TestDataStoreFiles(TestBase):

    """
    Load Files by type in datastore and validate them using pbvalidate
    """

    DATASTORE_FILE_VALIDATORS = (ValidateFasta, ValidateJsonReport)


@monkey_patch
class TestDataStoreFileLabels(TestBase):

    def test_datastore_file_name_and_description(self):
        """
        Make sure output files have non-blank name and description.
        """
        ds = DataStore.load_from_json(_to_ds_json(self.job_dir))
        rx = re.compile(r'[a-zA-Z0-9]{1,}')

        for fd in ds.files.values():
            for x in (fd.name, fd.description):
                self.assertTrue(rx.search(x))


class TestDataStoreUuids(TestBase):
    """
    Verify that report and DataSet UUIDs are propagated to the datastore.
    """

    def test_datastore_report_file_uuid(self):
        """Test that the DataStore file and the Underlying Report have the same UUID"""
        ds = DataStore.load_from_json(_to_ds_json(self.job_dir))
        n_tested = 0
        for ds_file in ds.files.values():
            if ds_file.file_type_id == FileTypes.REPORT.file_type_id:
                rpt = load_report_from_json(ds_file.path)
                emsg = "{p}: {u1} != {u2}".format(
                                     p=ds_file.path,
                                     u1=rpt.uuid,
                                     u2=ds_file.uuid)
                # by convention the DS UUID and the Report UUID should the same value
                self.assertEqual(rpt.uuid, ds_file.uuid, emsg)
                n_tested += 1

        if n_tested == 0:
            raise unittest.SkipTest("Warning. No Report JSON files in datastore.")

    def test_datastore_dataset_file_uuid(self):
        """Test that the DataStore file and the Underlying Report have the same UUID"""
        dataset_type_ids = FileTypes.ALL_DATASET_TYPES().keys()

        ds = DataStore.load_from_json(_to_ds_json(self.job_dir))

        n_tested = 0
        for ds_file in ds.files.values():
            if ds_file.file_type_id in dataset_type_ids:
                path = ds_file.path
                dsf_uuid = ds_file.uuid
                uuid = getDataSetUuid(path)
                self.assertEqual(uuid, dsf_uuid,
                                     "{p}: {u1} != {u2}".format(
                                     p=path,
                                     u1=uuid,
                                     u2=dsf_uuid))
                n_tested += 1

        if n_tested == 0:
            raise unittest.SkipTest("Warning. No DataSet XML files in datastore.")


class TestReports(TestBase):
    """
    Validate Report JSON files against AVRO schema and specifications.
    """

    # These will be report types will be ignored in the Report Spec lookup.
    INTERNAL_REPORTS = ('pbsmrtpipe',)

    def setUp(self):
        # FIXME This will change at some point
        if HAS_PBREPORTS:
            self._specs = {}
            spec_path = os.path.join(os.path.dirname(pbreports.__file__),
                                     "report", "specs")
            for file_name in os.listdir(spec_path):
                if file_name.endswith(".json"):
                    path = os.path.join(spec_path, file_name)
                    spec = load_report_spec_from_json(path)
                    self._specs[spec.id] = spec
        else:
            self._specs = None

    def _validate_datastore_reports(self, validate_func):

        ds = DataStore.load_from_json(_to_ds_json(self.job_dir))

        # found one or more valid Report
        have_reports = True

        for ds_file in ds.files.values():
            if ds_file.file_type_id == FileTypes.REPORT.file_type_id:
                try:
                    _ = validate_func(ds_file.path)
                except ValueError as e:
                    self.fail("Report validation failed:\n{e}".format(e=str(e)))
                else:
                    have_reports = True

        if not have_reports:
            raise unittest.SkipTest("No Report JSON files in datastore.")
        return have_reports

    def test_datastore_report_schema_validation(self):
        self._validate_datastore_reports(validate_report)

    def test_datastore_report_spec_validation(self):
        def _validate_against_spec(path):
            # always load the Report JSON to make sure it valid with respect to the Report core schema
            rpt = load_report_from_json(path)

            if rpt.id in self.INTERNAL_REPORTS:
                raise unittest.SkipTest("Ignoring internal report type '{}'".format(rpt.id))

            if self._specs is None:
                raise unittest.SkipTest("Can't find report specs.")

            spec = self._specs.get(rpt.id, None)
            if spec is None:
                self.fail("No spec found for report {r}".format(r=rpt.id))
            else:
                return spec.validate_report(rpt)
        self._validate_datastore_reports(_validate_against_spec)
