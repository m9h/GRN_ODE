"""Check complete cloud selections and original archive identity without network."""
from copy import deepcopy
import stat
import zipfile

import pytest
from scripts import collect_francois_native_capture as collector

REVISION='a'*40

@pytest.fixture
def api():
    run={'head_sha':REVISION,'path':collector.WORKFLOW,'head_branch':collector.BRANCH,
         'event':'workflow_dispatch','id':100,'run_attempt':1}
    gate={'id':1000,'run_id':100,'run_attempt':1,'head_sha':REVISION,'name':'validation','status':'completed','conclusion':'success'}
    rows=[gate]+[{'id':2000+i,'run_id':100,'run_attempt':1,'head_sha':REVISION,
                  'name':f'francois-native-branch-{i}','status':'queued','conclusion':None} for i in range(41)]
    return run,{'total_count':42,'jobs':rows}

def test_all_actual_jobs_are_bound(api):
    result=collector.bind(*api,REVISION)
    assert len(result['selected'])==41 and result['full_original_cases']==118
    assert [r['index'] for r in result['selected']]==list(range(41))
    assert len({r['record_id'] for r in result['selected']})==41

@pytest.mark.parametrize('change',[
    lambda r,j:j['jobs'].pop(),
    lambda r,j:j['jobs'][0].update(status='queued',conclusion=None),
    lambda r,j:j['jobs'][0].update(conclusion='failure'),
    lambda r,j:j['jobs'][1].update(head_sha='b'*40),
    lambda r,j:j['jobs'][1].update(id=True),
    lambda r,j:j['jobs'][1].update(name='francois-native-branch-99'),
    lambda r,j:j['jobs'][1].update(id=j['jobs'][2]['id']),
    lambda r,j:r.update(event='push'),
    lambda r,j:r.update(head_branch='different'),
])
def test_partial_or_wrong_producer_binding_is_rejected(api,change):
    run,jobs=deepcopy(api);change(run,jobs)
    with pytest.raises(ValueError):collector.bind(run,jobs,REVISION)

def test_artifact_bound_to_source_and_exact_attempt(api):
    selection=collector.bind(*api,REVISION);row=selection['selected'][0]
    artifact={'name':row['artifact_name'],'expired':False,'size_in_bytes':100,
              'digest':'sha256:'+'f'*64,'workflow_run':{'id':100,'head_sha':REVISION}}
    collector.validate_artifact(artifact,row,selection)
    for field,value in [('name','francois-native-branch-0-attempt-2'),('expired',True),('digest',''),('size_in_bytes',0)]:
        changed=deepcopy(artifact);changed[field]=value
        with pytest.raises(ValueError):collector.validate_artifact(changed,row,selection)
    artifact['workflow_run']['head_sha']='b'*40
    with pytest.raises(ValueError):collector.validate_artifact(artifact,row,selection)

@pytest.mark.parametrize('name',['../execution.json','/execution.json','nested/execution.json','unexpected.txt'])
def test_unsafe_zip_member_rejected(tmp_path,name):
    archive=tmp_path/'original.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr(name,b'{}')
    with pytest.raises(ValueError):collector.extract(archive,tmp_path/'out')
    assert archive.is_file()

def test_symlink_zip_member_rejected(tmp_path):
    archive=tmp_path/'original.zip';item=zipfile.ZipInfo('execution.json')
    item.create_system=3;item.external_attr=(stat.S_IFLNK|0o777)<<16
    with zipfile.ZipFile(archive,'w') as z:z.writestr(item,'outside')
    with pytest.raises(ValueError):collector.extract(archive,tmp_path/'out')

def test_missing_required_record_rejected(tmp_path):
    archive=tmp_path/'original.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('protocol.xml','<sbml/>')
    with pytest.raises(ValueError,match='execution'):collector.extract(archive,tmp_path/'out')

def test_known_members_are_preserved_byte_identical(tmp_path):
    archive=tmp_path/'original.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('execution.json','{}\n');z.writestr('protocol.xml','<sbml/>\n')
    files=collector.extract(archive,tmp_path/'out')
    assert set(files)=={'execution.json','protocol.xml'}
    assert (tmp_path/'out/protocol.xml').read_bytes()==b'<sbml/>\n'

def test_pending_jobs_do_not_become_completed_or_trigger_trials(api,tmp_path):
    run,jobs=api;selection=collector.bind(run,jobs,REVISION)
    snapshots=tmp_path/'api';snapshots.mkdir()
    for name,value in [('run',run),('jobs',jobs),('artifacts',{'total_count':0,'artifacts':[]})]:
        collector.work.write(snapshots/(name+'.json'),value)
    result=collector.collect(selection,snapshots,tmp_path/'archives',tmp_path/'collection')
    assert result['pending_indices']==list(range(41))
    assert result['verified_complete_arrays']==0 and result['selected_trial_audit'] is None
    assert not result['complete_native_attempt_coverage'] and not result['whole_model_pass_claimed']

def test_terminal_missing_output_is_not_a_numerical_result(api,tmp_path):
    run,jobs=api;jobs['jobs'][1].update(status='completed',conclusion='failure')
    selection=collector.bind(run,jobs,REVISION);snapshots=tmp_path/'api';snapshots.mkdir()
    for name,value in [('run',run),('jobs',jobs),('artifacts',{'total_count':0,'artifacts':[]})]:
        collector.work.write(snapshots/(name+'.json'),value)
    result=collector.collect(selection,snapshots,tmp_path/'archives',tmp_path/'collection')
    assert result['missing_artifacts']==[{'index':0,'job_conclusion':'failure'}]
    assert len(result['pending_indices'])==40 and result['selected_trial_audit'] is None
