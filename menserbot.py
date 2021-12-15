import discord
from discord.ext import commands
from discord.commands import Option

from datetime import datetime
import asyncio
import signal

from menser import parse_url
from helper import *
from config import TOKEN_MENSERBOT, DEBUG_GUILDS, GET_DELAY

bot = commands.Bot('!')
messages = []

async def getMenu(mensa: Mensa, veggie: bool) -> str:
    url = f'https://www.max-manager.de/daten-extern/sw-erlangen-nuernberg/xml/mensa-{mensa.name.lower()}.xml'
    menu = await parse_url(url=url, veggie=veggie, loop=bot.loop)
    return menu


@bot.slash_command(guild_ids=DEBUG_GUILDS, description='Sich automatisch aktualisierneder Mensaplan')
async def mensa(ctx, mensa: Option(str, "Mensa", choices=[mensa.value for mensa in Mensa]), veggie: Option(bool, "Veggie", default=True)):
    mensaEnum = Mensa(mensa)
    embed = discord.Embed(title=f'Speiseplan {mensaEnum.value}', description="*Lädt...*", color=0x49db39 if veggie else 0x03a1fc)

    interaction = await ctx.respond(embed=embed)
    interaction_message = await interaction.original_message()
    real_message = await interaction_message.channel.fetch_message(interaction_message.id)

    bot.loop.create_task(job(message=real_message, embed=embed, mensa=mensaEnum, veggie=veggie))
    insert_values_into_table(guild_id=real_message.guild.id, mensa=mensaEnum, channel_id=real_message.channel.id, message_id=real_message.id, veggie=veggie)
    messages.append(real_message)



@bot.event
async def on_ready():
    dbList = get_info_from_db()
    for db in dbList:
        try:
            guild = bot.get_guild(db.guild_id)
            channel = guild.get_channel(db.channel_id)
            msg = await channel.fetch_message(db.message_id)
            messages.append(msg)
            bot.loop.create_task(job(message=msg, embed=msg.embeds[0], mensa=db.mensa, veggie=db.veggie))

        except discord.NotFound:
            print('message not found on startup, deleting...')
            delete_from_db(guild_id=db.guild_id, channel_id=db.channel_id, message_id=db.message_id)
            pass
    print(f'{bot.user} has connected.')


# @tasks.loop(seconds=5)
async def job(message, embed, mensa: Mensa, veggie: bool):
    #ich würde ja lieber die eingebaute tasks.loop verwenden aber dann kann man den task nur ein mal starten
    while True:
        embed.title = f'Speiseplan {mensa.value} {"💚" if veggie else ""}'
        embed.description = str(await getMenu(mensa=mensa, veggie=veggie))
        embed.set_footer(text=f"Stand:  {datetime.now().strftime('%d.%m.%Y - %H:%M:%S')}")
        await message.edit(embed=embed)
        await asyncio.sleep(GET_DELAY)


class MyView(discord.ui.View):
    def __init__(self,):
        super().__init__()
        # super().__init__(timeout=60)

    @discord.ui.button(label=f'{Mensa.SUED.value}', style=discord.ButtonStyle.danger)
    async def sued_callback(self, button, interaction):
        embed = self.message.embeds[0]
        embed.title = f'Speiseplan {Mensa.SUED.value}'
        embed.description = '*Lädt...*'

        self.clear_items()

        await interaction.response.edit_message(embed=embed, view=self)
        #job.start(message=self.message, embed=embed, mensa='sued')
        bot.loop.create_task(job(message=self.message, embed=embed, mensa=Mensa.SUED, veggie=True))
        insert_values_into_table(guild_id=self.message.guild.id, mensa=Mensa.SUED, channel_id=self.message.channel.id, message_id=self.message.id, veggie=False)
    
    @discord.ui.button(label=f'{Mensa.LMP.value}', style=discord.ButtonStyle.danger)
    async def lmp_callback(self, button, interaction):
        embed = self.message.embeds[0]
        embed.title = f'Speiseplan {Mensa.LMP.value}'
        embed.description = '*Lädt...*'
        
        self.clear_items()

        await interaction.response.edit_message(embed=embed, view=self)
        # job.start(message=self.message, embed=embed, mensa='lmp')
        bot.loop.create_task(job(message=self.message, embed=embed, mensa=Mensa.LMP, veggie=True))
        insert_values_into_table(guild_id=self.message.guild.id, mensa=Mensa.LMP, channel_id=self.message.channel.id, message_id=self.message.id, veggie=False)
        
    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        await self.message.edit(view=self)

async def mensaCommand(message: discord.Message):
    embed = discord.Embed(title="Speiseplan", description="Bitte Mensa wählen...", color=0x03a1fc)
    view = MyView()
    #hab es nicht hingekriegt das schöner zu machen
    msg: discord.Message
    msg = view.message = await message.channel.send(embed=embed, view=view)
    messages.append(msg)

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    if message.author.bot:
        return

    elif message.content.startswith('!mensa'):
        await mensaCommand(message)
    
    elif message.content.startswith('!ping'):
        await message.channel.send('pong')

    print(message.content)

async def on_shutdown():
    if not messages:
        return
    for message in messages:
        message.embeds[0].description = '*Beendet...*'
        message.embeds[0].remove_footer()
        try:
            await message.edit(embed=message.embeds[0], view=None)
        except discord.NotFound:
            print('message not found on shutdown, deleting...')
            delete_from_db(guild_id=message.guild.id, channel_id=message.channel.id, message_id=message.id)
            pass



if __name__ == '__main__':
    check_if_table_exists()

    #der ganze scheiß ist nur hier weil ich die Nachricht löschen will, wenn der Bot beendet wird
    loop = bot.loop

    try:
        loop.add_signal_handler(signal.SIGINT, lambda: loop.stop())
        loop.add_signal_handler(signal.SIGTERM, lambda: loop.stop())
    except NotImplementedError:
        pass

    async def runner():
        try:
            await bot.start(TOKEN_MENSERBOT)
        finally:
            if not bot.is_closed():
                await bot.close()

    def stop_loop_on_completion(f):
        loop.stop()

    future = asyncio.ensure_future(runner(), loop=loop)
    future.add_done_callback(stop_loop_on_completion)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print('Received signal to terminate bot and event loop.')
    finally:
        loop.run_until_complete(on_shutdown())

        future.remove_done_callback(stop_loop_on_completion)
        print('Cleaning up tasks.')
        cleanup_loop(loop)
           