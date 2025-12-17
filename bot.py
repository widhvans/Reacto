import logging
import asyncio
import random
import os
from aiohttp import web
from pyrogram import Client, filters, idle, enums
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

# --- Logger Setup ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Database Setup (MongoDB) ---
mongo_client = AsyncIOMotorClient(Config.MONGO_URL)
db = mongo_client["ReactionBotDB"]
chats_col = db["connected_chats"]

# --- Bot Client Setup ---
app = Client(
    "ReactionBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

# --- Constants ---
AVAILABLE_EMOJIS = ["👍", "❤️", "🔥", "🎉"]

# --- Web Server for Health Check ---
async def health_check(request):
    return web.Response(text="Bot is Running!", status=200)

async def start_web_server():
    server = web.Application()
    server.router.add_get("/", health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info(f"Web server started on port {port}")

# --- Helper Functions ---
def get_start_keyboard(bot_username):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add to Group", url=f"http://t.me/{bot_username}?startgroup=true"),
            InlineKeyboardButton("➕ Add to Channel", url=f"http://t.me/{bot_username}?startchannel=true")
        ]
    ])

async def get_chat_selection_keyboard(user_id):
    cursor = chats_col.find({"user_id": user_id})
    buttons = []
    async for document in cursor:
        chat_title = document.get("chat_title", "Unknown Chat")
        chat_id = document.get("chat_id")
        buttons.append([InlineKeyboardButton(f"📢 {chat_title}", callback_data=f"select_chat_{chat_id}")])
    
    if not buttons:
        return None
    return InlineKeyboardMarkup(buttons)

async def get_emoji_keyboard(chat_id, user_id):
    doc = await chats_col.find_one({"user_id": user_id, "chat_id": int(chat_id)})
    current_emojis = doc.get("emojis", []) if doc else []

    buttons = []
    row = []
    for emoji in AVAILABLE_EMOJIS:
        is_active = emoji in current_emojis
        text = f"{emoji} {'✅' if is_active else ''}"
        callback_data = f"toggle_{chat_id}_{emoji}"
        row.append(InlineKeyboardButton(text, callback_data=callback_data))
    
    buttons.append(row)
    buttons.append([InlineKeyboardButton("🔙 Back to Chats", callback_data="back_to_chats")])
    return InlineKeyboardMarkup(buttons)

# --- Handlers ---

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    me = await client.get_me()
    text = (
        "**👋 Professional Reaction Bot**\n\n"
        "1. Add me to a Group/Channel.\n"
        "2. Copy the ID I send there.\n"
        "3. Send the ID here to connect.\n"
        "4. Use /chat to configure."
    )
    await message.reply_text(text, reply_markup=get_start_keyboard(me.username))

@app.on_message(filters.new_chat_members)
async def added_to_group(client: Client, message: Message):
    me = await client.get_me()
    for member in message.new_chat_members:
        if member.id == me.id:
            try:
                await message.reply_text(
                    f"**✅ Bot Added!**\nID: `{message.chat.id}`\nSend this ID to me in PM."
                )
            except Exception as e:
                logger.error(f"Could not send welcome message: {e}")

@app.on_message(filters.regex(r"^-100\d+") & filters.private)
async def connect_chat_handler(client: Client, message: Message):
    try:
        chat_id_input = int(message.text)
        user_id = message.from_user.id
        msg_wait = await message.reply_text("🔄 Verifying...")

        try:
            chat_info = await client.get_chat(chat_id_input)
        except Exception as e:
            logger.error(f"Chat verification failed: {e}")
            await msg_wait.edit("❌ I cannot find that chat. Make sure I am an Admin!")
            return

        existing = await chats_col.find_one({"user_id": user_id, "chat_id": chat_id_input})
        if existing:
            await msg_wait.edit(f"⚠️ **{chat_info.title}** is already connected!")
        else:
            await chats_col.insert_one({
                "user_id": user_id,
                "chat_id": chat_id_input,
                "chat_title": chat_info.title,
                "emojis": []
            })
            await msg_wait.edit(f"✅ Connected: **{chat_info.title}**\nUse /chat to configure.")
    except ValueError:
        await message.reply_text("❌ Invalid ID format.")

@app.on_message(filters.command("chat") & filters.private)
async def list_chats_handler(client: Client, message: Message):
    keyboard = await get_chat_selection_keyboard(message.from_user.id)
    if keyboard:
        await message.reply_text("👇 Select chat to configure:", reply_markup=keyboard)
    else:
        await message.reply_text("❌ No connected chats.")

@app.on_callback_query(filters.regex(r"select_chat_"))
async def show_emoji_options(client: Client, callback: CallbackQuery):
    chat_id = callback.data.split("_")[2]
    user_id = callback.from_user.id
    keyboard = await get_emoji_keyboard(chat_id, user_id)
    await callback.message.edit_text(f"Select reactions for `{chat_id}`:", reply_markup=keyboard)

@app.on_callback_query(filters.regex(r"toggle_"))
async def toggle_emoji(client: Client, callback: CallbackQuery):
    _, chat_id, emoji = callback.data.split("_")
    user_id = callback.from_user.id
    chat_id = int(chat_id)

    doc = await chats_col.find_one({"user_id": user_id, "chat_id": chat_id})
    if not doc:
        await callback.answer("Error: Chat not found.", show_alert=True)
        return

    current_list = doc.get("emojis", [])
    if emoji in current_list:
        current_list.remove(emoji)
        action = "Removed"
    else:
        current_list.append(emoji)
        action = "Added"

    await chats_col.update_one(
        {"user_id": user_id, "chat_id": chat_id},
        {"$set": {"emojis": current_list}}
    )

    keyboard = await get_emoji_keyboard(chat_id, user_id)
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer(f"{emoji} {action}")

@app.on_callback_query(filters.regex("back_to_chats"))
async def back_button(client: Client, callback: CallbackQuery):
    keyboard = await get_chat_selection_keyboard(callback.from_user.id)
    await callback.message.edit_text("👇 Select chat:", reply_markup=keyboard)

# --- DEBUGGED AUTO REACTION LOGIC ---

@app.on_message(filters.group | filters.channel)
async def auto_reaction_watcher(client: Client, message: Message):
    chat_id = message.chat.id
    
    doc = await chats_col.find_one({"chat_id": chat_id})
    
    if not doc:
        return

    if not doc.get("emojis"):
        logger.info(f"Chat {chat_id} is connected but has NO emojis selected.")
        return

    active_emojis = doc["emojis"]
    reaction_emoji = random.choice(active_emojis)
    
    logger.info(f"Attempting to react with {reaction_emoji} in {chat_id}")

    try:
        # Simplified reaction logic compatible with older Pyrogram versions
        await message.react(reaction_emoji)
        logger.info(f"✅ Success: Reacted {reaction_emoji} in {chat_id}")
    except Exception as e:
        logger.error(f"❌ Reaction Failed in {chat_id}: {e}")

# --- Main ---
async def main():
    logger.info("Starting Web Server...")
    await start_web_server()
    logger.info("Starting Bot...")
    await app.start()
    logger.info("Bot & Web Server are Running!")
    await idle()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    
