import discord

from discord import app_commands
from ui_components import MediaWizardView, AddCatalogItemModal, DynamicButtonView, catalog_autocomplete, category_autocomplete

from utils import bucket_client, settings, debug_log
from utils.media import extract_media_from_message
from catalogs.catalog_manager import catalog_managers


class CDNBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


intents = discord.Intents.default()
bot = CDNBot(intents=intents)


@bot.tree.command(name="addtocatalog", description="Add an item to a configured CDN catalog")
@app_commands.describe(catalog="The target catalog", category="The category within the catalog")
@app_commands.autocomplete(catalog=catalog_autocomplete, category=category_autocomplete)
@app_commands.describe(ephemeral="Whether the response should be visible to everyone or just you")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def addtocatalog(interaction: discord.Interaction, catalog: str, category: str, ephemeral: bool = True):
    manager = catalog_managers.get(catalog)

    if not manager or not manager.is_initialized():
        failure_mode = manager.failuremode if manager else "Manager not found"
        debug_log(f"Failed to add item to catalog {catalog}: {failure_mode}", 1)
        await interaction.response.send_message(f"Catalog {catalog} is not initialized. Cannot add to catalog. {failure_mode}", ephemeral=True)
        return

    try:
        schema = manager.get_category_schema(category)
    except Exception as e:
        await interaction.response.send_message(f"Failed to get category schema for {category}: {e}", ephemeral=True)
        return

    modal = AddCatalogItemModal(manager, category, schema, ephemeral)
    await interaction.response.send_modal(modal)


@bot.tree.command(name="managecatalog", description="Manage a configured CDN catalog")
@app_commands.describe(catalog="The catalog to manage")
@app_commands.autocomplete(catalog=catalog_autocomplete)
@app_commands.describe(ephemeral="Whether the response should be visible to everyone or just you")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def managecatalog(interaction: discord.Interaction, catalog: str, ephemeral: bool = True):
    manager = catalog_managers.get(catalog)

    if not manager:
        await interaction.response.send_message(f"Catalog {catalog} does not exist. Cannot manage catalog.", ephemeral=True)
        return

    options = {
        "Refresh Catalog": (manager.refresh_catalog, None, lambda: "Refresh successful"),
        "Check Initialization Status": (lambda: manager.is_initialized(),),
        "Reinitialize Catalog": (manager.initialize_catalog, False, lambda: manager.failuremode),
        "Reinitialize Catalog (Rebuild if Needed)": (manager.initialize_catalog, False, lambda: manager.failuremode, (True,)),
        "Reinitialize Catalog (Force Rebuild) ⚠": (manager.initialize_catalog, False, lambda: manager.failuremode, (True, True)),
        None: (lambda: None,)
    }

    view = DynamicButtonView("What would you like to do?", buttons=list(options.keys()))
    await interaction.response.send_message("Manage your catalog:", view=view, ephemeral=ephemeral)
    await view.wait()

    choice = options[view.choice]

    returned_data = "No data"

    try:
        args = choice[3] if len(choice) >= 4 else ()
        result = choice[0](*args)
    except Exception as e:
        await interaction.edit_original_response(content=f"Failed to perform action: {e}", view=None)
        return

    if len(choice) > 1:
        returned_data = choice[2]() if result == choice[1] else returned_data

    await interaction.edit_original_response(content=f"Action '{view.choice}' completed. Result: {returned_data}", view=None)


@bot.tree.command(name="getfiletree", description="Get the file tree for a given path in the CDN")
@app_commands.describe(path="The path to get the file tree for")
@app_commands.describe(ephemeral="Whether the response should be visible to everyone or just you")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def getfiletree(interaction: discord.Interaction, path: str = "", ephemeral: bool = True):
    try:
        file_tree = bucket_client.get_file_tree(path)
    except Exception as e:
        await interaction.response.send_message(f"Failed to get file tree for {path}: {e}", ephemeral=True)
        return
    
    await interaction.response.send_message(f"File tree for {path}:\n```\n{"\n".join(sorted(file_tree))}\n```", ephemeral=ephemeral)


@bot.tree.command(name="purgecache", description="Purge the cache for all files under a given prefix in the CDN")
@app_commands.describe(prefix="The prefix of the files to purge from the cache")
@app_commands.describe(ephemeral="Whether the response should be visible to everyone or just you")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def purgecache(interaction: discord.Interaction, prefix: str = settings.bucket_public_url.split('://')[1], ephemeral: bool = True):
    try:
        bucket_client.purge_cache(prefix)
    except Exception as e:
        await interaction.response.send_message(f"Failed to purge cache for {prefix}: {e}", ephemeral=True)
        return
    
    await interaction.response.send_message(f"Cache purged for {prefix}.", ephemeral=ephemeral)


@bot.tree.command(name="move", description="Move a file from one path to another in the CDN")
@app_commands.describe(source="The path of the file to move")
@app_commands.describe(destination="The path to move the file to")
@app_commands.describe(purge_cache="Whether to purge the cache for the source and destination paths after moving")
@app_commands.describe(ephemeral="Whether the response should be visible to everyone or just you")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def move(interaction: discord.Interaction, source: str, destination: str, purge_cache: bool = True, ephemeral: bool = True):
    try:
        file_data = bucket_client.get_file(source)
    except Exception as e:
        await interaction.response.send_message(f"File {source} does not exist in the CDN: {e}", ephemeral=True)
        return

    try:
        bucket_client.get_file(destination)
    except Exception: pass
    else:
        await interaction.response.send_message(f"File {destination} already exists in the CDN. Cannot move {source} to {destination}.", ephemeral=True)
        return
    
    try:
        bucket_client.upload_file(destination, file_data)
    except Exception as e:
        await interaction.response.send_message(f"Failed to move {source} to {destination}: {e}. Nothing was changed.", ephemeral=True)
        return
    
    await interaction.response.send_message(f"File {source} moved to {destination} in the CDN.", ephemeral=ephemeral)

    if purge_cache:
        full_source = f"{settings.bucket_public_url.split('://')[1].rstrip('/')}/{source.lstrip('/')}"
        full_destination = f"{settings.bucket_public_url.split('://')[1].rstrip('/')}/{destination.lstrip('/')}"
        try:
            bucket_client.purge_cache(full_source)
        except Exception as e:
            await interaction.followup.send(f"Failed to purge cache for {full_source}: {e}", ephemeral=True)

        try:
            bucket_client.purge_cache(full_destination)
        except Exception as e:
            await interaction.followup.send(f"Failed to purge cache for {full_destination}: {e}", ephemeral=True)

    try:
        bucket_client.delete_file(source)
    except Exception as e:
        await interaction.followup.send(f"Failed to delete {source} from the CDN: {e}", ephemeral=True)


@bot.tree.command(name="delete", description="Delete a file from the CDN")
@app_commands.describe(path="The path of the file to delete")
@app_commands.describe(purge_cache="Whether to purge the cache for the file after deletion")
@app_commands.describe(ephemeral="Whether the response should be visible to everyone or just you")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def delete(interaction: discord.Interaction, path: str, purge_cache: bool = True, ephemeral: bool = True):
    try:
        bucket_client.get_file(path)
    except Exception as e:
        await interaction.response.send_message(f"File {path} does not exist in the CDN: {e}", ephemeral=True)
        return

    try:
        bucket_client.delete_file(path)
    except Exception as e:
        await interaction.response.send_message(f"Failed to delete {path} from the CDN: {e}", ephemeral=True)
        return
    
    await interaction.response.send_message(f"File {path} deleted from the CDN.", ephemeral=ephemeral)

    if purge_cache:
        full_path = f"{settings.bucket_public_url.split('://')[1].rstrip('/')}/{path.lstrip('/')}"
        try:
            bucket_client.purge_cache(full_path)
        except Exception as e:
            await interaction.followup.send(f"Failed to purge cache for {full_path}: {e}", ephemeral=True)


@bot.tree.context_menu(name="Upload to CDN")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def upload_to_cdn(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.defer(ephemeral=True)

    media = await extract_media_from_message(message)
    if not media:
        await interaction.followup.send("No media found in that message.", ephemeral=True)
        return

    view = MediaWizardView(media)
    await interaction.followup.send(embed=view.build_current_embed(), view=view, ephemeral=True)


def main():
    debug_log("Starting CDNBot...", 0)
    debug_log(f"Settings: {settings}", 2)
    bot.run(settings.discord_token.get_secret_value())


if __name__ == "__main__":
    main()