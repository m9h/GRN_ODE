"""A declared solver retry is different from tuning a numerical acceptance test."""

import pytest

from grn_memory.protocol_retries import integrate_engines


def test_only_solver_failure_triggers_fallback_and_all_requests_remain_visible():
    settings={"roadrunner":{"rtol":1e-12,"atol":1e-14},"copasi":{"rtol":1e-8,"atol":1e-10}}
    fallbacks={"copasi":{"rtol":1e-7,"atol":1e-9}}
    calls=[]
    def solver(path,times,trains,engine,**request):
        calls.append((engine,request))
        if engine=="copasi" and request["rtol"]==1e-8:
            raise ValueError("partial trajectory")
        return engine
    record={}
    traces=integrate_engines(solver,None,None,None,list(settings),settings,fallbacks,record)
    assert traces=={"roadrunner":"roadrunner","copasi":"copasi"}
    assert len(calls)==3
    assert record["integration_settings_used"]=={"roadrunner":settings["roadrunner"],"copasi":fallbacks["copasi"]}
    assert [a["status"] for a in record["solver_attempts"]["copasi"]]==["error","completed"]
    assert settings["copasi"]["rtol"]==1e-8
    # Even clearly different completed outputs do not cause a retry: the
    # independent comparison must report their disagreement to the caller.
    record={}
    traces=integrate_engines(lambda p,t,s,e,**k: 0 if e=="roadrunner" else 100,
                            None,None,None,list(settings),settings,fallbacks,record)
    assert traces["roadrunner"]!=traces["copasi"]
    assert len(record["solver_attempts"]["copasi"])==1


def test_final_failure_is_not_reclassified_as_a_completed_trajectory():
    record={}
    def fail(*args,**kwargs):
        raise RuntimeError("step limit")
    with pytest.raises(RuntimeError,match="step limit"):
        integrate_engines(fail,None,None,None,["copasi"],{"copasi":{"rtol":1e-8}},
                          {"copasi":{"rtol":1e-7}},record)
    assert [a["status"] for a in record["solver_attempts"]["copasi"]]==["error","error"]
    assert not record["integration_settings_used"]
