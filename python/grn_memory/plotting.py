"""Static scientific figures; raw concentrations and controls remain visible."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


def plot_case(name, kind, traces, score, output):
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    response = score["response"]
    fig, axes = plt.subplots(2, 1, figsize=(10, 6.8), constrained_layout=True)
    def draw(ax, key, species, label, **kwargs):
        frame = pd.concat([traces["baseline"], traces[key]])
        ax.plot(frame.time, frame[species], label=label, **kwargs)
    if kind == "retention":
        us = score["stimulus"]
        draw(axes[0], "trained", us, f"Stimulated {us}", color="#7b165e")
        draw(axes[1], "trained", response, "Stimulated network", color="#236ec6")
        draw(axes[1], "control", response, "Untreated control", color="#555555", ls="--")
        for ax in axes:
            ax.axvspan(50, 100, color="#7b165e", alpha=.13)
        axes[0].set_ylabel(f"{us} concentration")
        axes[1].set_title(f"50-unit retention test: {score['ucs_memory']}; retained fraction {score['retained_fraction']:.2f}")
    elif kind == "association":
        draw(axes[0], "ucs", response, "UCS pretest", color="#7b165e")
        draw(axes[0], "naive_cs", response, "CS pretest", color="#d18b18")
        draw(axes[0], "control", response, "Untreated", color="#555555", ls="--")
        axes[0].set_xlim(0, 100)
        for key, label, color, style in [("paired", "Paired training + CS", "#236ec6", "-"),
                                          ("paired_sham", "Paired training + sham", "#555555", "--"),
                                          ("ucs", "UCS-only training + CS", "#7b165e", ":")]:
            t = traces[key]
            t = t[t.time >= 100]
            axes[1].plot(t.time, t[response], label=label, color=color, ls=style)
        axes[1].axvspan(150, 200, color="#2b9c7d", alpha=.14)
        axes[1].set_yscale("symlog", linthresh=1e-6)
        axes[0].set_ylabel(f"{response} concentration")
        axes[1].set_title(f"Associative criterion: {score['associative_memory']}; CS differs from sham: {score['probe_differs_from_paired_sham']}")
    elif kind == "repeated":
        draw(axes[0], "treated", score["stimulus"], "Applied stimulus", color="#7b165e")
        draw(axes[1], "treated", response, "Repeated stimulation", color="#236ec6")
        draw(axes[1], "control", response, "Untreated control", color="#555555", ls="--")
        for phase, group in traces["treated"].groupby("phase", sort=False):
            if phase.startswith("pulse"):
                for ax in axes:
                    ax.axvspan(group.time.min(), group.time.max(), color="#7b165e", alpha=.10)
        axes[0].set_ylabel(f"{score['stimulus']} concentration")
    else:
        breaker = next(iter(score["breaker"]))
        for key, label, color in [("breaking", "Second intervention", "#236ec6"),
                                   ("sham_breaking", "Sham intervention", "#555555")]:
            t = traces[key]
            axes[0].plot(t.time, t[breaker], label=label, color=color)
            axes[1].plot(t.time, t[response], label=label, color=color)
        axes[0].set_ylabel(f"{breaker} concentration")
        for phase, color in [("break", "#7b165e"), ("rechallenge", "#2b9c7d")]:
            t = traces["breaking"].query("phase == @phase")
            for ax in axes:
                ax.axvspan(t.time.min(), t.time.max(), color=color, alpha=.12)
    for ax in axes:
        ax.set_xlabel("Time (SBML model units)")
        ax.legend(loc="best", fontsize=9)
        ax.grid(alpha=.15)
    axes[1].set_ylabel(f"{response} concentration")
    fig.suptitle(name.replace("_", " ").capitalize(), fontsize=16)
    fig.savefig(output / f"{name}.png", dpi=160)
    plt.close(fig)
