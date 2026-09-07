"""Read-only local status and numeric telemetry. Never export transcripts or keys."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sqlite3
from statistics import median
from urllib.request import urlopen

p = argparse.ArgumentParser()
p.add_argument('--db', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
with urlopen('http://127.0.0.1:8003/api/text/bootstrap?role=admin', timeout=10) as response:
    data = json.load(response)
result = {'local_demo': data['local_demo'], 'runtime': data['runtime'],
          'settings': {k: data['settings'][k] for k in ['provider', 'model', 'avatar_profile', 'voice_mode', 'max_turns']},
          'scenario_count': len(data['scenarios']), 'session_count': len(data['sessions'])}
with sqlite3.connect(a.db.resolve().as_uri() + '?mode=ro', uri=True) as db:
    rows = db.execute("SELECT json_extract(body, '$.voice_metrics'), json_extract(body, '$.settings.avatar_profile'), json_extract(body, '$.report_status') FROM documents WHERE kind='session'").fetchall()
groups = defaultdict(list)
sessions_with_metrics = 0
for metrics, profile, status in rows:
    metrics = json.loads(metrics or '[]')
    sessions_with_metrics += bool(metrics)
    for metric in metrics:
        if metric.get('kind') in ('handoff_to_audio', 'vad_event_to_mute', 'video_connect') and isinstance(metric.get('ms'), (float, int)):
            key = (metric.get('profile', profile), metric['kind'], bool(metric.get('audio_only', False)))
            groups[key].append(metric['ms'])
result['telemetry'] = {'sessions_with_metrics': sessions_with_metrics, 'groups': [
    {'profile': profile, 'kind': kind, 'audio_only': audio, 'n': len(values),
     'min_ms': min(values), 'median_ms': median(values), 'max_ms': max(values), 'values_ms': values}
    for (profile, kind, audio), values in sorted(groups.items())
]}
a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
