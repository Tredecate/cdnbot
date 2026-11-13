import discord
import json

from discord import app_commands
from functools import partial

from bucketclient import client
from config import settings
from catalog_manager import catalog_managers, CatalogManager


class PathModal(discord.ui.Modal, title="Set Destination Path"):
    def __init__(self, wizard_view: "MediaWizardView", media_item: tuple[str, bytes, str]):
        super().__init__()
        self.wizard_view = wizard_view
        self.media_item = media_item
        name, _, _ = media_item

        self.path_input = discord.ui.TextInput(
            label=f"Path for {name}"[:45],  # Modal labels max out at 45 chars
            default=f"react/{name}",
            style=discord.TextStyle.short,
            required=True,
        )
        self.add_item(self.path_input)

        self.add_to_catalog = discord.ui.Label(
            text="Add to catalog?",
            description="You will be prompted to select a catalog and category after confirming the path.",
            component=discord.ui.Checkbox(default=False, custom_id="catalog_upload")
        )
        self.add_item(self.add_to_catalog)

    async def on_submit(self, interaction: discord.Interaction):
        name, data, url = self.media_item
        dest_path = self.path_input.value.strip()
        catalog_upload = self.add_to_catalog.component.value

        # Store confirmed item and its target path
        self.wizard_view.confirmed_uploads.append((name, data, url, dest_path, catalog_upload))

        # Advance the wizard to the next media item
        self.wizard_view.current_index += 1
        await self.wizard_view.update_message(interaction)


class MediaWizardView(discord.ui.View):
    def __init__(self, media: list[tuple[str, bytes, str]]):
        super().__init__(timeout=300)
        self.media = media
        self.current_index = 0

        # Stores (name, bytes, url, dest_path, catalog_upload)
        self.confirmed_uploads: list[tuple[str, bytes, str, str, bool]] = []

    def build_current_embed(self) -> discord.Embed:
        name, _, url = self.media[self.current_index]

        total = len(self.media)
        embed = discord.Embed(
            title=f"Media {self.current_index + 1} of {total}",
            description=f"**Name:** `{name}`\nUpload this item to the CDN?",
        )
        embed.set_thumbnail(url=url)

        return embed

    async def update_message(self, interaction: discord.Interaction):
        if self.current_index < len(self.media):
            await interaction.response.edit_message(embed=self.build_current_embed(), view=self)
        else:
            await self.finish(interaction)

    async def finish(self, interaction: discord.Interaction):
        self.stop()

        if not self.confirmed_uploads:
            await interaction.response.edit_message(content="No media selected for upload.", embed=None, view=None)
            return

        await interaction.response.edit_message(
            content=f"Uploading {len(self.confirmed_uploads)} item(s)...",
            embed=None,
            view=None,
        )

        uploaded_paths = []
        for name, data, url, dest_path, catalog_upload in self.confirmed_uploads:
            try:
                client.get_file(dest_path)  # Check if file already exists
            except Exception: pass
            else:
                confirm_view = ConfirmView(question=f"{dest_path} already exists. Overwrite?", media_url=f"{settings.bucket_public_url}/{dest_path}")
                prompt_message = await interaction.followup.send(
                    embed=confirm_view.build_embed(),
                    view=confirm_view,
                    ephemeral=True,
                )

                await confirm_view.wait()
                await prompt_message.delete()

                if confirm_view.choice == False:
                    continue

            try:
                client.upload_file(dest_path, data)
            except Exception as e:
                await interaction.followup.send(f"Failed to upload {name} to {dest_path}: {e}", ephemeral=True)
                return

            selected_catalog = None

            if catalog_upload:
                # Prepare catalog options
                catalog_options = [("Nevermind...", None), *catalog_managers.keys()]

                # Prompt user to select catalog 
                catalog_select = DynamicButtonView(
                    question=f"Which catalog would you like to add {name} to?",
                    media_url=f"{settings.bucket_public_url}/{dest_path}",
                    buttons=catalog_options
                )
                prompt_message = await interaction.followup.send(
                    embed=catalog_select.build_embed(),
                    view=catalog_select,
                    ephemeral=True,
                )
                await catalog_select.wait()
                await prompt_message.delete()

                selected_catalog = catalog_select.choice

            if selected_catalog:
                manager = catalog_managers.get(selected_catalog)
                if not manager or not manager.is_initialized():
                    await interaction.followup.send(f"Whoops! {selected_catalog} is not initialized.", ephemeral=True)
                
                else:
                    # Prompt user to select category
                    category_options = []
                    prefill_data = {
                        "name": name,
                        "url": f"{settings.bucket_public_url}/{dest_path}",
                    }

                    async def category_callback(interaction: discord.Interaction, cat_name: str, prefill_data: dict):
                        await interaction.response.send_modal(
                            AddCatalogItemModal(
                                manager,
                                cat_name,
                                manager.get_category_schema(cat_name),
                                ephemeral=True,
                                prefill_data=prefill_data,
                                spawn_interaction=interaction
                            )
                        )

                    for cat_name in manager.get_category_names():
                        category_options.append((cat_name, cat_name, partial(category_callback, cat_name=cat_name, prefill_data=prefill_data)))

                    category_options.append(("Nevermind...", None, None))

                    category_select = DynamicButtonView(
                        question=f"Which category in {selected_catalog} would you like to add {name} to?",
                        media_url=f"{settings.bucket_public_url}/{dest_path}",
                        buttons=category_options
                    )
                    prompt_message = await interaction.followup.send(
                        embed=category_select.build_embed(),
                        view=category_select,
                        ephemeral=True,
                    )

                    try:
                        await category_select.wait()
                    except Exception as e:
                        await interaction.followup.send(f"Failed to select category for {name}: {e}", ephemeral=True)

            uploaded_paths.append(f"{settings.bucket_public_url}/{dest_path}")

            try:
                client.purge_cache(f"{settings.bucket_public_url.split("://")[1]}/{dest_path}")
            except Exception as e:
                await interaction.followup.send(f"Failed to purge cache for {dest_path}: {e}", ephemeral=True)

        summary = "\n".join(uploaded_paths)

        ask_should_announce = ConfirmView(question="Announce uploaded items in the channel?", default_value=False)
        prompt_message = await interaction.followup.send(
            embed=ask_should_announce.build_embed(),
            view=ask_should_announce,
            ephemeral=True,
        )

        await ask_should_announce.wait()
        await prompt_message.delete()

        if ask_should_announce.choice:
            await interaction.followup.send(f"Uploaded {len(uploaded_paths)} item(s) to CDN:\n{summary}", ephemeral=False)
        else:
            await interaction.edit_original_response(content=f"Uploaded {len(uploaded_paths)} item(s) to CDN:\n{summary}")

    @discord.ui.button(label="Yes (Upload)", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        current_item = self.media[self.current_index]
        # Button interaction allows opening a Modal directly
        await interaction.response.send_modal(PathModal(self, current_item))

    @discord.ui.button(label="No (Skip)", style=discord.ButtonStyle.secondary)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_index += 1
        await self.update_message(interaction)


class ConfirmView(discord.ui.View):
    def __init__(self, question: str, default_value: bool = False, media_url: str = ""):
        super().__init__(timeout=60)
        self.choice: bool = default_value
        self.question = question
        self.media_url = media_url

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Confirmation",
            description=self.question,
            color=discord.Color.blue()
        )
        if self.media_url:
            embed.set_image(url=self.media_url)
        
        return embed

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = True
        self.stop()
        await interaction.response.defer(ephemeral=True)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.choice = False
        self.stop()
        await interaction.response.defer(ephemeral=True)


class DynamicButtonView(discord.ui.View):
    def __init__(self, question: str, default_value: str | None = None, media_url: str = "", buttons: list[str | tuple[str, any]] = []):
        super().__init__(timeout=60)
        self.choice = default_value
        self.question = question
        self.media_url = media_url

        for option_button in buttons:
            if isinstance(option_button, str):
                button = discord.ui.Button(label=option_button, style=discord.ButtonStyle.primary, custom_id=option_button)
                button.callback = self.button_callback
                self.add_item(button)

            elif isinstance(option_button, tuple) and len(option_button) == 2:
                label, custom_id = option_button
                button = discord.ui.Button(label=label, style=discord.ButtonStyle.primary, custom_id=custom_id)
                button.callback = self.button_callback
                self.add_item(button)

            elif isinstance(option_button, tuple) and len(option_button) == 3:
                label, custom_id, callfunc = option_button
                button = discord.ui.Button(label=label, custom_id=custom_id)

                if callfunc is None:
                    button.callback = self.button_callback
                    self.add_item(button)
                    return
                
                button.callback = self._create_custom_callback(callfunc, custom_id)
                self.add_item(button)

    def _create_custom_callback(self, original_callback, custom_id):
        async def wrapped_callback(interaction: discord.Interaction):
            self.choice = custom_id
            self.stop()
            await original_callback(interaction)
        return wrapped_callback

    def build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Confirmation",
            description=self.question,
            color=discord.Color.blue()
        )
        if self.media_url:
            embed.set_image(url=self.media_url)
        
        return embed

    async def button_callback(self, interaction: discord.Interaction):
        self.choice = interaction.data['custom_id']
        self.stop()
        await interaction.response.defer(ephemeral=True)


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


async def catalog_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=cat_type, value=cat_type) for cat_type in catalog_managers.keys() if current.lower() in cat_type.lower()][:25]


async def category_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    selected_catalog = interaction.namespace.catalog
    manager = catalog_managers.get(selected_catalog)

    if not manager:
        return []
    
    return [app_commands.Choice(name=cat, value=cat) for cat in manager.get_category_names() if current.lower() in cat.lower()][:25]