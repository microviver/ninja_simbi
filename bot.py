import json
import os
import asyncio
import logging
from datetime import datetime

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

MESSAGES_PER_MINUTE = config.get("messages_per_minute", 20)
LOG_FILE = config.get("log_file", "bot.log")


# ============================================================
# LOGGING AVANZADO
# ============================================================

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(formatter)
logger.addHandler(ch)

fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
fh.setLevel(logging.INFO)
fh.setFormatter(formatter)
logger.addHandler(fh)


# ============================================================
# ESTADOS DE USUARIO + ESTADÍSTICAS
# ============================================================

USER_STATE = {}

STATS = {
    "total_campaigns": 0,
    "total_sent": 0,
    "total_failed": 0,
    "total_blocked": 0,
    "last_campaign": None,
}


# ============================================================
# FUNCIONES AUXILIARES
# ============================================================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def get_rate_limit_delay() -> float:
    if MESSAGES_PER_MINUTE <= 0:
        return 0.0
    return 60.0 / MESSAGES_PER_MINUTE


async def safe_reply_text(message, text, **kwargs):
    try:
        await message.reply_text(text, **kwargs)
    except Exception:
        await message.reply_text(text)


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
        [InlineKeyboardButton("📊 Panel de administración", callback_data="admin_panel")],
        [InlineKeyboardButton("ℹ️ Ayuda", callback_data="help")]
    ]

    await update.message.reply_text(
        "🤖 *Bot de mensajes promocionales*\n\n"
        "Envía mensajes a todos los miembros de tu canal o grupo.\n\n"
        "Elige una opción:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"🆔 Tu ID es: `{user_id}`", parse_mode="Markdown")


# ✅ NOVO COMANDO: OBTÉM O ID DO CANAL/GRUPO
async def getchatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_id = chat.id
    chat_title = chat.title or "Privado"
    chat_type = chat.type

    await update.message.reply_text(
        f"🆔 *Chat ID:* `{chat_id}`\n"
        f"📛 *Nombre:* {chat_title}\n"
        f"📦 *Tipo:* {chat_type}",
        parse_mode="Markdown"
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in USER_STATE:
        del USER_STATE[user_id]
        await update.message.reply_text("❌ Operación cancelada. Usa /start para empezar de nuevo.")
    else:
        await update.message.reply_text("No hay ninguna operación en curso.")


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text("❌ No tienes permiso para usar el panel de administración.")
        return

    keyboard = [
        [InlineKeyboardButton("🚀 Iniciar campaña", callback_data="start_campaign")],
        [InlineKeyboardButton("📊 Ver estadísticas", callback_data="show_stats")],
        [InlineKeyboardButton("⚙️ Ver configuración", callback_data="show_config")]
    ]

    await update.message.reply_text(
        "📊 *Panel de administración*\n\n"
        "Elige una opción:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


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

    data = query.data

    if data == "start_campaign":
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

    elif data == "help":
        await query.edit_message_text(
            "ℹ️ *Cómo usar el bot*\n\n"
            "1️⃣ Pulsa *Iniciar campaña*\n"
            "2️⃣ Envía el canal o grupo\n"
            "3️⃣ Espera a que se extraigan los miembros\n"
            "4️⃣ Envía el mensaje que quieras reenviar\n"
            "5️⃣ Confirma el envío\n\n"
            "Usa /start para volver al menú.",
            parse_mode="Markdown"
        )

    elif data == "admin_panel":
        keyboard = [
            [InlineKeyboardButton("🚀 Iniciar campaña", callback_data="start_campaign")],
            [InlineKeyboardButton("📊 Ver estadísticas", callback_data="show_stats")],
            [InlineKeyboardButton("⚙️ Ver configuración", callback_data="show_config")]
        ]
        await query.edit_message_text(
            "📊 *Panel de administración*\n\n"
            "Elige una opción:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    elif data == "show_stats":
        last = STATS["last_campaign"]
        if last:
            last_text = (
                f"📅 Última campaña:\n"
                f"- Chat: {last.get('chat_name')}\n"
                f"- Miembros: {last.get('members_count')}\n"
                f"- Enviados: {last.get('sent')}\n"
                f"- Bloqueados: {last.get('blocked')}\n"
                f"- Errores: {last.get('failed')}\n"
                f"- Fecha: {last.get('timestamp')}\n"
            )
        else:
            last_text = "No hay campañas anteriores."

        await query.edit_message_text(
            "📊 *Estadísticas generales*\n\n"
            f"Campañas totales: {STATS['total_campaigns']}\n"
            f"Mensajes enviados: {STATS['total_sent']}\n"
            f"Bloqueados: {STATS['total_blocked']}\n"
            f"Errores: {STATS['total_failed']}\n\n"
            f"{last_text}",
            parse_mode="Markdown"
        )

    elif data == "show_config":
        await query.edit_message_text(
            "⚙️ *Configuración actual*\n\n"
            f"Mensajes por minuto: {MESSAGES_PER_MINUTE}\n"
            f"Archivo de log: `{LOG_FILE}`\n"
            f"Admins: {', '.join([str(i) for i in ADMIN_IDS])}\n",
            parse_mode="Markdown"
        )

    elif data == "confirm_send":
        user_data = USER_STATE.get(user_id, {})
        members = user_data.get("members", [])
        from_chat_id = user_data.get("from_chat_id")
        message_id = user_data.get("message_id")
        chat_name = user_data.get("chat_name", "desconocido")

        if not members or not from_chat_id or not message_id:
            await query.edit_message_text("❌ Faltan datos para enviar la campaña.")
            return

        await query.edit_message_text(
            "📤 *Empezando a enviar mensajes...*\n\nEsto puede tardar un poco.",
            parse_mode="Markdown"
        )

        success = 0
        failed = 0
        blocked = 0
        delay = get_rate_limit_delay()

        logger.info(f"Inicio de campaña por usuario {user_id} hacia chat '{chat_name}' con {len(members)} miembros.")

        for idx, member_id in enumerate(members, start=1):
            try:
                await context.bot.copy_message(
                    chat_id=member_id,
                    from_chat_id=from_chat_id,
                    message_id=message_id
                )
                success += 1

                if success % 20 == 0:
                    try:
                        await query.edit_message_text(
                            f"📤 *Enviando mensajes...*\n\nProgreso: {success}/{len(members)}",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass

                if delay > 0:
                    await asyncio.sleep(delay)

            except Exception as e:
                error_msg = str(e).lower()
                if "blocked" in error_msg:
                    blocked += 1
                else:
                    failed += 1
                logger.error(f"Error enviando a {member_id}: {e}")

        STATS["total_campaigns"] += 1
        STATS["total_sent"] += success
        STATS["total_failed"] += failed
        STATS["total_blocked"] += blocked
        STATS["last_campaign"] = {
            "chat_name": chat_name,
            "members_count": len(members),
            "sent": success,
            "failed": failed,
            "blocked": blocked,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        USER_STATE[user_id] = {}

        await query.edit_message_text(
            f"✅ *Campaña completada*\n\n"
            f"📢 Chat: {chat_name}\n"
            f"👥 Miembros: {len(members)}\n\n"
            f"✔️ Enviados: {success}\n"
            f"🚫 Bloqueados: {blocked}\n"
            f"❌ Errores: {failed}\n\n"
            f"Éxito: {(success / len(members) * 100):.1f}%",
            parse_mode="Markdown"
        )

        logger.info(
            f"Campaña terminada. Chat='{chat_name}', miembros={len(members)}, "
            f"enviados={success}, bloqueados={blocked}, errores={failed}"
        )

    elif data == "cancel":
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
                await safe_reply_text(
                    update.message,
                    f"❌ No pude acceder al chat\n\nError: {str(e)}"
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
                    "❌ No encontré miembros reales en este chat.\n\n"
                    "Comprueba que tiene miembros y que el bot tiene permisos."
                )
                del USER_STATE[user_id]
                return

            USER_STATE[user_id] = {
                "step": "awaiting_message",
                "members": [u.id for u in real_users],
                "chat_name": getattr(chat, "title", channel_input)
            }

            logger.info(
                f"Usuario {user_id} ha seleccionado chat '{USER_STATE[user_id]['chat_name']}' "
                f"con {len(real_users)} miembros."
            )

            await update.message.reply_text(
                f"✅ *Miembros extraídos*\n\n"
                f"📢 Chat: {USER_STATE[user_id]['chat_name']}\n"
                f"👥 Total: *{len(real_users)}*\n\n"
                f"Ahora envíame el mensaje de la campaña.",
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"Error extrayendo miembros: {e}")
            await safe_reply_text(update.message, f"❌ Error extrayendo miembros\n\nDetalles: {str(e)}")
            if user_id in USER_STATE:
                del USER_STATE[user_id]

    elif state.get("step") == "awaiting_message":
        msg = update.message
        members_count = len(state.get("members", []))

        USER_STATE[user_id]["from_chat_id"] = msg.chat_id
        USER_STATE[user_id]["message_id"] = msg.message_id
        USER_STATE[user_id]["step"] = "ready_to_send"

        keyboard = [
            [InlineKeyboardButton("✅ Enviar a todos", callback_data="confirm_send")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]
        ]

        await msg.reply_text(
            f"📋 *Vista previa de la campaña*\n\n"
            f"👥 Miembros que recibirán el mensaje: *{members_count}*\n\n"
            f"Este es el mensaje que se enviará a cada uno.\n\n"
            f"¿Quieres seguir adelante?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

        logger.info(
            f"Usuario {user_id} ha definido el mensaje de campaña "
            f"(from_chat_id={msg.chat_id}, message_id={msg.message_id}) "
            f"para {members_count} miembros."
        )


# ============================================================
# MAIN
# ============================================================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("getchatid", getchatid))  # ← NOVO COMANDO
    app.add_handler(CommandHandler("cancelar", cancel_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.add_handler(MessageHandler(
        (filters.ALL & ~filters.COMMAND),
        receive_message
    ))

    logger.info("🤖 Bot iniciado y listo para funcionar")
    app.run_polling()


if __name__ == "__main__":
    main()
