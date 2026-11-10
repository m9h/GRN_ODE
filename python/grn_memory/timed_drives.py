"""Equivalent event representation of the two timed drives in BioModel 664.

This is a guarded numerical representation for t >= 0, not a general piecewise
translator. The source document stays unchanged. Explicit switches allow tight
absolute tolerances without asking an ODE step to cross a discontinuous RHS.
"""

import hashlib
from pathlib import Path
import tempfile

import libsbml

from .catalog_validation import inspect_model
from .native_protocols import protocol_trajectory

YOON_SHA256 = "382a22cca6d338f7f614406343cd86189d30370ec98ee49df22310b32566b538"


def encode_yoon_drives(path):
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != YOON_SHA256:
        raise ValueError("Timed-drive encoding requires the verified BioModel 664 source")
    doc = libsbml.readSBML(str(path))
    if not doc.setLevelAndVersion(3, 2):
        raise ValueError("Could not convert timed-drive copy to SBML L3V2")
    model = doc.getModel()
    for i in reversed(range(model.getNumRules())):
        if model.getRule(i).getVariable() in {"g1", "g2"}:
            model.removeRule(i)
    model.getParameter("g1").setValue(0.)
    model.getParameter("g2").setValue(1.)
    for when, values in [(5., {"g1": 1., "g2": 0.}), (10., {"g1": 0.})]:
        event = model.createEvent()
        event.setId(f"grn_drive_{int(when)}")
        event.setUseValuesFromTriggerTime(True)
        trigger = event.createTrigger()
        trigger.setInitialValue(False)
        trigger.setPersistent(True)
        trigger.setMath(libsbml.parseL3Formula(f"time >= {when}"))
        for name, value in values.items():
            assignment = event.createEventAssignment()
            assignment.setVariable(name)
            assignment.setMath(libsbml.parseL3Formula(str(value)))
    encoded = libsbml.writeSBMLToString(doc)
    checked = libsbml.readSBMLFromString(encoded)
    if checked.getNumErrors(libsbml.LIBSBML_SEV_ERROR):
        raise ValueError(checked.getErrorLog().toString())
    return encoded


def yoon_trajectory(path, times, trains, engine, **settings):
    columns = ["time"] + inspect_model(path)["observables"]
    with tempfile.TemporaryDirectory(prefix="grn-timed-drives-") as directory:
        modified = Path(directory)/"drives.xml"
        modified.write_text(encode_yoon_drives(path), encoding="utf-8")
        return protocol_trajectory(modified, times, trains, engine, **settings).loc[:, columns]
