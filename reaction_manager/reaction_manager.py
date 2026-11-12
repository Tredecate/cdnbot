# Extremely niche functionality because I like having a catalogue of my reaction images
import json

from config import settings
from log import debug_log
from bucketclient import client


class ReactionManager:
    def __init__(self):
        self._remote_state: dict | None = None
        self._local_state: dict | None = None


    def add_emoji(self, name: str, file_path: str, alt_names: list[str] = [], width: int = 35):
        pass


    def add_gif(self, name: str, file_path: str, alt_names: list[str] = [], width: int = 150):
        pass


    def add_image(self, name: str, file_path: str, alt_names: list[str] = [], width: int = 100):
        pass


    def _add_reaction(self, category: str, name: str, file_path: str, alt_names: list[str], width: int):
        pass


    def _get_state(self):
        state_file = settings.cdn_state_file
        
        if not state_file:
            raise ValueError("CDN state file is not configured.")

        try:
            state_data = client.get_file(state_file)
            self._remote_state = json.loads(state_data.decode("utf-8"))
        except Exception as e:
            debug_log(f"Failed to fetch remote state file: {e}")
            self._remote_state = None
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


    def _generate_reaction_html(self) -> str:
        self._get_state()

        if self._remote_state is None:
            raise ValueError("Remote state is not available. Cannot generate reaction HTML.")

        try:
            with open("reaction_manager/reaction_template.html", "r", encoding="utf-8") as f:
                template = f.read()
        except Exception as e:
            debug_log(f"Failed to read reaction template: {e}")
            raise ValueError("Failed to generate reaction HTML. No template available.")

        reaction_html = self._parse_state_to_html(self._remote_state, template)

        return reaction_html


    def _update_reaction_html(self):
        html_content = self._generate_reaction_html()
        html_file_path = self._remote_state.get("html_file_path", "reactions.html")

        try:
            client.upload_file(html_file_path, html_content.encode("utf-8"))
            debug_log(f"Successfully updated reaction HTML file: {html_file_path}")
        except Exception as e:
            debug_log(f"Failed to update reaction HTML file: {e}")
            raise ValueError("Failed to update reaction HTML file.")


    def _parse_state_to_html(self, state: dict, template: str) -> str:
        pass