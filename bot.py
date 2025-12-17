import logging
import asyncio
import random
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

# --- Logger Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Database Setup (MongoDB) ---
mongo_client = AsyncIOMotorClient(Config.MONGO_URL)
db = mongo_client["ReactionBotDB"]
# Collection structure: { "user_id": int, "chat_id": int, "chat_title": str, "emojis": list }
chats_col = db["connected_chats"]

# --- Bot Client Setup ---
app = Client(
    "ReactionBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

# --- Constants ---
# The 4 emotions/emojis available for selection
AVAILABLE_EMOJIS = ["👍", "❤️", "🔥", "🎉"]

# --- Helper Functions ---

def get_start_keyboard(bot_username):
    """Generates buttons to add bot to Group or Channel."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add to Group", url=f"http://t.me/{bot_username}?startgroup=true"),
            InlineKeyboardButton("➕ Add to Channel", url=f"http://t.me/{bot_username}?startchannel=true")
        ]
    ])

async def get_chat_selection_keyboard(user_id):
    """Generates a list of connected chats for the user to configure."""
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
    """Generates the 4 emoji buttons with tick marks if selected."""
    doc = await chats_col.find_one({"user_id": user_id, "chat_id": int(chat_id)})
    current_emojis = doc.get("emojis", []) if doc else []

    buttons = []
    row = []
    for emoji in AVAILABLE_EMOJIS:
        # Check if emoji is currently active
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
        "Here is how to use me:\n"
        "1. Click the buttons below to add me to a Group or Channel.\n"
        "2. Once added, I will send the `Chat ID` in that group.\n"
        "3. Copy that ID and send it here to connect the chat.\n"
        "4. Use /chat to configure reactions."
    )
    await message.reply_text(text, reply_markup=get_start_keyboard(me.username))

@app.on_message(filters.new_chat_members)
async def added_to_group(client: Client, message: Message):
    """Detects when bot is added to a group and sends the ID."""
    me = await client.get_me()
    for member in message.new_chat_members:
        if member.id == me.id:
            try:
                await message.reply_text(
                    f"**✅ Bot Successfully Added!**\n\n"
                    f"The ID of this chat is: `{message.chat.id}`\n\n"
                    f"➡️ Copy this ID and send it to me in Private Message to connect."
                )
            except Exception as e:
                logger.error(f"Could not send message in {message.chat.id}: {e}")

@app.on_message(filters.regex(r"^-100\d+") & filters.private)
async def connect_chat_handler(client: Client, message: Message):
    """
    Handles the user sending a Chat ID (starts with -100 for supergroups/channels).
    Verifies the bot is actually in that chat before saving.
    """
    try:
        chat_id_input = int(message.text)
        user_id = message.from_user.id
        
        msg_wait = await message.reply_text("🔄 Verifying connection...")

        # Verify bot is member and get Chat Title
        try:
            chat_info = await client.get_chat(chat_id_input)
        except Exception:
            await msg_wait.edit("❌ I cannot find that chat. Make sure I am an Admin there!")
            return

        # Save to MongoDB
        existing = await chats_col.find_one({"user_id": user_id, "chat_id": chat_id_input})
        if existing:
            await msg_wait.edit(f"⚠️ **{chat_info.title}** is already connected!")
        else:
            await chats_col.insert_one({
                "user_id": user_id,
                "chat_id": chat_id_input,
                "chat_title": chat_info.title,
                "emojis": [] # No reactions by default
            })
            await msg_wait.edit(f"✅ Successfully connected: **{chat_info.title}**\nUse /chat to configure reactions.")

    except ValueError:
        await message.reply_text("❌ Invalid ID format. It usually starts with -100.")

@app.on_message(filters.command("chat") & filters.private)
async def list_chats_handler(client: Client, message: Message):
    keyboard = await get_chat_selection_keyboard(message.from_user.id)
    if keyboard:
        await message.reply_text("👇 Select a connected chat to configure reactions:", reply_markup=keyboard)
    else:
        await message.reply_text("❌ You haven't connected any chats yet.\nSend me a Group/Channel ID first.")

# --- Callback Queries (Button Clicks) ---

@app.on_callback_query(filters.regex(r"select_chat_"))
async def show_emoji_options(client: Client, callback: CallbackQuery):
    chat_id = callback.data.split("_")[2]
    user_id = callback.from_user.id
    
    keyboard = await get_emoji_keyboard(chat_id, user_id)
    await callback.message.edit_text(f"Select reactions for Chat ID `{chat_id}`:", reply_markup=keyboard)

@app.on_callback_query(filters.regex(r"toggle_"))
async def toggle_emoji(client: Client, callback: CallbackQuery):
    # Format: toggle_{chat_id}_{emoji}
    _, chat_id, emoji = callback.data.split("_")
    user_id = callback.from_user.id
    chat_id = int(chat_id)

    # Fetch current DB state
    doc = await chats_col.find_one({"user_id": user_id, "chat_id": chat_id})
    if not doc:
        await callback.answer("Error: Chat not found.", show_alert=True)
        return

    current_list = doc.get("emojis", [])

    # Toggle Logic
    if emoji in current_list:
        current_list.remove(emoji)
        action = "Removed"
    else:
        current_list.append(emoji)
        action = "Added"

    # Update DB
    await chats_col.update_one(
        {"user_id": user_id, "chat_id": chat_id},
        {"$set": {"emojis": current_list}}
    )

    # Refresh Keyboard
    keyboard = await get_emoji_keyboard(chat_id, user_id)
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer(f"{emoji} {action}")

@app.on_callback_query(filters.regex("back_to_chats"))
async def back_button(client: Client, callback: CallbackQuery):
    keyboard = await get_chat_selection_keyboard(callback.from_user.id)
    await callback.message.edit_text("👇 Select a connected chat to configure reactions:", reply_markup=keyboard)

# --- The Auto-Reaction Logic ---

@app.on_message(filters.group | filters.channel)
async def auto_reaction_watcher(client: Client, message: Message):
    """
    Checks every incoming message in groups/channels.
    If the chat is in DB and has emojis selected, reacts randomly.
    """
    chat_id = message.chat.id
    
    # Find if this chat is configured in DB (Check any document with this chat_id)
    # Note: If multiple users connected the same chat, we pick the first config found.
    # To support multiple configs, logic would need adjustment, but assuming 1 owner per chat here.
    doc = await chats_col.find_one({"chat_id": chat_id})
    
    if doc and doc.get("emojis"):
        active_emojis = doc["emojis"]
        # Select ONE random emoji from the selected list
        reaction = random.choice(active_emojis)
        
        try:
            await message.react(reaction)
        except Exception as e:
            # Common errors: Bot not admin, or reaction restricted in chat
            pass

# --- Run ---
if __name__ == "__main__":
    print("Bot Started...")
    app.run()
      
