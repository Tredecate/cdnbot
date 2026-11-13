import discord
import json

from catalogs import CatalogManager


class AddCatalogItemModal(discord.ui.Modal):
    def __init__(self, manager: CatalogManager, category: str, schema: dict, ephemeral: bool, prefill_data: dict = {}, spawn_interaction: discord.Interaction | None = None):
        super().__init__(title=f"Add to {manager.catalog_type} / {category}")
        self.manager = manager
        self.category = category
        self.schema = schema
        self.ephemeral = ephemeral
        self.spawn_interaction = spawn_interaction
        self.field_inputs: dict[str, discord.ui.TextInput] = {}

        fields: list[str] = schema["fields"]
        defaults: dict = schema["defaults"]

        for field in fields[:5]:
            has_default = field in defaults
            default_val = defaults.get(field)

            if prefill_data and field in prefill_data:
                default_val = prefill_data[field]
                has_default = True
            
            text_input = discord.ui.TextInput(
                label=field,
                default=str(default_val) if has_default else None,
                required=not has_default,
                placeholder=f"Enter {field}...",
            )
            self.field_inputs[field] = text_input
            self.add_item(text_input)


    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=self.ephemeral)
        defaults = self.schema["defaults"]
        kwargs = {}

        for field, text_input in self.field_inputs.items():
            raw_val = text_input.value.strip()
            if not raw_val and field in defaults:
                kwargs[field] = defaults[field]
                continue

            # If the default is a list or dict, parse the input as JSON
            if isinstance(defaults.get(field), (list, dict)):
                try:
                    kwargs[field] = json.loads(raw_val)
                except json.JSONDecodeError:
                    await interaction.followup.send(
                        f"Invalid JSON for field `{field}`. Expected format like `{json.dumps(defaults[field])}`.",
                        ephemeral=True,
                    )
                    return
            else:
                kwargs[field] = raw_val

        try:
            self.manager.add_to_category(self.category, **kwargs)
        except Exception as e:
            await interaction.followup.send(f"Failed to add to catalog: {e}", ephemeral=True)
            return

        await interaction.followup.send(
            f"Successfully added item to `{self.manager.catalog_type}/{self.category}`!\n{self.manager.html_url}",
            ephemeral=self.ephemeral,
        )

        try:
            await self.spawn_interaction.delete_original_response() if self.spawn_interaction else None
        except: pass