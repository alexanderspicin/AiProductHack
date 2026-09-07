"""Reproducible API-only estimate; no network, keys or provider requests."""
import json
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text(), parse_float=D, parse_int=D)


def choose_plan(plans, minutes, duration):
    eligible = [p for p in plans if p['session_limit_minutes'] is None
                or p['session_limit_minutes'] >= duration]
    options = [(p['monthly_usd'] + max(D(0), minutes - p['minutes_included'])
                * p['overage_usd_min'], p['name']) for p in eligible]
    return min(options)


def money(n):
    return float(n.quantize(D('0.01')))


def main():
    b, a = load('defense_api_gpu.json'), load('cheaper_api.json')
    w = b['workload']
    sessions, fx = w['sessions_per_month']['value'], w['usd_rub']['value']
    results = []
    for i, duration in enumerate(w['session_minutes']['values']):
        minutes = sessions * duration
        chars = minutes * w['bot_speech_fraction']['value'] * w['tts_chars_per_spoken_minute']['value']
        llm = sessions * (w['llm_input_tokens']['values'][i] * b['openai']['input_usd_per_million']
                          + w['llm_output_tokens']['values'][i] * b['openai']['output_usd_per_million']) / D(1000000)
        tts = {'Cartesia Startup': b['cartesia']['monthly_usd'],
               'Inworld TTS-2': chars * a['inworld']['tts2_usd_million_chars'] / D(1000000),
               'Inworld TTS-2 Flash': chars * a['inworld']['tts2_flash_usd_million_chars'] / D(1000000)}
        assert chars <= b['cartesia']['credits_per_month']
        video = {name: choose_plan(plans, minutes, duration) for name, plans in
                 [('Tavus', b['tavus']['plans']), ('LiveAvatar', a['liveavatar']['plans'])]}
        reference = video['Tavus'][0] + tts['Cartesia Startup'] + llm
        combos = []
        for avatar, voice in [('Tavus', 'Cartesia Startup'), ('Tavus', 'Inworld TTS-2'),
                              ('LiveAvatar', 'Cartesia Startup'), ('LiveAvatar', 'Inworld TTS-2'),
                              ('LiveAvatar', 'Inworld TTS-2 Flash')]:
            total = video[avatar][0] + tts[voice] + llm
            combos.append({'avatar': avatar, 'video_plan': video[avatar][1], 'voice': voice,
                           'video_usd_month': money(video[avatar][0]),
                           'tts_usd_month': money(tts[voice]), 'llm_usd_month': money(llm),
                           'api_rub_month': money(total * fx),
                           'api_rub_training': money(total * fx / sessions),
                           'savings_percent': money((reference - total) / reference * 100)})
        results.append({'session_minutes': int(duration), 'video_minutes_month': int(minutes),
                        'tts_chars_month': int(chars), 'combinations': combos})
    base = results[1]['combinations']
    assert base[0]['api_rub_month'] == 39803.0
    assert base[2]['api_rub_month'] == 14928.0
    assert base[3]['api_rub_month'] == 10965.5
    assert base[2]['video_plan'] == 'Essential'
    assert base[0]['api_rub_month'] - base[1]['api_rub_month'] == 3962.5
    output = {'as_of': a['as_of'], 'scope': 'API only; planning scenarios, not observed invoices',
              'usd_rub': int(fx), 'scenarios': results}
    (ROOT / 'cheaper_api_results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
