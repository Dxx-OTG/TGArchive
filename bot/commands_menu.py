from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonCommands

# The bot is command-free: /start opens the menu hub and everything is done from there (or by pasting
# a @username/link). /start is the only command left.
COMMANDS = [
    BotCommand(command="start", description="Open the menu"),
]


async def setup_commands(bot: Bot) -> None:
    """Set the command menu shown next to the text field. Single command set: the bot is
    admin-only (see bot/middlewares/admin_only.py)."""
    await bot.set_my_commands(COMMANDS, scope=BotCommandScopeDefault())
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
