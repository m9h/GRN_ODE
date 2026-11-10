"""Separate paper-style memory labels from controlled effects of joint exposure.

The four training histories are none, UCS, CS and UCS+CS. Each is simulated
with and without a later CS probe. Their contrasts control untreated drift,
residual training effects, UCS-only transfer and CS-only pre-exposure.
"""

from .analysis import regulation, retained


def contrast(terms):
    """Linear contrast with a conservative sum of the comparison tolerances.

This is a numerical resolution rule, not a confidence interval or a bound on
the true integration error. Terms are (coefficient, arithmetic window mean).
"""
    value = sum(weight*mean for weight, mean in terms)
    resolution = sum(abs(weight)*(1e-7+2e-5*abs(mean)) for weight, mean in terms)
    direction = 1 if value > resolution else -1 if value < -resolution else 0
    return {"value": value, "resolution": resolution, "resolved_direction": direction}


def controlled_probe(cells, *, negative=False):
    """Score a complete training-history by probe-presence factorial.

Cells map history names to (with-CS mean, without-CS mean). A joint-exposure
candidate must have a resolved cue effect, exceed each simpler history in the
same direction, and have a nonadditive interaction in that direction. Such a
result still does not establish a mechanism or dependence on simultaneous
pairing: a separately timed/unpaired-training control would be needed for that.
"""
    terms = {name: [(1., on), (-1., sham)] for name, (on, sham) in cells.items()}
    effects = {name: contrast(values) for name, values in terms.items()}
    def difference(a, b):
        return contrast(terms[a]+[(-w, y) for w, y in terms[b]])
    differences = {name: difference("paired", name) for name in ("none", "ucs", "cs")}
    interaction = contrast(terms["paired"] + terms["none"] +
                           [(-w, y) for name in ("ucs", "cs") for w, y in terms[name]])
    direction = effects["paired"]["resolved_direction"]
    joint = bool(direction and interaction["resolved_direction"] == direction and
                 all(v["resolved_direction"] == direction for v in differences.values()))
    transfer = difference("ucs", "none")
    cs_history = difference("cs", "none")
    category = ("negative_response_state" if negative else
                "joint_exposure_candidate" if joint else
                "cue_response_without_joint_specificity" if direction else
                "unresolved_cue_effect")
    return {"cue_effects": effects, "paired_minus_simpler_history": differences,
            "factorial_interaction": interaction, "ucs_history_effect": transfer,
            "cs_history_effect": cs_history, "negative_response_values": negative,
            "category": category}


def paper_labels(means):
    """Intended MATLAB thresholds, with Boolean failure and explicit controls.

Names refer to 50-unit windows. The MATLAB post-probe relaxation test and the
additional delayed-cue experiment are separate outputs. Neither is silently
substituted for the other.
"""
    m = means
    ud = regulation(m["baseline"], m["ucs_train"], m["control_train"])
    cd = regulation(m["baseline"], m["cs_train"], m["control_train"])
    pretest = bool(ud and not cd)
    pair2 = regulation(m["baseline"], m["paired_train"], m["control_train"])
    pair15 = regulation(m["baseline"], m["paired_train"], m["control_train"], 1.5)
    ucs15 = regulation(m["baseline"], m["ucs_train"], m["control_train"], 1.5)
    u_probe = regulation(m["ucs_wash"], m["ucs_probe"], m["control_probe"], 1.5)
    p_probe = regulation(m["paired_wash"], m["paired_probe"], m["control_probe"], 1.5)
    transfer = bool(pretest and ucs15 and u_probe)
    association = bool(pretest and pair15 and p_probe and not transfer)
    u_memory = bool(ud and retained(m["baseline"], m["ucs_train"], m["ucs_wash"], ud))
    p_memory = bool(pair2 and retained(m["baseline"], m["paired_train"], m["paired_wash"], pair2))
    long_recall = bool(association and retained(m["paired_wash"], m["paired_probe"],
                                               m["paired_postprobe"], p_probe))
    later = regulation(m["paired_wash"], m["paired_postprobe"], m["control_postprobe"], 1.5)
    delayed = regulation(m["delayed_preprobe"], m["delayed_probe"], m["delayed_sham"], 1.5)
    return {"ucs_direction": ud, "cs_direction": cd, "pretest": pretest,
            "ucs_memory": u_memory, "pairing_memory": p_memory,
            "pairing_memory_without_ucs_memory": bool(pretest and p_memory and not u_memory),
            "transfer": transfer, "association": association,
            "long_recall": long_recall, "short_recall": bool(association and not long_recall),
            "matlab_later_relaxation_candidate": bool(pretest and pair15 and not transfer and not p_probe and later),
            "delayed_cue_candidate": bool(pretest and pair15 and not transfer and not p_probe and delayed)}


def response_score(branches, engine, response):
    """Use all histories at each clock time; never restart an evolved state."""
    def row(role, window):
        return branches[role]["windows"][engine][window][response]
    def mean(role, window):
        return row(role, window)["mean"]
    histories = ("none", "ucs", "cs", "paired")
    result = {}
    for clock, window in (("normal", "probe"), ("delayed", "postprobe")):
        cells = {h: (mean(f"{h}_{clock}", window), mean(f"{h}_sham", window)) for h in histories}
        relevant = [row(role, w) for h in histories for role in (f"{h}_{clock}", f"{h}_sham")
                    for w in ("baseline", "train", "wash", window)]
        if clock == "delayed":
            relevant += [row(f"{h}_sham", "probe") for h in histories]
        negative = any(v["minimum"] < -(1e-7+2e-5*max(abs(v["minimum"]), abs(v["maximum"])))
                       for v in relevant)
        result[clock] = controlled_probe(cells, negative=negative)
        # A paired trained/probed trajectory minus its time-matched no-probe
        # counterpart measures persistence of the cue's incremental effect.
        recall_window = "postprobe" if clock == "normal" else "late"
        recall = contrast([(1., mean(f"paired_{clock}", recall_window)),
                           (-1., mean("paired_sham", recall_window))])
        cue = result[clock]["cue_effects"]["paired"]
        direction = cue["resolved_direction"]
        retention = contrast([(direction, mean(f"paired_{clock}", recall_window)),
                              (-direction, mean("paired_sham", recall_window)),
                              (-.5*direction, mean(f"paired_{clock}", window)),
                              (.5*direction, mean("paired_sham", window))])
        invalid_recall = any(row(role, recall_window)["minimum"] <
                             -(1e-7+2e-5*max(abs(row(role, recall_window)["minimum"]),
                                             abs(row(role, recall_window)["maximum"])))
                             for role in (f"paired_{clock}", "paired_sham"))
        retained_label = ("negative_response_state" if negative or invalid_recall else
                          "unresolved_cue_effect" if not direction else
                          "threshold_unresolved" if not retention["resolved_direction"] else
                          "retained_half" if retention["resolved_direction"] > 0 else "below_half")
        result[clock]["recall"] = {"cue_increment_after_withdrawal": recall,
                                    "half_retention_contrast": retention, "category": retained_label}
    raw = {"baseline": mean("none_sham", "baseline"),
           "control_train": mean("none_sham", "train"),
           "control_probe": mean("none_sham", "probe"),
           "control_postprobe": mean("none_sham", "postprobe"),
           "ucs_train": mean("ucs_sham", "train"), "ucs_wash": mean("ucs_sham", "wash"),
           "cs_train": mean("cs_sham", "train"),
           "paired_train": mean("paired_sham", "train"), "paired_wash": mean("paired_sham", "wash"),
           "ucs_probe": mean("ucs_normal", "probe"), "paired_probe": mean("paired_normal", "probe"),
           "paired_postprobe": mean("paired_normal", "postprobe"),
           "delayed_preprobe": mean("paired_sham", "probe"),
           "delayed_probe": mean("paired_delayed", "postprobe"), "delayed_sham": mean("paired_sham", "postprobe")}
    result["paper_like"] = paper_labels(raw)
    result["paper_like_means"] = raw
    return result


def classification_key(score):
    """Every controlled categorical finding must agree across engines."""
    return {clock: {"category": score[clock]["category"],
                    "recall_category": score[clock]["recall"]["category"],
                    "cue_directions": {k: v["resolved_direction"] for k,v in score[clock]["cue_effects"].items()},
                    "difference_directions": {k: v["resolved_direction"] for k,v in score[clock]["paired_minus_simpler_history"].items()},
                    "interaction_direction": score[clock]["factorial_interaction"]["resolved_direction"],
                    "ucs_history_direction": score[clock]["ucs_history_effect"]["resolved_direction"],
                    "cs_history_direction": score[clock]["cs_history_effect"]["resolved_direction"]}
            for clock in ("normal", "delayed")}
