from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    inworld_api_key: str = ""
    inworld_voice_id: str = "Svetlana"
    whisper_model: str = "medium"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"


settings = Settings()
