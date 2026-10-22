"""One-time source patch used to install the grouped timing review UI."""

from pathlib import Path


app_path = Path("app.py")
app = app_path.read_text(encoding="utf-8")

import_line = (
    "from lastrada.reporting.suggestions import suggested_intervals, "
    "timing_questions, confirmed_prefills\n"
)
import_block = import_line + (
    "from lastrada.reporting.loop_groups import (\n"
    "    group_loop_families,\n"
    "    loop_family_rows,\n"
    "    raw_interval_rows,\n"
    ")\n"
)
if "from lastrada.reporting.loop_groups import" not in app:
    if app.count(import_line) != 1:
        raise RuntimeError("Could not find the suggestions import exactly once")
    app = app.replace(import_line, import_block, 1)

seed_anchor = '                    seeds = st.session_state[key + "seed_intervals"]\n'
agreement_anchor = '\n                    agreement = st.radio(\n'
seed_start = app.index(seed_anchor) + len(seed_anchor)
seed_end = app.index(agreement_anchor, seed_start)
grouped_ui = '''                    loop_families = group_loop_families(
                        seeds,
                        result.durations.get("new"),
                    )
                    if loop_families:
                        st.markdown("#### Grouped use pattern")
                        st.caption(
                            "Rows that point to the same source passage are grouped into "
                            "one use family. Overlapping Sony windows are collapsed, while "
                            "every exact timestamp remains available below."
                        )
                        st.dataframe(
                            pd.DataFrame(loop_family_rows(loop_families)),
                            use_container_width=True,
                            hide_index=True,
                        )
                        raw_rows = raw_interval_rows(loop_families)
                        with st.expander(
                            f"View all {len(raw_rows)} exact timestamp suggestion(s)"
                        ):
                            st.dataframe(
                                pd.DataFrame(raw_rows),
                                use_container_width=True,
                                hide_index=True,
                            )

                    st.markdown("#### Confirm the pattern")
                    st.caption(
                        "Review the grouped pattern first. Accept the exact occurrences, or "
                        "choose edit to open the full timestamp editor."
                    )
                    if rights == "master" and seeds:
                        paired = [
                            item
                            for item in seeds
                            if item.original_start is not None
                            and item.original_end is not None
                        ]
                        if paired:
                            st.info(
                                f"{len(paired)} paired Sony/refinement row(s) were condensed "
                                f"into {len(loop_families)} source/use group(s)."
                            )
'''
app = app[:seed_start] + grouped_ui + app[seed_end:]

agreement_start = app.index('                    agreement = st.radio(\n')
rows_anchor = '                    rows = [\n'
manual_anchor = '\n                    with st.container(key=key + "manual_confirmation"):\n'
rows_start = app.index(rows_anchor, agreement_start)
rows_end = app.index(manual_anchor, rows_start)
editor_ui = '''                    rows = [
                        {
                            "new_start": i.new_start,
                            "new_end": i.new_end,
                            "original_start": i.original_start,
                            "original_end": i.original_end,
                        }
                        for i in seeds
                    ]
                    base_intervals = pd.DataFrame(
                        rows,
                        columns=[
                            "new_start",
                            "new_end",
                            "original_start",
                            "original_end",
                        ],
                    )
                    if editable:
                        st.markdown("#### Edit exact occurrences")
                        st.caption(
                            "The grouped summary stays intact until you save; edit, add, "
                            "or remove individual occurrences here."
                        )
                        intervals = st.data_editor(
                            base_intervals,
                            num_rows="dynamic",
                            disabled=status == "not_detected",
                            key=key + "intervals",
                            column_config={
                                c: st.column_config.NumberColumn(
                                    {
                                        "new_start": "Your track · start (s)",
                                        "new_end": "Your track · end (s)",
                                        "original_start": "Original · start (s)",
                                        "original_end": "Original · end (s)",
                                    }[c],
                                    min_value=0.0,
                                    step=0.01,
                                )
                                for c in [
                                    "new_start",
                                    "new_end",
                                    "original_start",
                                    "original_end",
                                ]
                            },
                        )
                    else:
                        intervals = base_intervals
'''
app = app[:rows_start] + editor_ui + app[rows_end:]

app_path.write_text(app, encoding="utf-8")
