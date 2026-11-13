import discord


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