"""Reproducible pricing arithmetic; no network or service clients."""
import json
from pathlib import Path

base = Path(__file__).parent
config = json.loads((base / 'defense_api_gpu.json').read_text())
w = config['workload']
n, fx = w['sessions_per_month']['value'], w['usd_rub']['value']
results = {'currency_rate_status': 'planning assumption, 100 RUB/USD', 'scenarios': []}
for idx, minutes in enumerate(w['session_minutes']['values']):
    billed = n * minutes
    llm = n * (w['llm_input_tokens']['values'][idx] * config['openai']['input_usd_per_million'] + w['llm_output_tokens']['values'][idx] * config['openai']['output_usd_per_million']) / 1000000
    chars = billed * w['bot_speech_fraction']['value'] * w['tts_chars_per_spoken_minute']['value']
    assert chars <= config['cartesia']['credits_per_month']
    voice = config['cartesia']['monthly_usd']
    options = [(p['monthly_usd'] + max(0, billed-p['minutes_included']) * p['overage_usd_min'], p['name']) for p in config['tavus']['plans'] if p['session_limit_minutes'] is None or minutes <= p['session_limit_minutes']]
    video, plan = min(options)
    total = video + voice + llm
    anam = config['anam']['plans'][idx]
    a_extra = max(0, billed-anam['minutes_included']) * anam['overage_usd_min']
    results['scenarios'].append({'session_minutes': minutes, 'sessions': n, 'billed_video_minutes': billed, 'generated_tts_characters_assumed': chars,
        'llm_monthly_usd': round(llm, 6), 'voice_monthly_usd': voice,
        'tavus': {'plan': plan, 'video_monthly_usd': round(video, 2), 'all_api_monthly_usd': round(total, 2), 'all_api_monthly_rub': round(total*fx, 2), 'all_api_per_training_rub': round(total*fx/n, 2)},
        'anam': {'plan_for_session_length': anam['name'], 'subscription_usd': None, 'video_overage_usd': round(a_extra, 2), 'all_api_monthly_usd_excluding_anam_subscription': round(a_extra+voice+llm, 2), 'all_api_monthly_rub_excluding_anam_subscription': round((a_extra+voice+llm)*fx, 2), 'formula': 'add actual monthly Anam subscription in USD times planning FX; unknown is not zero'}})
results['gpu_compute_only'] = [{'hours_per_month': h, 'usd': round(h*config['gpu']['hourly_usd'],2), 'rub': round(h*config['gpu']['hourly_usd']*fx,2)} for h in config['gpu']['active_hours_per_month']]
results['hybrid_cpu_media_with_api_llm_base_monthly_rub'] = round(results['scenarios'][1]['llm_monthly_usd']*fx,2)
labor = n * config['business']['illustrative_methodist_minutes_per_session'] / 60 * config['business']['methodist_hourly_rub']
results['illustrative_business_base'] = {'methodist_minutes_per_session_assumption': 20, 'labor_monthly_rub': labor, 'tavus_api_plus_labor_monthly_rub_before_exclusions': round(labor+results['scenarios'][1]['tavus']['all_api_monthly_rub'],2), 'manual_reference_rub': config['business']['manual_baseline_monthly_rub'], 'effect_proven': False}
# Independent arithmetic checks for the base scenario and fixed compute hours.
assert abs(results['scenarios'][1]['tavus']['video_monthly_usd'] - (59+825*0.35)) < 1e-9
assert results['gpu_compute_only'][-1]['rub'] == 78480
assert results['scenarios'][1]['llm_monthly_usd'] == 1.28
(base/'defense_api_gpu_results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(results, ensure_ascii=False, indent=2))
