# Extremely niche functionality because I like having a catalogue of my reaction images
import json
import copy

from config import settings
from log import debug_log
from bucketclient import client


class ReactionManager:
    def __init__(self):
        self._remote_state: dict | None = None
        self._local_state: dict | None = None


    def add_kaomoji(self, alt: str, data: str):
        pass


    def add_emoji(self, name: str, file_path: str, alt_names: list[str] = [], width: int = None):
        pass


    def add_gif(self, name: str, file_path: str, alt_names: list[str] = [], width: int = None):
        pass


    def add_image(self, name: str, file_path: str, alt_names: list[str] = [], width: int = None):
        pass


    def _add_reaction(self, category: str, item_data: dict):
        self._get_state()
        remote_state_bkp = copy.deepcopy(self._remote_state)

        self._local_state["reactions"][category]["items"].append(item_data)

        try:
            self._update_state()
            self._update_reaction_html()
        except Exception as e:
            debug_log(f"Failed to update state or reaction HTML: {e}. Rolling back changes.")
            self._local_state = remote_state_bkp
            self._update_state()
            self._update_reaction_html()
            raise ValueError("Failed to update state or reaction HTML. Changes rolled back.")


    def _get_state(self):
        state_file = settings.cdn_state_file
        
        if not state_file:
            raise ValueError("CDN state file is not configured.")

        try:
            state_data = client.get_file(state_file)
            self._remote_state = json.loads(state_data.decode("utf-8"))
            self._local_state = json.loads(state_data.decode("utf-8"))
        except Exception as e:
            debug_log(f"Failed to fetch remote state file: {e}")
            self._local_state = None
            raise ValueError("Failed to fetch remote state file.")


    def _update_state(self):
        state_file = settings.cdn_state_file
        
        if not state_file:
            raise ValueError("CDN state file is not configured.")

        if self._local_state is None:
            raise ValueError("Local state is not set. Cannot update remote state.")

        try:
            client.upload_file(state_file, json.dumps(self._local_state).encode("utf-8"))
            debug_log(f"Successfully updated remote state file: {state_file}")
        except Exception as e:
            debug_log(f"Failed to update remote state file: {e}")
            raise ValueError("Failed to update remote state file.")

        self._get_state()


    def _generate_reaction_html(self, state: dict) -> str:
        try:
            with open("reaction_manager/reaction_template.html", "r", encoding="utf-8") as f:
                template = f.read()
        except Exception as e:
            debug_log(f"Failed to read reaction template: {e}")
            raise ValueError("Failed to generate reaction HTML. No template available.")

        reaction_html = self._parse_state_to_html(state["reactions"], template)

        return reaction_html


    def _update_reaction_html(self):
        if self._local_state is None:
            raise ValueError("State is not available. Cannot update reaction HTML.")
        
        html_content = self._generate_reaction_html(self._local_state)

        state_meta = self._local_state["reactions"]["meta"]
        html_file_path = state_meta.get("root") + state_meta.get("html_catalog")

        try:
            client.upload_file(html_file_path, html_content.encode("utf-8"))
            debug_log(f"Successfully updated reaction HTML file: {html_file_path}")
        except Exception as e:
            debug_log(f"Failed to update reaction HTML file: {e}")
            raise ValueError("Failed to update reaction HTML file.")


    def _parse_state_to_html(self, state_section: dict, template: str) -> str:
        section_meta = state_section.get("meta", None)
        
        if section_meta is None or section_meta.get("type", "") != "cdn_section":
            raise ValueError("State section is invalid or missing 'meta' information.")

        for category in section_meta.get("categories", []):
            category_data = state_section.get(category, None)
            
            if category_data is None or category_data.get("type", "") != "cdn_category":
                debug_log(f"Category '{category}' is missing or invalid.")
                continue

            start_marker = f"<!-- startsect:{category} -->"
            end_marker = f"<!-- endsect:{category} -->"

            html_schema = category_data.get("html_schema", "")
            fields = category_data.get("fields", [])
            defaults = category_data.get("defaults", {})

            for item in category_data.get("items", []):
                item_html = html_schema
                for field in fields:
                    value = item.get(field, defaults.get(field, ""))
                    item_html = item_html.replace("${" + field + "}", str(value))

                template = template.replace(end_marker, item_html + "\n" + end_marker)

        return template