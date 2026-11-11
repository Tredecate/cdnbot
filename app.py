import discord
import re
import requests

from discord import app_commands

from config import settings
from log import debug_log
from bucketclient import client
from commandux import MediaWizardView


class CDNBot(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


intents = discord.Intents.default()
bot = CDNBot(intents=intents)


@bot.tree.command(name="getfiletree", description="Get the file tree for a given path in the CDN")
@app_commands.describe(path="The path to get the file tree for")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def getfiletree(interaction: discord.Interaction, path: str = ""):
    try:
        file_tree = client.get_file_tree(path)
    except Exception as e:
        await interaction.response.send_message(f"Failed to get file tree for {path}: {e}", ephemeral=True)
    else:
        await interaction.response.send_message(f"File tree for {path}:\n```\n{"\n".join(sorted(file_tree))}\n```", ephemeral=True)


@bot.tree.command(name="purgecache", description="Purge the cache for all files under a given prefix in the CDN")
@app_commands.describe(prefix="The prefix of the files to purge from the cache")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def purgecache(interaction: discord.Interaction, prefix: str):
    prefix = settings.bucket_public_url.rstrip("/") + "/" + prefix.lstrip("/")
    try:
        client.purge_cache(prefix)
    except Exception as e:
        await interaction.response.send_message(f"Failed to purge cache for {prefix}: {e}", ephemeral=True)
    else:
        await interaction.response.send_message(f"Cache purged for {prefix}.", ephemeral=True)


@bot.tree.command(name="move", description="Move a file from one path to another in the CDN")
@app_commands.describe(source="The path of the file to move")
@app_commands.describe(destination="The path to move the file to")
@app_commands.describe(purge_cache="Whether to purge the cache for the source and destination paths after moving")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def move(interaction: discord.Interaction, source: str, destination: str, purge_cache: bool = True):
    try:
        file_data = client.get_file(source)
    except Exception as e:
        await interaction.response.send_message(f"File {source} does not exist in the CDN: {e}", ephemeral=True)
        return

    try:
        client.get_file(destination)
    except Exception:
        pass
    else:
        await interaction.response.send_message(f"File {destination} already exists in the CDN. Cannot move {source} to {destination}.", ephemeral=True)
        return
    
    try:
        client.upload_file(destination, file_data)
    except Exception as e:
        await interaction.response.send_message(f"Failed to move {source} to {destination}: {e}. Nothing was changed.", ephemeral=True)
        return
    else:
        await interaction.response.send_message(f"File {source} moved to {destination} in the CDN.", ephemeral=True)

    if purge_cache:
        full_source = settings.bucket_public_url.rstrip("/") + "/" + source.lstrip("/")
        full_destination = settings.bucket_public_url.rstrip("/") + "/" + destination.lstrip("/")
        try:
            client.purge_cache(full_source)
        except Exception as e:
            await interaction.followup.send(f"Failed to purge cache for {full_source}: {e}", ephemeral=True)

        try:
            client.purge_cache(full_destination)
        except Exception as e:
            await interaction.followup.send(f"Failed to purge cache for {full_destination}: {e}", ephemeral=True)

    try:
        client.delete_file(source)
    except Exception as e:
        await interaction.response.send_message(f"Failed to delete {source} from the CDN: {e}", ephemeral=True)


@bot.tree.command(name="delete", description="Delete a file from the CDN")
@app_commands.describe(path="The path of the file to delete")
@app_commands.describe(purge_cache="Whether to purge the cache for the file after deletion")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def delete(interaction: discord.Interaction, path: str, purge_cache: bool = True):
    try:
        client.get_file(path)
    except Exception as e:
        await interaction.response.send_message(f"File {path} does not exist in the CDN: {e}", ephemeral=True)
        return

    try:
        client.delete_file(path)
    except Exception as e:
        await interaction.response.send_message(f"Failed to delete {path} from the CDN: {e}", ephemeral=True)
        return
    else:
        await interaction.response.send_message(f"File {path} deleted from the CDN.", ephemeral=True)

    if purge_cache:
        full_path = settings.bucket_public_url.rstrip("/") + "/" + path.lstrip("/")
        try:
            client.purge_cache(full_path)
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


async def extract_media_from_message(message: discord.Message):
    # Get emojis from the message
    emojis = re.findall(r"<a?:[a-zA-Z0-9_]+:\d+>", message.content)

    # Get reactions from the message
    reactions = message.reactions

    # Get attachments from the message
    attachments = message.attachments

    # Get embeds from the message
    embeds = message.embeds

    # Get stickers from the message
    stickers = message.stickers

    media = [item for sublist in [
        await process_emojis(emojis),
        await process_reactions(reactions),
        await process_attachments(attachments),
        await process_embeds(embeds),
        await process_stickers(stickers)
    ] for item in sublist if len(sublist) > 0]

    debug_log(f"Number of media items: {len(media)}", 1)
    debug_log(media, 2)
    return media


async def process_emojis(emojis: list[str]):
    debug_log(emojis, 1)

    if len(emojis) == 0:
        return []
    
    media = []

    for raw_emoji in set(emojis):
        anim, name, emoji_id = re.match(r"<(a?):([a-zA-Z0-9_]+):(\d+)>", raw_emoji).groups()

        emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.webp{'?animated=true' if anim else ''}"

        media.append((name + ".webp", requests.get(emoji_url).content, emoji_url))

    debug_log(media, 2)
    return media


async def process_reactions(reactions: list[discord.Reaction]):
    debug_log(reactions, 1)

    if len(reactions) == 0:
        return []

    raw_emoji_list = []

    for reaction in reactions:
        if isinstance(reaction.emoji, (discord.Emoji, discord.PartialEmoji)):
            raw_emoji_list.append(f"<{'a' if reaction.emoji.animated else ''}:{reaction.emoji.name}:{reaction.emoji.id}>")

    debug_log(raw_emoji_list, 2)
    media = await process_emojis(raw_emoji_list)

    debug_log(media, 2)
    return media


async def process_attachments(attachments: list[discord.Attachment]):
    debug_log(attachments, 1)

    if len(attachments) == 0:
        return []

    media = [(attachment.filename, await attachment.read(), attachment.url) for attachment in attachments]

    debug_log(media, 2)
    return media


async def process_embeds(embeds: list[discord.Embed]):
    debug_log(embeds, 1)

    if len(embeds) == 0:
        return []

    media = []

    for embed in embeds:
        if embed.image:
            media.append((embed.image.url.split("/")[-1], requests.get(embed.image.url).content, embed.image.url))
        if embed.thumbnail:
            media.append((embed.thumbnail.url.split("/")[-1], requests.get(embed.thumbnail.url).content, embed.thumbnail.url))
        if embed.video:
            media.append((embed.video.url.split("/")[-1], requests.get(embed.video.url).content, embed.video.url))

    debug_log(media, 2)
    return media


async def process_stickers(stickers: list[discord.Sticker]):
    debug_log(stickers, 1)

    if len(stickers) == 0:
        return []

    media = [(sticker.name + "." + sticker.format.name, await sticker.read(), sticker.url) for sticker in stickers if sticker.format != discord.StickerFormatType.lottie]

    debug_log(media, 2)
    return media


def main():
    bot.run(settings.discord_token.get_secret_value())


if __name__ == "__main__":
    main()