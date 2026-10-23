from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Earthwork Volume API"
    version: str = "0.1.0"
    debug: bool = False
    data_dir: Path = Path("data")
    database_url: str

    max_upload_mb: int = 50
    max_survey_points: int = 2_000_000
    min_survey_points: int = 3
    insert_chunk_size: int = 5_000

    model_config = SettingsConfigDict(env_file=".env")

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def report_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()