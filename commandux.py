import discord

from bucketclient import client
from config import settings


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

    async def on_submit(self, interaction: discord.Interaction):
        name, data, url = self.media_item
        dest_path = self.path_input.value.strip()

        # Store confirmed item and its target path
        self.wizard_view.confirmed_uploads.append((name, data, url, dest_path))

        # Advance the wizard to the next media item
        self.wizard_view.current_index += 1
        await self.wizard_view.update_message(interaction)


class MediaWizardView(discord.ui.View):
    def __init__(self, media: list[tuple[str, bytes, str]]):
        super().__init__(timeout=300)
        self.media = media
        self.current_index = 0
        # Stores (name, bytes, url, dest_path)
        self.confirmed_uploads: list[tuple[str, bytes, str, str]] = []

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
            embed = self.build_current_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            # All items reviewed; execute uploads
            await self.finish(interaction)

    async def finish(self, interaction: discord.Interaction):
        self.stop()
        if not self.confirmed_uploads:
            await interaction.response.edit_message(
                content="No media selected for upload.", embed=None, view=None
            )
            return

        await interaction.response.edit_message(
            content=f"Uploading {len(self.confirmed_uploads)} item(s)...",
            embed=None,
            view=None,
        )

        uploaded_paths = []
        for name, data, url, dest_path in self.confirmed_uploads:
            try:
                client.get_file(dest_path)  # Check if file already exists
            except Exception:
                pass
            else:
                confirm_view = ConfirmView(question=f"{dest_path} already exists. Overwrite?", media_url=f"{settings.bucket_public_url}/{dest_path}")
                prompt_message = await interaction.followup.send(
                    embed=confirm_view.build_embed(),
                    view=confirm_view,
                    ephemeral=True,
                )

                await confirm_view.wait()
                await prompt_message.delete()
                
                if not confirm_view.choice:
                    continue

            try:
                client.upload_file(dest_path, data)
            except Exception as e:
                await interaction.followup.send(
                    f"Failed to upload {name} to {dest_path}: {e}", ephemeral=True
                )
            else:
                uploaded_paths.append(f"{settings.bucket_public_url}/{dest_path}")
                try:
                    client.purge_cache(f"{settings.bucket_public_url.split("://")[1]}/{dest_path}")
                except Exception as e:
                    await interaction.followup.send(
                        f"Failed to purge cache for {dest_path}: {e}", ephemeral=True
                    )

        summary = "\n".join(uploaded_paths)
        await interaction.edit_original_response(
            content=f"Uploaded {len(uploaded_paths)} item(s) to CDN:\n{summary}"
        )

    @discord.ui.button(label="Yes (Set Path)", style=discord.ButtonStyle.success)
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