import json
import copy
from functools import partial
from typing import Any

from bucketclient import client
from config import CdnCatalogConfig, CdnCategoryConfig, settings
from log import debug_log


class CatalogManager:
    def __init__(self, catalog_config: CdnCatalogConfig, category_configs: list[CdnCategoryConfig]):
        debug_log(f"Initializing CatalogManager for catalog type: {catalog_config.cdn_catalog_type}", 0)
        self.catalog_type: str = catalog_config.cdn_catalog_type
        self.catalog_root: str = catalog_config.cdn_catalog_root
        self.catalog_state_file: str = catalog_config.cdn_catalog_state_file
        self.catalog_html_file: str = catalog_config.cdn_catalog_html
        self.catalog_do_init_state: bool = catalog_config.cdn_catalog_do_init_state

        self.state_path = f"{self.catalog_root.strip('/')}/{self.catalog_state_file.strip('/')}"
        self.state_url = f"{settings.bucket_public_url.rstrip('/')}/{self.state_path}"

        self.html_path = f"{self.catalog_root.strip('/')}/{self.catalog_html_file.strip('/')}"
        self.html_url = f"{settings.bucket_public_url.rstrip('/')}/{self.html_path}"

        self.categories: dict[str, CdnCategoryConfig] = {
            c.cdn_category_name: c for c in category_configs
        }

        self._remote_state: dict[str, Any] | None = None
        self._local_state: dict[str, Any] | None = None

        self._initialized = False
        self.failuremode = None

        self.initialize_catalog(self.catalog_do_init_state, False)


    def is_initialized(self) -> bool:
        return self._initialized


    def get_category_names(self) -> list[str]:
        if self._local_state and self.catalog_type in self._local_state:
            return self._local_state[self.catalog_type].get("meta", {}).get("categories", [])
        return list(self.categories.keys())


    def get_category_schema(self, category: str, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            self._get_state()
        cat_data = self._local_state[self.catalog_type].get(category)

        if not cat_data or cat_data.get("type") != "cdn_category":
            raise ValueError(f"Category {category} does not exist in catalog {self.catalog_type}.")
        
        return {
            "fields": cat_data.get("fields", []),
            "defaults": cat_data.get("defaults", {}),
            "root": cat_data.get("root", ""),
        }


    def add_to_category(self, category: str, **kwargs: Any):
        self._get_state()
        section = self._local_state.get(self.catalog_type, {})
        cat_data = section.get(category)

        if not cat_data or cat_data.get("type") != "cdn_category":
            raise ValueError(f"Unknown category {category} in catalog {self.catalog_type}")

        allowed_fields = cat_data.get("fields", [])
        defaults = cat_data.get("defaults", {})

        item_data = {}
        for field in allowed_fields:
            if field in kwargs and kwargs[field] is not None and kwargs[field] != "":
                item_data[field] = kwargs[field]
            elif field in defaults:
                item_data[field] = defaults[field]
            else:
                raise ValueError(f"Missing required field {field} for category {category}.")

        self._add_media(category, item_data)


    def refresh_catalog(self):
        self._get_state()
        self._update_catalog_html()


    def initialize_catalog(self, build_initial_on_failure: bool = False, _force_rebuild: bool = False):
        try:
            try:
                self._get_state()
            except Exception as e:
                debug_log(f"Failed to fetch remote state: {e}")
                if build_initial_on_failure:
                    self._local_state = self._build_initial_state()

            if _force_rebuild:
                self._local_state = self._build_initial_state()

            if self._local_state is None:
                raise ValueError("Failed to fetch remote state and build_initial_on_failure is False.")

            self._update_state()

            for cat_name in self.get_category_names():
                setattr(self, f"add_{cat_name}", partial(self.add_to_category, cat_name))
            
            self._update_catalog_html()
            self._did_initialize()
            return True
        except Exception as e:
            self._failed_to_initialize(f"Failed to initialize catalog {self.catalog_type}: {e}.")
            return False


    def _did_initialize(self):
        debug_log(f"Catalog Manager for {self.catalog_type} initialized successfully.")
        self._initialized = True
        self.failuremode = None


    def _failed_to_initialize(self, error_message: str):
        debug_log(f"Failed to initialize {self.catalog_type} Catalog Manager: {error_message}")
        self._initialized = False
        self.failuremode = error_message


    def _add_media(self, category: str, item_data: dict[str, Any]):
        remote_state_bkp = copy.deepcopy(self._remote_state)
        self._local_state[self.catalog_type][category]["items"].append(item_data)

        try:
            self._update_state()
            self._update_catalog_html()
        except Exception as e:
            debug_log(f"Failed to update state or catalog HTML: {e}. Rolling back changes.")
            self._local_state = remote_state_bkp
            try:
                self._update_state()
                self._update_catalog_html()
            except Exception as e:
                debug_log(f"Rollback also failed: {e}")
            raise ValueError("Failed to update state or catalog HTML. Changes rolled back.")


    def _get_state(self):
        if not self.catalog_state_file:
            raise ValueError("CDN catalog state file is not configured.")

        try:
            state_data = client.get_file(self.state_path)
            self._remote_state = json.loads(state_data.decode("utf-8"))
            self._local_state = copy.deepcopy(self._remote_state)
        except Exception as e:
            debug_log(f"Failed to fetch remote state file from {self.state_path}: {e}")
            self._local_state = None
            raise ValueError("Failed to fetch remote state file.")


    def _update_state(self):
        if not self.catalog_state_file:
            raise ValueError("CDN catalog state file is not configured.")

        if self._local_state is None:
            raise ValueError("Local state is not set. Cannot update remote state.")

        try:
            client.upload_file(self.state_path, json.dumps(self._local_state, indent=4).encode("utf-8"))
            debug_log(f"Successfully updated remote state file: {self.state_path}")
        except Exception as e:
            debug_log(f"Failed to update remote state file {self.state_path}: {e}")
            raise ValueError("Failed to update remote state file.")
        
        try:
            client.purge_cache(self.state_url.split('://')[1])
        except Exception as e:
            debug_log(f"Failed to purge cache for state file {self.state_url}: {e}")

        self._get_state()


    def _build_initial_state(self) -> dict[str, Any]:
        section: dict[str, Any] = {
            "meta": {
                "type": "cdn_section",
                "root": self.catalog_root,
                "html_catalog": self.catalog_html_file,
                "categories": list(self.categories.keys()),
            }
        }

        for cat_name, cat_cfg in self.categories.items():
            section[cat_name] = {
                "type": "cdn_category",
                "root": cat_cfg.cdn_category_root,
                "html_schema": cat_cfg.cdn_category_html,
                "fields": cat_cfg.cdn_category_fields,
                "defaults": cat_cfg.cdn_category_defaults,
                "items": [],
            }

        return {self.catalog_type: section}


    def _generate_catalog_html(self, state: dict[str, Any]) -> str:
        try:
            with open("catalog_template.html", "r", encoding="utf-8") as f:
                template = f.read()
        except Exception as e:
            debug_log(f"Failed to read catalog template: {e}")
            raise ValueError("Failed to generate catalog HTML. No template available.")

        debug_log(f"Using catalog template: {template}", 2)
        return self._parse_state_to_html(state[self.catalog_type], template)


    def _update_catalog_html(self):
        if self._local_state is None:
            raise ValueError("State is not available. Cannot update catalog HTML.")

        html_content = self._generate_catalog_html(self._local_state)
        debug_log(f"Generated catalog HTML: {html_content}", 2)

        try:
            client.upload_file(self.html_path, html_content.encode("utf-8"))
            debug_log(f"Successfully updated catalog HTML file: {self.html_path}")
        except Exception as e:
            debug_log(f"Failed to update catalog HTML file {self.html_path}: {e}")
            raise ValueError("Failed to update catalog HTML file.")
        
        try:
            client.purge_cache(self.html_url.split('://')[1])
        except Exception as e:
            debug_log(f"Failed to purge cache for HTML file {self.html_url}: {e}")


    def _parse_state_to_html(self, state_section: dict, template: str) -> str:
        debug_log(f"Parsing state section to HTML: {state_section}", 2)
        section_meta = state_section.get("meta", None)
        
        if section_meta is None or section_meta.get("type", "") != "cdn_section":
            raise ValueError("State section is invalid or missing 'meta' information.")

        end_marker = "<!-- endsect:categories -->"
        generated_blocks: list[str] = []

        for category in section_meta.get("categories", []):
            category_data = state_section.get(category, None)

            if category_data is None or category_data.get("type", "") != "cdn_category":
                debug_log(f"Category '{category}' is missing or invalid.")
                continue

            html_schema = category_data.get("html_schema", "")
            fields = category_data.get("fields", [])
            defaults = category_data.get("defaults", {})

            block_lines = [f"<h2>{category}</h2>"]

            for item in category_data.get("items", []):
                item_html = html_schema
                for field in fields:
                    value = item.get(field, defaults.get(field, ""))
                    item_html = item_html.replace("{{" + field + "}}", str(value))

                block_lines.append(item_html)

            generated_blocks.append("\n".join(block_lines))

        if generated_blocks:
            replacement = "\n\n".join(generated_blocks) + "\n" + end_marker
            template = template.replace(end_marker, replacement)

        return template


catalog_managers: dict[str, CatalogManager] = {}
debug_log(f"catalog_managers dict made: {catalog_managers}", 2)

for catalog_cfg in settings.cdn_catalogs:
    matching_categories = [category for category in settings.cdn_categories if category.cdn_category_catalog_type == catalog_cfg.cdn_catalog_type]
    try:
        catalog_managers[catalog_cfg.cdn_catalog_type] = CatalogManager(catalog_cfg, matching_categories)
    except Exception as e:
        debug_log(f"Skipping catalog {catalog_cfg.cdn_catalog_type}: {e}")