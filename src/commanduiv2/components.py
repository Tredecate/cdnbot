import discord
import inspect

from utils import Stage, PostInitMeta, Timer, debug_log


class ToggleButton(discord.ui.Button):
    def __init__(
            self,
            true_appearance: tuple[str, discord.ButtonStyle] = ("✅", discord.ButtonStyle.success),
            false_appearance: tuple[str, discord.ButtonStyle] = ("❌", discord.ButtonStyle.grey),
            initial_state: bool = False,
            attribute_holder = None,
            attribute_name: str = None,
        ):
        self.attribute_holder = attribute_holder
        self.attribute_name = attribute_name

        self._state = None
        self._initial_state = initial_state

        self.true_appearance = true_appearance
        self.false_appearance = false_appearance

        label, style = true_appearance if self.state else false_appearance
        super().__init__(label=label, style=style)

    @property
    def state(self) -> bool:
        if self.attribute_holder and self.attribute_name:
            self._state = getattr(self.attribute_holder, self.attribute_name)

        if self._state is None:
            self._state = self._initial_state
        
        return self._state

    @state.setter
    def state(self, value: bool):
        self._state = value
        if self.attribute_holder and self.attribute_name:
            setattr(self.attribute_holder, self.attribute_name, value)

        self.label, self.style = self.true_appearance if self.state else self.false_appearance

    async def callback(self, interaction: discord.Interaction):
        self.state = not self.state

        await self.view.update_page(interaction)


class ModalSpawnButton(discord.ui.Button):
    def __init__(self, label: str, modal: discord.ui.Modal, disabled: bool = False):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.modal = modal
        self.disabled = disabled

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(self.modal)


class CountableContainer[ViewT: discord.ui.View](discord.ui.Container[ViewT]):
    @property
    def total_children_count(self) -> int:
        count = 1
        for child in self.walk_children():
            count += 1
        return count


class PageControls(discord.ui.ActionRow):
    def __init__(
            self, view: discord.ui.View, 
            success_callback=None, cancel_callback=None, 
            labels=("Cancel", "Back", "Next", "Finish"), 
            styles=(discord.ButtonStyle.danger, discord.ButtonStyle.secondary, discord.ButtonStyle.primary, discord.ButtonStyle.success),
            emojis=(None, None, None, None),
            enable_finish_func=lambda: True
            ):
        super().__init__()
        self.success_callback = success_callback
        self.cancel_callback = cancel_callback
        assert hasattr(view, "_page"), "The view must have a '_page' attribute to use PageControls."

        self.cancel_button.label, self.back_button.label, self.next_button.label, self.finish_button.label = labels
        self.cancel_button.style, self.back_button.style, self.next_button.style, self.finish_button.style = styles
        self.cancel_button.emoji, self.back_button.emoji, self.next_button.emoji, self.finish_button.emoji = emojis

        self.back_button.disabled = view.is_first_page
        self.next_button.disabled = view.is_last_page

        self.finish_button.disabled = not enable_finish_func()

    @discord.ui.button()
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.cancel_callback:
            return await self.cancel_callback(interaction) if inspect.iscoroutinefunction(self.cancel_callback) else self.cancel_callback(interaction)

        debug_log("No cancel_callback provided, stopping the view and deleting the original response.")
        if not interaction.response.is_done():
            await interaction.response.defer()
        self.view.stop()
        await interaction.delete_original_response()

    @discord.ui.button()
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.view.is_first_page:
            await interaction.response.defer()
            return

        await self.view.prev_page(interaction)

    @discord.ui.button()
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.view.is_last_page:
            await interaction.response.defer()
            return

        await self.view.next_page(interaction)

    @discord.ui.button()
    async def finish_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.success_callback:
            return await self.success_callback(interaction) if inspect.iscoroutinefunction(self.success_callback) else self.success_callback(interaction)
        
        debug_log("No success_callback provided, stopping the view and deleting the original response.")
        if not interaction.response.is_done():
            await interaction.response.defer()
        self.view.stop()
        await interaction.delete_original_response()


class PaginatedLayoutView(discord.ui.LayoutView, metaclass=PostInitMeta):
    def __init__(self, interaction: discord.Interaction = None):
        super().__init__(timeout=300)
        self._interaction = interaction
        self._owner = interaction.user
        self._page = self._page if hasattr(self, "_page") else 0
        self._pages = self._pages if hasattr(self, "_pages") else []

        self._stage = self._stage if hasattr(self, "_stage") else 0
        self._stages = self._stages if hasattr(self, "_stages") else []

        self.items = self.items if hasattr(self, "items") else []

    def __post_init__(self):
        self._divide_into_pages()
        self._render_page()

    @property
    def stage(self) -> Stage:
        return self._stages[self._stage] if self._stages else Stage()

    @property
    def stage_num(self) -> int:
        return self._stage

    @property
    def is_first_page(self) -> bool:
        return self._page <= 0

    @property
    def is_last_page(self) -> bool:
        return self._page >= len(self._pages) - 1

    async def set_stage(self, stage_index: int, interaction: discord.Interaction):
        Timer.start()
        debug_log(f"Setting stage to {stage_index} (current: {self._stage})")
        if stage_index < 0 or stage_index >= len(self._stages):
            await interaction.response.defer()
            return None

        self._stage = stage_index
        self._page = 0
        self._divide_into_pages()
        await self.update_page(interaction)
        Timer.stop()
        return self

    async def skip_next_stage(self, interaction: discord.Interaction):
        self._stage += 1
        await self.stage.controls_class(**self.stage.controls_args).finish_button.callback(interaction)

    async def next_page(self, interaction: discord.Interaction):
        if self.is_last_page:
            await interaction.response.defer()
            return None

        self._page += 1
        await self.update_page(interaction)
        return self

    async def prev_page(self, interaction: discord.Interaction):
        if self.is_first_page:
            await interaction.response.defer()
            return None

        self._page -= 1
        await self.update_page(interaction)
        return self

    async def update_page(self, interaction: discord.Interaction):
        self._render_page()
        if interaction.response.is_done():
            await interaction.edit_original_response(view=self)
        else:
            await interaction.response.edit_message(view=self)

    def register_stage(self, stage_data: Stage, stage_index: int = None, carry_forward: bool = False):
        if stage_index is None:
            self._stages.append(stage_data)
            stage_index = len(self._stages) - 1
        else:
            self._stages.insert(stage_index, stage_data)

        # Copy attributes from the previous stage that aren't defined on the new stage
        if stage_index > 0 and carry_forward:
            previous_stage = self._stages[stage_index - 1]
            for attr in dir(previous_stage):
                if not attr.startswith("_") and (not hasattr(stage_data, attr) or getattr(stage_data, attr) is None):
                    setattr(stage_data, attr, getattr(previous_stage, attr))

    def _render_page(self):
        Timer.start()
        self.clear_items()

        self._build_header()
        self._build_page()
        self._build_controls()
        Timer.stop()

    def _divide_into_pages(self, max_components_per_page: int = 40):
        Timer.start()
        self.clear_items()
        self._build_header()
        self._build_controls()
        self._pages.clear()
        current_count = self.total_children_count

        filtered_items = [item for item in self.items if self.stage.item_filter(item)]
        if not filtered_items:
            self._pages.append([])
            return

        # Temporary container to calculate children count
        temp_container = self.stage.container_class(self, filtered_items[0])
        container_count = temp_container.total_children_count
        max_items_per_page = max(1, (max_components_per_page - current_count) // container_count)

        debug_log(f"{len(filtered_items)} items, {container_count} container children, {current_count} current children, {max_items_per_page} max items per page.", 2)

        for i in range(0, len(filtered_items), max_items_per_page):
            self._pages.append(filtered_items[i:i + max_items_per_page])
        Timer.stop()

    def _build_header(self):
        pass

    def _build_page(self):
        for item in self._pages[self._page]:
            self.add_item(self.stage.container_class(self, item))

    def _build_controls(self):
        self.add_item(self.stage.controls_class(**self.stage.controls_args))
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user == self._owner:
            return True

        await interaction.response.defer()
        return False