"""Rechallenge effects after interventions on acquired response histories."""

from .paired_scores import contrast


def matlab_break_direction(before, during, last_code):
    """Literal reversal test; zero equality artifacts remain visible as raw labels."""
    if last_code not in (1,2):
        return 0
    if during >= 1.5*before and last_code != 1:
        return 1
    if during <= before/1.5 and last_code != 2:
        return 2
    return 0


def controlled_break(cells, *, negative=False):
    """Compare the effect of prior history with and without the breaker.

Cells are (rechallenge, same-history sham) means for none, history, breaker and
history_breaker. A direct breaker effect shared by naive and trained systems
is subtracted. Restoration means at least a halving of the history-dependent
cue effect, beyond the declared numerical resolution.
"""
    terms = {name:[(1.,on),(-1.,sham)] for name,(on,sham) in cells.items()}
    effects = {name:contrast(values) for name,values in terms.items()}
    before_terms = terms["history"]+[(-w,y) for w,y in terms["none"]]
    after_terms = terms["history_breaker"]+[(-w,y) for w,y in terms["breaker"]]
    before, after = contrast(before_terms), contrast(after_terms)
    interaction = contrast(after_terms+[(-w,y) for w,y in before_terms])
    half_margin = .5*abs(before["value"])-abs(after["value"])
    half_resolution = .5*before["resolution"]+after["resolution"]
    amplification = abs(after["value"])-1.5*abs(before["value"])
    amplification_resolution = after["resolution"]+1.5*before["resolution"]
    if negative:
        category = "negative_response_state"
    elif not before["resolved_direction"]:
        category = "no_resolved_history_effect_at_rechallenge"
    elif abs(half_margin) <= half_resolution:
        category = "half_restoration_threshold_unresolved"
    elif half_margin > half_resolution:
        category = "history_effect_reduced_by_half"
    elif not interaction["resolved_direction"]:
        category = "no_resolved_breaker_effect_on_history"
    elif before["resolved_direction"]*after["resolved_direction"] < 0:
        category = "history_effect_reversed"
    elif amplification > amplification_resolution:
        category = "history_effect_amplified"
    else:
        category = "history_effect_changed_without_half_restoration"
    return {"cue_effects":effects, "history_effect_without_breaker":before,
            "history_effect_with_breaker":after, "breaker_history_interaction":interaction,
            "half_restoration_margin":half_margin, "half_restoration_resolution":half_resolution,
            "negative_response_values":negative, "category":category}


def classification_key(score):
    return {"category":score["category"],
            "cue_directions":{k:v["resolved_direction"] for k,v in score["cue_effects"].items()},
            "history_direction_before":score["history_effect_without_breaker"]["resolved_direction"],
            "history_direction_after":score["history_effect_with_breaker"]["resolved_direction"],
            "interaction_direction":score["breaker_history_interaction"]["resolved_direction"]}


def trial_scores(branches, engine, responses, source, trial):
    result = {}
    for response in responses:
        def row(role, window):
            return branches[role]["windows"][engine][window][response]
        def mean(role, window):
            return row(role,window)["mean"]
        cells = {h:(mean(h+"_cue",f"cue_{trial}"),mean(h+"_sham",f"cue_{trial}"))
                 for h in ("none","history","breaker","history_breaker")}
        # The complete prefix and extension ranges guard against interpreting
        # excursions outside the concentration domain as physical learning.
        negative = any(v["minimum"] < -(1e-7+2e-5*max(abs(v["minimum"]),abs(v["maximum"])))
                       for branch in branches.values() for window in branch["windows"][engine].values()
                       for symbol,v in window.items() if symbol == response)
        score = controlled_break(cells,negative=negative)
        raw = source[response][engine]
        pre = mean("history_breaker_cue",f"pre_{trial}")
        on = mean("history_breaker_cue",f"cue_{trial}")
        score["matlab"] = {**raw, "pre_mean":pre, "cue_mean":on,
                            "break_direction":matlab_break_direction(pre,on,raw["last_code"])}
        result[response] = score
    return result


def remaining_responses(scores, responses, engines):
    """Follow the union of the two engines' literal MATLAB continuation paths.

Controls do not silently alter the original search tree. A raw-positive result
can stop the search yet fail controlled interpretation; both facts are reported.
"""
    return [r for r in responses if any(scores[e][r]["matlab"]["eligible"] and
            not scores[e][r]["matlab"]["break_direction"] for e in engines)]
