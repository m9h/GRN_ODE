"""A control run must preserve the complete original failed-case inventories."""
from copy import deepcopy
import json
import shutil
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from scripts import diagnose_marhl_controls as diagnostic


def test_conda_heyoka_version_without_wheel_metadata(monkeypatch):
    monkeypatch.setitem(sys.modules,'heyoka',SimpleNamespace(__version__='7.13.2'))
    original_version=diagnostic.version
    def conda_metadata(name):
        if name=='heyoka':
            from importlib.metadata import PackageNotFoundError
            raise PackageNotFoundError(name)
        return original_version(name)
    monkeypatch.setattr(diagnostic,'version',conda_metadata)
    versions=diagnostic.runtime_versions()
    assert versions['heyoka']=='7.13.2'
    assert all(versions[p] for p in ('mpmath','numpy','pandas','libroadrunner','python-libsbml'))


@pytest.fixture(scope='module')
def plan():
    return diagnostic.prepare_plan()


def test_all_twelve_arms_of_both_cases_are_retained(plan):
    assert len(plan['cases'])==2
    assert all(len(c['branches'])==12 for c in plan['cases'].values())
    required={bid for c in plan['cases'].values() for bid in c['branches'].values()}
    assert len(required)==18 and required==set(plan['required_branch_ids'])
    selected=set(plan['selected_branch_ids']);excluded=set(plan['excluded_original_failed_branch_ids'])
    assert len(selected)==15 and len(excluded)==3 and not selected&excluded
    assert selected|excluded==required and selected==set(plan['selected_branches'])
    assert plan['original_case_count']==26 and plan['original_passed_cases']==24
    assert not plan['case_recovery_claimed']


def test_missing_original_control_cannot_be_planned(tmp_path):
    source=diagnostic.ROOT/'results/catalog-paired/BIOMD0000000039.json'
    report=json.loads(source.read_text())
    archive=report['branch_archive']['file']
    shutil.copyfile(source.parent/archive,tmp_path/archive)
    case=next(c for c in report['cases'].values() if c['status']!='passed')
    case['branches'].pop('none_sham')
    (tmp_path/source.name).write_text(json.dumps(report))
    with pytest.raises(ValueError,match='Original case arm inventory'):
        diagnostic.prepare_plan(original_directory=tmp_path)


@pytest.mark.parametrize('field,value',[('performed_resets',997),('absolute_time_preserved',False)])
def test_incomplete_saved_integration_cannot_be_reused(field,value):
    directory=diagnostic.ROOT/'results/catalog-paired-taylor-marhl'
    report=json.loads((directory/'report.json').read_text())
    record=json.loads((directory/report['branches'][0]['file']).read_text())
    evidence=deepcopy(record['integrations']['taylor192'])
    evidence['request']=diagnostic.REQUESTS['taylor192']
    times=np.load(directory/record['traces']['taylor192']['file'])['times']
    diagnostic.validate_outcome('taylor192',evidence,times,record['reset_trains'])
    evidence[field]=value
    with pytest.raises(ValueError,match='reset and precision'):
        diagnostic.validate_outcome('taylor192',evidence,times,record['reset_trains'])


def test_truncated_cached_arrays_cannot_be_reused(tmp_path):
    source=diagnostic.ROOT/'results/catalog-paired-taylor-marhl/untreated_baseline-taylor192.npz'
    with np.load(source,allow_pickle=False) as data:
        arrays={k:data[k].copy() for k in data.files}
    times=arrays['times'].copy()
    arrays['times']=arrays['times'][:-1];arrays['values']=arrays['values'][:-1]
    path=tmp_path/'truncated.npz';np.savez_compressed(path,**arrays)
    with pytest.raises(ValueError,match='Complete original trajectory'):
        diagnostic.load_trace(path,{'sha256':diagnostic.digest(path)},times)
