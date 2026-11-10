"""Explicit, bounded integration retries for solver failures in native protocols."""


def integrate_engines(trajectory, path, times, trains, engines, settings, fallbacks, record):
    """Record requested/used settings and preserve every failed attempt.

A fallback is tried only when the trajectory function raises, never because a
completed trajectory disagrees with an independent engine. The caller must
still compare every resulting sample at the unchanged acceptance tolerance.
"""
    traces = {}
    record["solver_attempts"] = {}
    record["integration_settings_used"] = {}
    for engine in engines:
        requests = [settings[engine]]
        if engine in fallbacks and fallbacks[engine] != settings[engine]:
            requests.append(fallbacks[engine])
        attempts = record["solver_attempts"][engine] = []
        for index, request in enumerate(requests):
            attempt = {"settings":dict(request)}
            attempts.append(attempt)
            try:
                traces[engine] = trajectory(path,times,trains,engine,**request)
            except (ValueError,RuntimeError) as exc:
                attempt.update({"status":"error","error":f"{type(exc).__name__}: {exc}"})
                if index == len(requests)-1:
                    raise
            else:
                attempt["status"] = "completed"
                record["integration_settings_used"][engine] = dict(request)
                break
    return traces
