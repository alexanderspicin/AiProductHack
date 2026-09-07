"""Curated, server-owned identities. No credentials or user-provided provider URLs."""
from .budget import local_setting

PROFILES = {
    "tavus_sergei": {"id": "tavus_sergei", "title": "Даниил", "description": "Мужской персонаж. Cartesia Sergei + Tavus Daniel.",
                     "provider": "tavus", "voice_id": "1e4176b1-3db9-44d6-a601-4fe68b041942", "face_id": "r72f7f7f7c8b"},
    "anam_tatiana": {"id": "anam_tatiana", "title": "Татьяна", "description": "Женский персонаж. Cartesia Tatiana + Anam Cara.",
                     "provider": "anam", "voice_id": "064b17af-d36b-4bfb-b003-be07dba1b649", "face_id": "30fa96d0-26c4-4e55-94a0-517025942e18"},
    "legacy_3d": {"id": "legacy_3d", "title": "Прежний 3D-персонаж", "description": "Резерв команды: Inworld и локальная 3D-модель.",
                  "provider": "local", "voice_id": "", "face_id": ""},
}


def public_profiles():
    return [{k: p[k] for k in ("id", "title", "description", "provider")} for p in PROFILES.values()]


def identity_instruction(settings):
    if settings.voice_mode != 'avatar' or settings.avatar_profile == 'legacy_3d':
        return ''
    p = PROFILES[settings.avatar_profile]
    gender = 'мужском' if settings.avatar_profile == 'tavus_sergei' else 'женском'
    return (f"В этой тренировке тебя зовут {p['title']}. Говори о себе в {gender} роде. "
            "Сохраняй роль и факты сценария, даже если описание использует другой род. "
            "Этот род относится только к тебе: согласуй свои глаголы, прилагательные и причастия. "
            "Не меняй род других людей или их прямую речь. Пол участника не выводи из своего пола; "
            "если он неизвестен, обращайся на «вы» без предположений о роде.\n")


def selected_status(profile: str, *, audio_only=False):
    import importlib.util
    p = PROFILES[profile]
    required = ["OPENAI", "CARTESIA"] + ([] if audio_only else [p["provider"].upper()])
    missing = [name for name in required if not local_setting(name + "_API_KEY")
               or local_setting(name + "_API_ENABLED", "0") != "1"]
    installed = importlib.util.find_spec("pipecat") is not None
    return {"profile": profile, "available": installed and not missing, "installed": installed,
            "missing": missing, "provider": p["provider"], "voice": "Sergei" if profile == "tavus_sergei" else "Tatiana",
            "detail": "Ключи подключены. Модели распознавания прогреваются при первом запуске." if installed and not missing
                      else "Не подключено: " + ", ".join(missing + ([] if installed else ["local voice dependencies"]))}
