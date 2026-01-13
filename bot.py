import json
import os
import asyncio
import logging

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch


# ============================================================
# 🔧 CARGAR CONFIG.JSON
# ============================================================

CONFIG_PATH = "config.json"

if not os.path.exists(CONFIG_PATH):
    raise FileNotFoundError("No se encontró el archivo config.json")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

BOT_TOKEN = config["bot_token"]
API_ID = config["api_id"]
API_HASH = config["api_hash"]
ADMIN_IDS = config["admin_ids"]


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# ESTADOS DE USUARIO
# ============================================================

USER_STATE = {}


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def is_admin(user_id: int) -> bool:
    """Comprueba si el usuario está autorizado a usar el bot."""
    return user_id in ADMIN_IDS


# ============================================================
# COMANDOS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ No tienes permiso para usar este bot.")
        return

    keyboard = [
        [InlineKeyboardButton("🚀 Iniciar campaña promocional", callback_data="start_campaign")],
        [InlineKeyboardButton("ℹ️ Ayuda", callback_data="help")]
    ]

    await update.message.reply_text(
        "🤖 *Bot de mensajes promocionales*\n\n"
        "Envía mensajes a todos los miembros de tu canal o grupo.\n\n"
        "Pulsa el botón para empezar:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Devuelve el ID del usuario."""
    user_id = update.effective_user.id
    await update.message.reply_text(f"🆔 Tu ID es: `{user_id}`", parse_mode="Markdown")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in USER_STATE:
        del USER_STATE[user_id]
        await update.message.reply_text("❌ Operación cancelada. Usa /start para empezar de nuevo.")
    else:
        await update.message.reply_text("No hay ninguna operación en curso.")


# ============================================================
# CALLBACKS DE BOTONES
# ============================================================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    if not is_admin(user_id):
        await query.edit_message_text("❌ No tienes permiso.")
        return

    # Iniciar campaña
    if query.data == "start_campaign":
        USER_STATE[user_id] = {"step": "awaiting_channel"}

        await query.edit_message_text(
            "📢 *Paso 1: Indica el canal o grupo*\n\n"
            "Envíame el ID o el @username.\n\n"
            "Ejemplos:\n"
            "• `@micomunidad`\n"
            "• `-1001234567890`\n\n"
            "Escribe /cancelar para parar.",
            parse_mode="Markdown"
        )

    # Ayuda
    elif query.data == "help":
        await query.edit_message_text(
            "ℹ️ *Cómo usar el bot*\n\n"
            "1️⃣ Pulsa *Iniciar campaña*\n"
            "2️⃣ Envía el canal o grupo\n"
            "3️⃣ Espera a que se extraigan los miembros\n"
            "4️⃣ Escribe tu mensaje promocional\n"
            "5️⃣ Confirma el envío\n\n"
            "Usa /start para volver al menú.",
            parse_mode="Markdown"
        )

    # Confirmar envío
    elif query.data == "confirm_send":
        user_data = USER_STATE.get(user_id, {})
        members = user_data.get("members", [])
        message = user_data.get("message")

        if not members or not message:
            await query.edit_message_text("❌ Faltan datos para enviar.")
            return

        await query.edit_message_text("📤 *Enviando mensajes...*\n\nDame un momento...", parse_mode="Markdown")

        success = 0
        failed = 0
        blocked = 0

        for member_id in members:
            try:
                await context.bot.send_message(
                    chat_id=member_id,
                    text=message,
                    parse_mode="Markdown"
                )
                success += 1

                if success % 20 == 0:
                    await query.edit_message_text(
                        f"📤 *Enviando mensajes...*\n\n"
                        f"Enviados: {success}/{len(members)}",
                        parse_mode="Markdown"
                    )

                await asyncio.sleep(0.5)

            except Exception as e:
                error_msg = str(e).lower()
                if "blocked" in error_msg:
                    blocked += 1
                else:
                    failed += 1
                logger.error(f"Error enviando a {member_id}: {e}")

        USER_STATE[user_id] = {}

        await query.edit_message_text(
            f"✅ *Envío completado*\n\n"
            f"📊 *Resultados:*\n"
            f"✔️ Enviados: {success}\n"
            f"🚫 Bloqueado por: {blocked}\n"
            f"❌ Errores: {failed}\n"
            f"👥 Total: {len(members)}\n\n"
            f"Éxito: {(success / len(members) * 100):.1f}%",
            parse_mode="Markdown"
        )

    # Cancelar
    elif query.data == "cancel":
        if user_id in USER_STATE:
            del USER_STATE[user_id]
        await query.edit_message_text("❌ Operación cancelada. Usa /start para empezar de nuevo.")


# ============================================================
# RECEPCIÓN DE MENSAJES
# ============================================================

async def receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        return

    if user_id not in USER_STATE:
        return

    state = USER_STATE[user_id]

    # Paso 1 — Recibir canal o grupo
    if state.get("step") == "awaiting_channel":
        channel_input = update.message.text.strip()

        await update.message.reply_text(
            "⏳ *Extrayendo miembros...*\n\nEsto puede tardar un poco.",
            parse_mode="Markdown"
        )

        try:
            client = TelegramClient("session_bot", API_ID, API_HASH)
            await client.start(bot_token=BOT_TOKEN)

            try:
                if channel_input.startswith("@"):
                    chat = await client.get_entity(channel_input)
                else:
                    chat = await client.get_entity(int(channel_input))
            except Exception as e:
                await client.disconnect()
                await update.message.reply_text(
                    f"❌ *No pude acceder al chat*\n\n"
                    f"Error: {str(e)}",
                    parse_mode="Markdown"
                )
                del USER_STATE[user_id]
                return

            participants = []
            offset = 0
            limit = 100

            while True:
                result = await client(GetParticipantsRequest(
                    channel=chat,
                    filter=ChannelParticipantsSearch(""),
                    offset=offset,
                    limit=limit,
                    hash=0
                ))

                if not result.users:
                    break

                participants.extend(result.users)
                offset += len(result.users)

                if len(result.users) < limit:
                    break

            real_users = [u for u in participants if not u.bot and not u.deleted]

            await client.disconnect()

            if len(real_users) == 0:
                await update.message.reply_text(
                    "❌ *No encontré miembros reales en este chat.*",
                    parse_mode="Markdown"
                )
                del USER_STATE[user_id]
                return

            USER_STATE[user_id] = {
                "step": "awaiting_message",
                "members": [u.id for u in real_users],
                "chat_name": getattr(chat, "title", channel_input)
            }

            await update.message.reply_text(
                f"✅ *Miembros extraídos*\n\n"
                f"📢 Chat: {USER_STATE[user_id]['chat_name']}\n"
                f"👥 Total: *{len(real_users)}*\n\n"
                f"Ahora envíame el mensaje promocional.\n"
                f"Escribe /cancelar para parar.",
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"Error extrayendo miembros: {e}")
            await update.message.reply_text(
                f"❌ *Error extrayendo miembros*\n\n"
                f"Detalles: {str(e)}",
                parse_mode="Markdown"
            )
            if user_id in USER_STATE:
                del USER_STATE[user_id]

    # Paso 2 — Recibir mensaje promocional
    elif state.get("step") == "awaiting_message":
        message_text = update.message.text
        members_count = len(state.get("members", []))

        USER_STATE[user_id]["message"] = message_text
        USER_STATE[user_id]["step"] = "ready_to_send"

        keyboard = [
            [InlineKeyboardButton("✅ Enviar", callback_data="confirm_send")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]
        ]

        await update.message.reply_text(
            f"📋 *Vista previa*\n\n"
            f"👥 Miembros que recibirán el mensaje: *{members_count}*\n\n"
            f"📝 Mensaje:\n"
            f"{'─' * 30}\n"
            f"{message_text}\n"
            f"{'─' * 30}\n\n"
            f"¿Quieres seguir adelante?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


# ============================================================
# MAIN
# ============================================================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("cancelar", cancel_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_message))

    logger.info("🤖 Bot iniciado y listo para funcionar")
    app.run_polling()


if __name__ == "__main__":
    main()
