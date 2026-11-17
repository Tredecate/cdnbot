import json

import discord
import concurrent.futures

from utils import MediaItem, Stage
from utils.log import debug_log
from utils.bucketclient import bucket_client
from catalogs import get_active_catalogs

from .components import CountableContainer, PaginatedLayoutView, ToggleButton, ModalSpawnButton, PageControls


class UploadConfigCatalogModal(discord.ui.Modal):
    def __init__(self, wizard_view: "MediaProcessView", media_item: MediaItem):
        super().__init__(title="Catalog Selection")
        self.media_item = media_item
        self.wizard_view = wizard_view

        catalog_options = [
            discord.RadioGroupOption(
                label=catalog, value=catalog,
                default=media_item.catalog == catalog
            ) for catalog in get_active_catalogs().keys()
        ]

        self.catalog_select = discord.ui.RadioGroup(
            options=[discord.RadioGroupOption(
                label="None", value=0, 
                default=media_item.catalog in (None, 0)
            )] + catalog_options,
        )
        self.add_item(discord.ui.Label(text=f"Select Catalog for:", description=media_item.name, component=self.catalog_select))

    async def on_submit(self, interaction: discord.Interaction):
        selected_catalog = self.catalog_select.value
        self.media_item.catalog = None if selected_catalog in (None, 0, "0") else selected_catalog

        await self.wizard_view.update_page(interaction)


class UploadConfigCategoryModal(discord.ui.Modal):
    def __init__(self, wizard_view: "MediaProcessView", media_item: MediaItem):
        super().__init__(title="Category Selection")
        self.media_item = media_item
        self.wizard_view = wizard_view

        self.category_select = None
        self.single_category = None

        selected_catalog = get_active_catalogs().get(media_item.catalog)

        if selected_catalog is None:
            self.add_item(discord.ui.TextDisplay("No catalog selected. Please select a catalog first."))
            return

        category_options = [
            discord.RadioGroupOption(
                label=category, value=category, 
                default=media_item.category == category
            ) for category in selected_catalog.get_category_names()
        ]

        match len(category_options):
            case 0:
                self.add_item(discord.ui.TextDisplay("No categories available in the selected catalog."))
                self.single_category = None
                return
            case 1:
                self.single_category = category_options[0].value
                self.add_item(discord.ui.TextDisplay("Only one category available in the selected catalog."))
            case _:
                self.category_select = discord.ui.RadioGroup(options=category_options)
                self.add_item(discord.ui.Label(text=f"Select Category for:", description=media_item.name, component=self.category_select))

        self.auto_set_path = discord.ui.Checkbox(default=True)
        self.add_item(discord.ui.Label(text="Automatically set path based on category?", component=self.auto_set_path))

    async def on_submit(self, interaction: discord.Interaction):
        selected_category = self.category_select.value if self.category_select else self.single_category
        self.media_item.category = selected_category

        if self.auto_set_path.value:
            category_root = get_active_catalogs()[self.media_item.catalog].get_category_schema(self.media_item.category)["root"]
            self.media_item.path = f"{category_root.rstrip('/')}/{self.media_item.name}"

        await self.wizard_view.update_page(interaction)


class UploadConfigPathModal(discord.ui.Modal):
    def __init__(self, wizard_view: "MediaProcessView", media_item: MediaItem):
        super().__init__(title="Upload Path Configuration")
        self.media_item = media_item
        self.wizard_view = wizard_view

        self.path_input = discord.ui.TextInput(
            style=discord.TextStyle.short,
            default=media_item.path or f"etc/{media_item.name}",
        )
        self.add_item(discord.ui.Label(text=f"Set Upload Path for:", description=media_item.name, component=self.path_input))

    async def on_submit(self, interaction: discord.Interaction):
        self.media_item.path = self.path_input.value.strip()
        self.media_item.name = self.media_item.path.split("/")[-1]

        await self.wizard_view.update_page(interaction)


class UploadConfigContainer(CountableContainer["MediaProcessView"]):
    def __init__(self, wizard_view: "MediaProcessView", media_item: MediaItem):
        super().__init__()
        self.media_item = media_item

        self.header = self.add_item(discord.ui.Section(
            discord.ui.TextDisplay(
                f"# Configure upload for:\n`{media_item.name}`\n" + 
                f"## Selected Catalog\n- `{self.media_item.catalog}`\n" +
                f"## Selected Category\n- `{self.media_item.category}`\n" +
                f"## Upload Path\n- `{self.media_item.path}`"
            ), accessory=discord.ui.Thumbnail(media=media_item.url)
        ))
        
        self.actions = self.add_item(discord.ui.ActionRow(
            ToggleButton(attribute_holder=media_item, attribute_name="upload"),
            ModalSpawnButton("Select Catalog", UploadConfigCatalogModal(wizard_view, media_item), disabled=not media_item.upload),
            ModalSpawnButton("Select Category", UploadConfigCategoryModal(wizard_view, media_item), disabled=not media_item.catalog),
            ModalSpawnButton("Set Path", UploadConfigPathModal(wizard_view, media_item), disabled=not media_item.upload),
        ))


class OverwriteToggleContainer(CountableContainer["MediaProcessView"]):
    def __init__(self, wizard_view: "MediaProcessView", media_item: MediaItem):
        super().__init__()
        self.wizard_view = wizard_view
        self.item = media_item
        self.toggle_button = ToggleButton(attribute_holder=media_item, attribute_name="overwrite_confirmed")

        self.thumbnail_section = discord.ui.Section(
            discord.ui.TextDisplay(f"`{media_item.path}` already exists in the bucket!\n-# {media_item.public_url}"),
            accessory=discord.ui.Thumbnail(media=media_item.url)
        )
        self.button_section = discord.ui.Section(
            discord.ui.TextDisplay("Allow overwrite?\n-# (Click to toggle)"),
            accessory=self.toggle_button
        )

        self.add_item(self.thumbnail_section)
        self.add_item(self.button_section)


class CategorySchemaConfigModal(discord.ui.Modal):
    def __init__(self, wizard_view: "MediaProcessView", media_item: MediaItem, fields, defaults):
        super().__init__(title="Category Schema Data Configuration")
        self.media_item = media_item
        self.wizard_view = wizard_view
        self.fields = fields
        self.defaults = defaults

        self.inputs = {}

        for field in fields[:5]:
            has_default = field in defaults
            default_val = defaults.get(field)

            if media_item.category_schema_data and field in media_item.category_schema_data:
                default_val = media_item.category_schema_data[field]
                has_default = True

            text_input = discord.ui.TextInput(
                default=str(default_val) if has_default else None,
                placeholder=str(default_val) if has_default else f"Enter {field}...",
                required=not has_default
            )
            self.inputs[field] = text_input
            self.add_item(discord.ui.Label(text=f"Set value for:", description=field, component=text_input))

    async def on_submit(self, interaction: discord.Interaction):
        for field, text_input in self.inputs.items():
            raw_val = text_input.value.strip()
            if not raw_val and field in self.defaults:
                self.media_item.category_schema_data[field] = self.defaults[field]
                continue

            # If the default is a list or dict, parse the input as JSON
            if isinstance(self.defaults.get(field), (list, dict)):
                try:
                    self.media_item.category_schema_data[field] = json.loads(raw_val)
                except json.JSONDecodeError:
                    self.media_item.category_schema_data[field] = raw_val
            else:
                self.media_item.category_schema_data[field] = raw_val

        await self.wizard_view.update_page(interaction)


class CategorySchemaConfigContainer(CountableContainer["MediaProcessView"]):
    def __init__(self, wizard_view: "MediaProcessView", media_item: MediaItem):
        super().__init__()
        self.wizard_view = wizard_view
        self.item = media_item

        self.manager = get_active_catalogs().get(media_item.catalog)
        self.category_schema = self.manager.get_category_schema(media_item.category) if self.manager else None

        self.thumbnail_section = discord.ui.Section(
            discord.ui.TextDisplay(f"`{media_item.name}`\n- **Catalog:** `{media_item.catalog}`\n- **Category:** `{media_item.category}`"),
            accessory=discord.ui.Thumbnail(media=media_item.url)
        )
        self.add_item(self.thumbnail_section)

        if not self.category_schema:
            self.add_item(discord.ui.TextDisplay("No catalog or category selected. Please select a catalog and category first."))
            return

        fields = self.category_schema.get("fields")
        defaults = self.category_schema.get("defaults")

        # Can only have 5 fields per Modal, so add 1 button per 5 fields to spawn a modal for that set of fields

        action_row = discord.ui.ActionRow()

        for i in range(0, len(fields), 5):
            field_subset = fields[i:i+5]
            action_row.add_item(ModalSpawnButton("Edit Catalog Schema Data", CategorySchemaConfigModal(wizard_view, media_item, field_subset, defaults)))

        self.add_item(action_row)


class ReviewContainer(CountableContainer["MediaProcessView"]):
    def __init__(self, wizard_view: "MediaProcessView", media_item: MediaItem):
        super().__init__()
        self.wizard_view = wizard_view
        self.item = media_item

        item_recap = (
            f"## `{media_item.name}`\n" +
            f"- **Path:** `{media_item.path}`\n" +
            (
                f"- **Overwriting:** `{media_item.overwrite_confirmed}`\n"
                if media_item.overwrite_confirmed else ""
            ) +
            (
                f"- **Catalog:** `{media_item.catalog}`\n" +
                f"- **Category:** `{media_item.category}`\n" +
                f"## Category Schema Data:\n" +
                "".join(
                    f"- **{field}:** `{value}`\n"
                    for field, value in media_item.category_schema_data.items()
                )
                if media_item.catalog_configured else ""
            )
        )

        debug_log(f"Reviewing item: {media_item.name}\n{item_recap}", 2)

        self.thumbnail_section = discord.ui.Section(
            discord.ui.TextDisplay(item_recap),
            accessory=discord.ui.Thumbnail(media=media_item.url)
        )
        self.add_item(self.thumbnail_section)


class UploadStatusContainer(CountableContainer["MediaProcessView"]):
    def __init__(self, wizard_view: "MediaProcessView", media_item: MediaItem):
        super().__init__()
        self.wizard_view = wizard_view
        self.item = media_item

        item_recap = (
            f"## `{media_item.name}`\n" +
            (
                f"- Upload Successful!\n"
                if media_item.upload_success else
                f"- Upload Failed!\n"
            ) +
            (
                f"- Cataloged Successfully!\n"
                if media_item.catalog_success else
                f"- Cataloging Failed!\n"
                if media_item.catalog_configured else
                ""
            ) +
            f"## Public URL\n{media_item.public_url}"
        )

        self.thumbnail_section = discord.ui.Section(
            discord.ui.TextDisplay(item_recap),
            accessory=discord.ui.Thumbnail(media=media_item.public_url if media_item.upload_success else media_item.url)
        )
        self.add_item(self.thumbnail_section)


class MediaProcessView(PaginatedLayoutView):
    def __init__(self, media_candidates: list[MediaItem], **kwargs):
        super().__init__(**kwargs)

        self.register_stage(Stage(
            name="Select Uploads and Configure",
            container_class=UploadConfigContainer, 
            item_filter=lambda item: True,
            controls_class=PageControls, 
            controls_args={
                "view": self, 
                "success_callback": self.overwrite_check, 
                "labels": ("Cancel", None, None, "Next"),
                "styles": (discord.ButtonStyle.danger, discord.ButtonStyle.secondary, discord.ButtonStyle.secondary, discord.ButtonStyle.primary),
                "emojis": (None, discord.PartialEmoji.from_str("left_btn:1286185850757058675"), discord.PartialEmoji.from_str("right_btn:1286185838874460251"), None),
                "enable_finish_func": lambda: any(item.upload_configured for item in self.items),
            },
        ))

        self.register_stage(Stage(
            name="Overwrite Confirmation",
            container_class=OverwriteToggleContainer,
            item_filter=lambda item: item.overwrite_risk,
            controls_class=PageControls,
            controls_args={
                "view": self, 
                "success_callback": self.category_check, 
                "labels": ("Cancel", None, None, "Next"),
                "styles": (discord.ButtonStyle.danger, discord.ButtonStyle.secondary, discord.ButtonStyle.secondary, discord.ButtonStyle.primary),
                "emojis": (None, discord.PartialEmoji.from_str("left_btn:1286185850757058675"), discord.PartialEmoji.from_str("right_btn:1286185838874460251"), None),
                "enable_finish_func": lambda: any(item.upload_ready for item in self.items),
            },
        ))

        self.register_stage(Stage(
            name="Catalog and Category Confirmation",
            container_class=CategorySchemaConfigContainer,
            item_filter=lambda item: (item.upload_ready and item.catalog_configured),
            controls_class=PageControls,
            controls_args={
                "view": self, 
                "success_callback": self.review, 
                "labels": ("Cancel", None, None, "Review"),
                "styles": (discord.ButtonStyle.danger, discord.ButtonStyle.secondary, discord.ButtonStyle.secondary, discord.ButtonStyle.primary),
                "emojis": (None, discord.PartialEmoji.from_str("left_btn:1286185850757058675"), discord.PartialEmoji.from_str("right_btn:1286185838874460251"), None),
                "enable_finish_func": lambda: any(item.catalog_ready for item in self.items),
            },
        ))

        self.register_stage(Stage(
            name="Review",
            container_class=ReviewContainer,
            item_filter=lambda item: (item.upload_ready and item.catalog_ready),
            controls_class=PageControls,
            controls_args={
                "view": self, 
                "success_callback": self.finish, 
                "cancel_callback": self.redo,
                "labels": ("Redo", None, None, "Upload!"),
                "styles": (discord.ButtonStyle.primary, discord.ButtonStyle.secondary, discord.ButtonStyle.secondary, discord.ButtonStyle.success),
                "emojis": (discord.PartialEmoji.from_str("↩️"), discord.PartialEmoji.from_str("left_btn:1286185850757058675"), discord.PartialEmoji.from_str("right_btn:1286185838874460251"), None),
            },
        ))

        self.register_stage(Stage(
            name="Final Status",
            container_class=UploadStatusContainer,
            item_filter=lambda item: (item.upload_ready and item.catalog_ready),
            controls_class=PageControls,
            controls_args={
                "view": self, 
                "labels": ("Exit", None, None, "Exit"),
                "styles": (discord.ButtonStyle.danger, discord.ButtonStyle.secondary, discord.ButtonStyle.secondary, discord.ButtonStyle.danger),
                "emojis": (None, discord.PartialEmoji.from_str("left_btn:1286185850757058675"), discord.PartialEmoji.from_str("right_btn:1286185838874460251"), None),
            },
        ))

        self.items = media_candidates
        debug_log("Init finish")

    async def redo(self, interaction: discord.Interaction):
        await self.set_stage(0, interaction)

    async def overwrite_check(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        
        uploads = [item for item in self.items if item.upload_configured]
        debug_log(f"Requested uploads: {uploads}", 2)

        # Asynchronously check if any of the paths already exist in the bucket and set overwrite flag accordingly
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            file_exist_checks = {executor.submit(bucket_client.file_exists, item.path): item for item in uploads}

            for file_exists_response in concurrent.futures.as_completed(file_exist_checks):
                item = file_exist_checks[file_exists_response]
                item.overwrite_risk = file_exists_response.result()

        if any(not item.upload_ready for item in uploads):
            debug_log("Overwrite risk found!")
            await self.set_stage(1, interaction)
            return

        await self.skip_next_stage(interaction)

    async def category_check(self, interaction: discord.Interaction):
        uploads = [item for item in self.items if item.upload_ready]
        debug_log(f"Ready uploads: {uploads}", 2)

        not_catalog_ready = [item for item in uploads if not item.catalog_ready]
        if not_catalog_ready:
            for item in not_catalog_ready:
                manager = get_active_catalogs().get(item.catalog)
                category_schema = manager.get_category_schema(item.category)

                fields = category_schema.get("fields")
                defaults = category_schema.get("defaults")

                if item.category_schema_data is None:
                    item.category_schema_data = {}
                for field in fields:
                    if field not in item.category_schema_data:
                        item.category_schema_data[field] = defaults.get(field)

                fuzzy_matches = {
                    item.public_url: ["url", "link", "public_url", "src", "data"],
                    item.name.split(".")[0]: ["name", "title", "label", "alt", "altname", "filename"],
                }

                for data_piece, field_names in fuzzy_matches.items():
                    for field_name in field_names:
                        if field_name in fields:
                            item.category_schema_data[field_name] = data_piece
            
            await self.set_stage(2, interaction)
            return

        await self.skip_next_stage(interaction)

    async def review(self, interaction: discord.Interaction):
        await self.set_stage(3, interaction)

    async def finish(self, interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()

        uploads = [item for item in self.items if item.upload_ready and item.catalog_ready]

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            upload_futures = {executor.submit(bucket_client.upload_file, item.path, item.data): item for item in uploads}

            for upload_future in concurrent.futures.as_completed(upload_futures):
                item = upload_futures[upload_future]
                try:
                    upload_future.result()
                except Exception as e:
                    item.upload_success = False
                else:
                    item.upload_success = True

        items_to_catalog = [item for item in uploads if item.upload_success and item.catalog_configured and item.catalog_ready]

        debug_log(f"Items to upload: {uploads}", 2)
        debug_log(f"Items to catalog: {items_to_catalog}", 2)
        items_by_catalog = {}
        items_by_schema_data = {}
        catalog_successes = []
        catalog_urls = []

        for item in items_to_catalog:
            items_by_catalog.setdefault(item.catalog, {}).setdefault(item.category, []).append(item.category_schema_data)
            items_by_schema_data[frozenset(item.category_schema_data.items())] = item

        debug_log(f"Items by catalog: {items_by_catalog}", 2)

        for catalog, items_by_category in items_by_catalog.items():
            debug_log(f"Adding items to catalog {catalog}")
            debug_log(f"Items by category: {items_by_category}", 2)
            try:
                catalog_successes.extend(get_active_catalogs().get(catalog).add_batch_to_category(items_by_category))
                catalog_urls.append(get_active_catalogs().get(catalog).html_url)
            except Exception as e:
                debug_log(f"Error adding items to catalog: {e}", 1)

        for category_schema_data in catalog_successes:
            items_by_schema_data[frozenset(category_schema_data.items())].catalog_success = True

        if catalog_urls:
            self._stages[self.stage_num + 1].header_class = discord.ui.TextDisplay
            self._stages[self.stage_num + 1].header_args = {
                "content": "## Catalogs Updated:\n" + "\n".join(f"- {url}" for url in catalog_urls)
            }

        await self.set_stage(4, interaction)