"""Read-only application audit, isolated fixtures, at most 12 real text calls."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4

from dotenv import dotenv_values
from openai import AsyncOpenAI

from backend.text_app.agent import Agent
from backend.text_app.budget import OpenAIRequestBudget
from backend.text_app.models import Settings, Stage, StartRequest, Turn
from backend.text_app.seeds import seed
from backend.text_app.service import Service, session_view
from backend.text_app.store import Store
from backend.text_app.voice_training import VoiceTraining


async def main(args):
    values = dotenv_values(args.env)
    for name in ('OPENAI_API_KEY', 'OPENAI_BASE_URL'):
        if values.get(name): os.environ[name] = values[name]
    os.environ['OPENAI_API_ENABLED'] = '1'
    budget = OpenAIRequestBudget.from_local_config()
    result = {'initial_lines': [], 'responses': [], 'voice_video_calls':0,
              'voice_scope':'Production VoiceTraining instruction/history; text generation only, no media or tool execution'}
    with tempfile.TemporaryDirectory(prefix='rehearsal-gender-audit-') as temporary:
        store = Store(Path(temporary) / 'fixtures.sqlite3'); seed(store)
        agent = Agent(budget); service = Service(store, agent)
        fixtures = []
        for profile in ('tavus_sergei', 'anam_tatiana'):
            store.put('settings', 'main', Settings(voice_mode='avatar', avatar_profile=profile))
            for scenario_id in ('sales-objection', 'feedback', 'support'):
                session = await service.start(StartRequest(scenario_id=scenario_id,request_id=str(uuid4()),consent=True,voice_consent=True))
                result['initial_lines'].append({'profile':profile,'scenario':scenario_id,
                    'name':session.scenario.npc_name,'text':session_view(session)['opening_message'],
                    'voice_history_same':VoiceTraining(service,session.id).history()[0]['content']==session_view(session)['opening_message']})
            for mode in ('text', 'voice_instruction'):
                for case in ('own_actions', 'wrong_old_history', 'third_person'):
                    session = await service.start(StartRequest(scenario_id='feedback',request_id=str(uuid4()),consent=True,voice_consent=True))
                    session.scenario.context = ('Твои личные действия: покупка учебной лицензии, выбор тарифа «Старт», решение начать пилот, '
                        'подписание договора. Ты лично готовишь запуск и лично готовишься провести тест. '
                        'Коллега Анна купила гарнитуру и выбрала ноутбук. Коллега Олег купил микрофон и выбрал камеру. Это разные люди.')
                    session.scenario.manner = 'Отвечай спокойно, конкретно и от своего лица. Факты о коллегах не приписывай себе.'
                    session.scenario.stages = [Stage(id='facts', title='Личные действия',
                        objective='Обсудить личные действия и роли коллег до согласования даты запуска.', opening_line='Здравствуйте. Обсудим подготовку к запуску.')]
                    question = 'Расскажите от первого лица: что вы купили, выбрали, решили и подписали? Вы готовы к запуску?'
                    if case == 'wrong_old_history':
                        wrong = 'Я купила лицензию, выбрала тариф и подписала договор. Я готова.' if profile == 'tavus_sergei' else 'Я купил лицензию, выбрал тариф и подписал договор. Я готов.'
                        session.turns.append(Turn(id='old',request_id='old',user_text='Вы уже подготовились?',reply=wrong,stage_index=0,status='committed',interrupted=True))
                    if case == 'third_person':
                        question = 'Что купили и выбрали лично вы, а что купили и выбрали Анна и Олег? О себе говорите «я», не «мы».'
                    session.turns.append(Turn(id='probe',request_id='probe',user_text=question,stage_index=0,status='pending'))
                    fixtures.append((profile,mode,case,session,question))
        for profile, mode, case, session, question in fixtures:
            started=time.perf_counter(); row={'profile':profile,'mode':mode,'case':case,'question':question}
            try:
                if mode == 'text':
                    decision = await agent.turn(session); row['reply'] = decision.reply
                else:
                    store.put('session',session.id,session)
                    training=VoiceTraining(service,session.id)
                    messages=[{'role':'system','content':training.instruction()},*training.history(),{'role':'user','content':question}]
                    reservation=budget.reserve('text_turn'); state='failed'
                    try:
                        async with AsyncOpenAI(api_key=budget.api_key,base_url=budget.base_url,max_retries=0,timeout=30) as client:
                            stream=await client.chat.completions.create(model=session.settings.model,messages=messages,
                                max_completion_tokens=600,reasoning_effort='none',stream=True,stream_options={'include_usage':True})
                            parts=[]
                            async for chunk in stream:
                                if chunk.usage: budget.record(reservation,chunk.model,chunk.usage.model_dump())
                                if chunk.choices and chunk.choices[0].delta.content: parts.append(chunk.choices[0].delta.content)
                            row['reply']=''.join(parts);state='completed'
                    finally: budget.finish(reservation,state)
                row['elapsed_ms']=round((time.perf_counter()-started)*1000)
            except Exception as exc:
                row['error_type']=type(exc).__name__
            result['responses'].append(row)
            args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(row,ensure_ascii=False),flush=True)
            if row.get('error_type'): break
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--env',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    asyncio.run(main(parser.parse_args()))
