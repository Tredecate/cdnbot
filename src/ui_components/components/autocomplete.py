import discord

from discord import app_commands

from catalogs.catalog_manager import catalog_managers


async def catalog_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return [app_commands.Choice(name=cat_type, value=cat_type) for cat_type in catalog_managers.keys() if current.lower() in cat_type.lower()][:25]


async def category_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    selected_catalog = interaction.namespace.catalog
    manager = catalog_managers.get(selected_catalog)

    if not manager:
        return []
    
    return [app_commands.Choice(name=cat, value=cat) for cat in manager.get_category_names() if current.lower() in cat.lower()][:25]