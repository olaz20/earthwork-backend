from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Earthwork Volume API"
    version: str = "0.1.0"
    debug: bool = False
    data_dir: Path = Path("data")
    database_url: str

    model_config = SettingsConfigDict(env_file=".env")

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def report_dir(self) -> Path:
        return self.data_dir / "reports"


settings = Settings()