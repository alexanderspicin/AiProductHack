"""Only the original local GLB avatar is available in this edition."""
PROFILES = {"legacy_3d": {"id": "legacy_3d", "title": "3D-персонаж команды",
    "description": "Inworld, локальные Three.js и Oculus Visemes. Без внешнего видео API.", "provider": "local"}}

def public_profiles():
    return list(PROFILES.values())

def identity_instruction(settings):
    return ""

def selected_status(profile, **kwargs):
    from .voice_routes import pipeline_status
    return pipeline_status()
