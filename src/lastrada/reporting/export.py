from html import escape
import json


def json_report(analysis):
    return analysis.model_dump_json(indent=2)


def html_report(analysis):
    title = escape(analysis.case_id)
    corrected = analysis.review.corrected
    text = corrected["nature_of_use"]["text"] if corrected else analysis.nature_of_use.text
    data = escape(json.dumps(analysis.model_dump(mode="json"), indent=2))
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>'
        "<style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px;"
        "color:#271d36}pre{white-space:pre-wrap;background:#f3eef9;padding:20px}</style>"
        f"</head><body><h1>Nature of Use review · {title}</h1>"
        f"<p>Status: {escape(analysis.review.status)} · "
        f"{'Synthetic demonstration' if analysis.synthetic else 'Local analysis'}</p>"
        "<p>Draft documentation; this report is not a licensing or legal clearance decision.</p>"
        f"<p>{escape(text)}</p><h2>Automated evidence and separate expert corrections</h2>"
        f"<pre>{data}</pre></body></html>"
    )
