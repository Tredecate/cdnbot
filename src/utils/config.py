import json
import os
import re

from typing import Any
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CdnCategoryConfig(BaseModel):
    cdn_category_name: str = Field(default="", min_length=0)
    cdn_category_root: str = Field(default="", min_length=0)
    cdn_category_html: str = Field(default="", min_length=0)
    cdn_category_fields: list[str] = Field(default_factory=list)
    cdn_category_defaults: dict[str, Any] = Field(default_factory=dict)
    cdn_category_catalog_type: str = Field(default="", min_length=0)


    @field_validator("cdn_category_fields", "cdn_category_defaults", mode="before")
    @classmethod
    def parse_json_strings(cls, v: Any) -> Any:
        if isinstance(v, str) and v.strip():
            return json.loads(v)
        return v


class CdnCatalogConfig(BaseModel):
    cdn_catalog_state_file: str = Field(default="", min_length=0)
    cdn_catalog_do_init_state: bool = Field(default=False)
    cdn_catalog_type: str = Field(default="", min_length=0)
    cdn_catalog_root: str = Field(default="", min_length=0)
    cdn_catalog_html: str = Field(default="", min_length=0)


class Settings(BaseSettings):
    discord_token: SecretStr = Field(..., min_length=1)
    bucket_secret_access_key: SecretStr = Field(..., min_length=1)
    cdn_cache_token: SecretStr = Field(..., min_length=1)

    bucket_access_key_id: str = Field(..., min_length=1)
    bucket_name: str = Field(..., min_length=1)
    bucket_url: str = Field(..., min_length=1)
    bucket_region: str = Field(default="auto", min_length=1)
    bucket_public_url: str = Field(default="", min_length=0)

    cdn_cache_purge_url: str = Field(default="", min_length=0)

    cdn_categories: list[CdnCategoryConfig] = Field(default_factory=list)
    cdn_catalogs: list[CdnCatalogConfig] = Field(default_factory=list)

    debug_level: int = Field(default=0, ge=0, le=2)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
        cli_parse_args=True,
    )


    @model_validator(mode="after")
    def build_indexed_configs(self) -> "Settings":
        raw_vars: dict[str, Any] = {}
        if self.model_extra:
            raw_vars.update({k.lower(): v for k, v in self.model_extra.items()})
        raw_vars.update({k.lower(): v for k, v in os.environ.items()})

        cat_grouped: dict[int, dict[str, Any]] = {}
        catalog_grouped: dict[int, dict[str, Any]] = {}

        cat_pattern = re.compile(r"^(cdn_category_.*?)_(\d+)$", re.IGNORECASE)
        catalog_pattern = re.compile(r"^(cdn_catalog_.*?)_(\d+)$", re.IGNORECASE)

        for key, value in raw_vars.items():
            if match := cat_pattern.match(key):
                cat_grouped.setdefault(int(match.group(2)), {})[match.group(1)] = value
            elif match := catalog_pattern.match(key):
                catalog_grouped.setdefault(int(match.group(2)), {})[match.group(1)] = value

        if self.model_extra:
            for key in list(self.model_extra):
                if cat_pattern.match(key) or catalog_pattern.match(key):
                    del self.model_extra[key]

        self.cdn_categories.extend(
            CdnCategoryConfig(**cat_grouped[idx]) for idx in sorted(cat_grouped)
        )
        self.cdn_catalogs.extend(
            CdnCatalogConfig(**catalog_grouped[idx]) for idx in sorted(catalog_grouped)
        )
        return self


    def build_catalog_state(self, catalog: CdnCatalogConfig) -> dict[str, Any]:
        matching_cats = [
            c for c in self.cdn_categories
            if c.cdn_category_catalog_type == catalog.cdn_catalog_type
        ]

        section: dict[str, Any] = {
            "meta": {
                "type": "cdn_section",
                "root": catalog.cdn_catalog_root,
                "html_catalog": catalog.cdn_catalog_html,
                "categories": [c.cdn_category_name for c in matching_cats],
            }
        }

        for cat in matching_cats:
            section[cat.cdn_category_name] = {
                "type": "cdn_category",
                "root": cat.cdn_category_root,
                "html_schema": cat.cdn_category_html,
                "fields": cat.cdn_category_fields,
                "defaults": cat.cdn_category_defaults,
                "items": [],
            }

        return {catalog.cdn_catalog_type: section}


settings = Settings()