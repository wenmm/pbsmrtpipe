
"""
Utility for running a testkit job through services as an alternative to
pbtestkit-runner.
"""

import logging
import os
import sys

from pbcommand.cli import (get_default_argparser_with_base_opts,
                           pacbio_args_runner)
from pbcommand.utils import setup_log
from pbcommand.services._service_access_layer import get_smrtlink_client
from pbcommand.services.cli import run_analysis_job
from pbcommand.validators import validate_file

from pbsmrtpipe.testkit.butler import ButlerWorkflow
from pbsmrtpipe.testkit.loader import parse_tests_from_testkit_json
from pbsmrtpipe.testkit.runner import run_butler_tests, write_nunit_output

log = logging.getLogger(__name__)


# FIXME evil dwells here
def _patch_test_cases_with_service_access_layer(test_cases,
                                                service_access_layer, job_id):
    """This must be called before the test cases are run"""
    for test_case in test_cases:
        test_case.__class__.service_access_layer = service_access_layer
        test_case.__class__.job_id = job_id
        for t in test_case:
            t.__class__.service_access_layer = service_access_layer
            t.__class__.job_id = job_id


def run_butler_tests_from_testkit_json(testkit_json, output_dir, output_xml,
                                       service_access_layer, services_job_id=None,
                                       nunit_out=None):

    butler = ButlerWorkflow.from_json(testkit_json)
    job_id = butler.job_id
    test_cases = parse_tests_from_testkit_json(testkit_json)
    _patch_test_cases_with_service_access_layer(test_cases,
                                                service_access_layer,
                                                job_id=services_job_id)
    log.info("running tests...")
    exit_code = run_butler_tests(
        test_cases=test_cases,
        output_dir=output_dir,
        output_xml=output_xml,
        job_id=job_id,
        requirements=butler.requirements)
    if nunit_out is not None:
        write_nunit_output(
            name=job_id,
            xunit_out=output_xml,
            nunit_out=nunit_out,
            requirements=butler.requirements,
            tests=butler.xray_tests)
    return exit_code


def run_services_testkit_job(host, port, testkit_json,
                             xml_out="test-output.xml",
                             nunit_out="nunit_out.xml",
                             ignore_test_failures=False,
                             time_out=1800, sleep_time=2,
                             import_only=False, test_job_id=None,
                             user=None, password=None):
    """
    Given a testkit.cfg and host/port parameters:
        1. convert the .cfg to a JSON file
        2. connect to the SMRTLink services and start the job, then block
           until it finishes
        3. run the standard test suite on the job output

    :param test_job_id: Means ONLY run the tests if a SL job id isn't provided
    :type test_job_id: int | None
    """
    sal = get_smrtlink_client(host, port, user, password)

    if test_job_id is not None:
        engine_job = sal.get_job_by_id(test_job_id)
        return run_butler_tests_from_testkit_json(
            testkit_json=testkit_json,
            output_dir=engine_job.path,
            output_xml=xml_out,
            service_access_layer=sal,
            services_job_id=test_job_id,
            nunit_out=nunit_out)

    butler = ButlerWorkflow.from_json(testkit_json)

    pipeline_id = butler.pipeline_id
    job_id = butler.job_id
    task_options = butler.get_task_options()

    log.info("job_id = {j}".format(j=job_id))
    log.info("pipeline_id = {p}".format(p=pipeline_id))
    log.info("url = {h}:{p}".format(h=host, p=port))

    service_entrypoints = butler.get_service_entry_points()

    for ep, dataset_xml in butler.entry_points.iteritems():
        log.info("Importing {x}".format(x=dataset_xml))
        sal.run_import_local_dataset(dataset_xml)
    if import_only:
        log.info("Skipping job execution")
        return 0
    log.info("starting analysis job...")
    # XXX note that workflow options are currently ignored
    engine_job = run_analysis_job(sal, job_id, pipeline_id,
                                  service_entrypoints, block=True,
                                  time_out=time_out,
                                  task_options=task_options,
                                  tags=butler.tags)

    exit_code = run_butler_tests_from_testkit_json(
        testkit_json=testkit_json,
        output_dir=engine_job.path,
        output_xml=xml_out,
        service_access_layer=sal,
        services_job_id=engine_job.id,
        nunit_out=nunit_out)
    if ignore_test_failures and engine_job.was_successful():
        return 0
    return exit_code


def args_runner(args):
    return run_services_testkit_job(
        host=args.host,
        port=args.port,
        testkit_json=args.testkit_json,
        xml_out=args.xml_out,
        nunit_out=args.nunit_out,
        ignore_test_failures=args.ignore_test_failures,
        time_out=args.time_out,
        sleep_time=args.sleep,
        import_only=args.import_only,
        test_job_id=args.test_job_id,
        user=args.user,
        password=args.password)


def get_parser():
    p = get_default_argparser_with_base_opts(
        version="0.1",
        description=__doc__)
    p.add_argument("testkit_json", help="Path to pbsmrtpipe Testkit JSON file", type=validate_file)
    p.add_argument("-u", "--host", dest="host", action="store",
                   default=os.environ.get("PB_SERVICE_HOST", "localhost"),
                   help="Hostname of SMRT Link server.  If this is anything other than 'localhost' you must supply authentication.")
    p.add_argument("-p", "--port", dest="port", action="store", type=int,
                   default=int(os.environ.get("PB_SERVICE_PORT", "8081")),
                   help="Services port number")
    p.add_argument("--user", dest="user", action="store",
                   default=os.environ.get("PB_SERVICE_AUTH_USER", None),
                   help="User to authenticate with (if using HTTPS)")
    p.add_argument("--password", dest="password", action="store",
                   default=os.environ.get("PB_SERVICE_AUTH_PASSWORD", None),
                   help="Password to authenticate with (if using HTTPS)")
    p.add_argument("-x", "--xunit", dest="xml_out", default="test-output.xml",
                   help="Output XUnit test results")
    p.add_argument("-n", "--nunit", dest="nunit_out", default="nunit_out.xml",
                   help="Optional NUnit output file, used for JIRA/Xray integration.")
    p.add_argument("-t", "--timeout", dest="time_out", type=int, default=1800,
                   help="Timeout for blocking after job submission")
    p.add_argument("-s", "--sleep", dest="sleep", type=int, default=2,
                   help="Sleep time after job submission")
    p.add_argument("--ignore-test-failures", dest="ignore_test_failures",
                   action="store_true",
                   help="Only exit with non-zero return code if the job "+
                        "itself failed, regardless of test outcome")
    p.add_argument("--import-only", dest="import_only", action="store_true",
                   help="Import datasets without running pipeline")
    p.add_argument("--only-tests", dest="test_job_id", action="store",
                   type=int, default=None,
                   help="Run tests on an existing smrtlink job")
    return p


def main(argv=sys.argv):
    return pacbio_args_runner(
        argv=argv[1:],
        parser=get_parser(),
        args_runner_func=args_runner,
        alog=log,
        setup_log_func=setup_log)

if __name__ == "__main__":
    sys.exit(main())
