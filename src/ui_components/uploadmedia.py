import discord

from functools import partial

from ui_components import DynamicButtonView, ConfirmView, AddCatalogItemModal
from utils import bucket_client, settings
from catalogs.catalog_manager import catalog_managers


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
                bucket_client.get_file(dest_path)  # Check if file already exists
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
                bucket_client.upload_file(dest_path, data)
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
                bucket_client.purge_cache(f"{settings.bucket_public_url.split("://")[1]}/{dest_path}")
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