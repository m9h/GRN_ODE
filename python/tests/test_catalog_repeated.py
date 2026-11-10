"""Schedule and interpretation checks for the repeated-input catalog stage."""

from grn_memory.catalog_repeated import increment_category, matlab_codes, pulse_schedule, trains_for


def test_matlab_schedule_has_six_growing_pulses_and_both_endpoint_resets():
    schedule = pulse_schedule()
    assert [(p["start"], p["stop"], p["rest_stop"]) for p in schedule] == [
        (50.,100.,160.), (160.,220.,290.), (290.,360.,440.),
        (440.,520.,610.), (610.,700.,800.), (800.,900.,1010.)]
    trains = trains_for(schedule, {"input": 3.})
    assert sum(len(train.times()) for train in trains) == 4506
    assert trains[0].times()[0] == 50 and trains[-1].times()[-1] == 900


def test_accumulation_can_raise_raw_pulse_means_without_enhancing_increment():
    # Integrating identical unit inputs adds each pulse duration to the state.
    # Longer pulses and accumulated material increase absolute response means.
    durations = [50.,60.,70.,80.,90.,100.]
    total, on = 0., []
    for duration in durations:
        on.append(total+duration/2)
        total += duration
    codes = [value for value in matlab_codes(0., on) if value]
    assert len(codes)>1 and set(codes)=={1}
    # At the last pulse, both repeated and naive increments remain exactly 50.
    assert increment_category(400.,350.,50.,0.) == "no_1.5fold_change"


def test_literal_matlab_down_response_asymmetry_is_exposed():
    assert matlab_codes(10., [6.,3.,1.4]) == [2,1,1]


def test_unresolved_negative_and_reversed_responses_are_distinct():
    assert increment_category(1e-20,0.,-1e-20,0.) == "unresolved"
    assert increment_category(-2.,1.,2.,1.,negative=True) == "negative_response_state"
    assert increment_category(0.,1.,2.,1.) == "reversed"
