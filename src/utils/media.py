import discord
import re
import requests

from utils import debug_log


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