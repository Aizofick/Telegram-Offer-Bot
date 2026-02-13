import asyncio
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InputMediaAnimation,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

API_TOKEN = ''
ADMIN_CHAT_ID = -12345
CHANNEL_CHAT_ID = -12345

pending_messages = {}
admin_messages = {}
media_groups = {}
media_group_timers = {}
approved_albums = {}

async def send_album_to_admin(media_group_id, context, user):
    msgs = media_groups[media_group_id]
    msgs = sorted(msgs, key=lambda x: x.message_id)
    first_caption = msgs[0].caption if msgs[0].caption else ""

    media = []
    for i, m in enumerate(msgs):
        cap = first_caption if i == 0 else None
        if m.photo:
            media.append(InputMediaPhoto(media=m.photo[-1].file_id, caption=cap))
        elif m.video:
            media.append(InputMediaVideo(media=m.video.file_id, caption=cap))
        elif m.animation:
            media.append(InputMediaAnimation(media=m.animation.file_id, caption=cap))
        elif m.document and getattr(m.document, "mime_type", None) == "image/gif":
            media.append(InputMediaDocument(media=m.document.file_id, caption=cap))

    approved_albums[str(msgs[0].message_id)] = media

    await context.bot.send_media_group(ADMIN_CHAT_ID, media)

    admin_caption = f"""
    Новое сообщение от: {user.full_name} ({user.id})
    Ник: @{user.username or 'нет ника'}

    Текст сообщения:
    {first_caption or '(Нет текста)'}
    """.strip()
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Опубликовать", callback_data=f"approve:{msgs[0].message_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"reject:{msgs[0].message_id}")
        ]
    ])
    admin_message = await context.bot.send_message(
        ADMIN_CHAT_ID,
        admin_caption,
        reply_markup=keyboard,
    )
    pending_messages[str(msgs[0].message_id)] = msgs[0]
    admin_messages[str(msgs[0].message_id)] = (ADMIN_CHAT_ID, admin_message.message_id)
    media_groups.pop(media_group_id, None)
    media_group_timers.pop(media_group_id, None)

    user_chat_id = msgs[0].chat_id
    await context.bot.send_message(user_chat_id,
        "Ваш пост принят на рассмотрение и отправлен администраторам!"
    )

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    text = msg.text.strip() if msg.text else ""
    clip_caption = msg.caption.strip() if msg.caption else ""
    user = msg.from_user

    if text.startswith("/start"):
        await msg.reply_text(
            "Привет! Это бот для предложки.\n"
            "Отправьте сюда текст, фото, альбом, видео или GIF — и оно отправится на рассмотрение администраторам."
        )
        return

    if msg.media_group_id:
        mgid = msg.media_group_id
        if mgid not in media_groups:
            media_groups[mgid] = []
        media_groups[mgid].append(msg)

        if mgid in media_group_timers:
            media_group_timers[mgid].cancel()
        async def timer():
            await asyncio.sleep(2)
            await send_album_to_admin(mgid, context, user)
        media_group_timers[mgid] = asyncio.create_task(timer())
        return

    await msg.reply_text("Ваш пост принят на рассмотрение и отправлен администраторам!")

    is_media = msg.photo or msg.video or msg.animation or (
        msg.document and getattr(msg.document, "mime_type", None) == "image/gif"
    )
    if is_media:
        admin_caption = f"""
        Новое сообщение от: {user.full_name} ({user.id})
        Ник: @{user.username or 'нет ника'}

        Текст сообщения:
        {clip_caption or '(Нет текста)'}

        Подпись к изображению:
        {clip_caption or '(Без подписи)'}
        """.strip()
    else:
        admin_caption = f"""
        Новое сообщение от: {user.full_name} ({user.id})
        Ник: @{user.username or 'нет ника'}

        Текст сообщения:
        {text or '(Нет текста)'}
        """.strip()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Опубликовать", callback_data=f"approve:{msg.message_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"reject:{msg.message_id}")
        ]
    ])
    admin_message = None
    if msg.photo:
        admin_message = await context.bot.send_photo(
            ADMIN_CHAT_ID,
            msg.photo[-1].file_id,
            caption=admin_caption,
            reply_markup=keyboard
        )
    elif msg.video:
        admin_message = await context.bot.send_video(
            ADMIN_CHAT_ID,
            msg.video.file_id,
            caption=admin_caption,
            reply_markup=keyboard
        )
    elif msg.animation:
        admin_message = await context.bot.send_animation(
            ADMIN_CHAT_ID,
            msg.animation.file_id,
            caption=admin_caption,
            reply_markup=keyboard
        )
    elif msg.document and getattr(msg.document, "mime_type", None) == "image/gif":
        admin_message = await context.bot.send_document(
            ADMIN_CHAT_ID,
            msg.document.file_id,
            caption=admin_caption,
            reply_markup=keyboard
        )
    else:
        admin_message = await context.bot.send_message(
            ADMIN_CHAT_ID,
            admin_caption,
            reply_markup=keyboard
        )
    pending_messages[str(msg.message_id)] = msg
    if admin_message:
        admin_messages[str(msg.message_id)] = (ADMIN_CHAT_ID, admin_message.message_id)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, msg_id = query.data.split(":")
    orig_msg = pending_messages.get(msg_id)
    admin_msg_info = admin_messages.get(msg_id)

    if not orig_msg or not admin_msg_info:
        try:
            await query.edit_message_text("Сообщение не найдено или уже обработано.", reply_markup=None)
        except Exception:
            pass
        return

    chat_id, message_id = admin_msg_info
    admin_user = query.from_user
    operator = f"{admin_user.full_name} (@{admin_user.username or 'нет ника'})"

    feedback_text = ""
    if action == "approve":
        feedback_text = "Ваш пост одобрен и опубликован!"

        album_media = approved_albums.pop(msg_id, None)
        if album_media:
            await context.bot.send_media_group(CHANNEL_CHAT_ID, album_media)
        elif orig_msg.photo:
            await context.bot.send_photo(CHANNEL_CHAT_ID, orig_msg.photo[-1].file_id, caption=orig_msg.caption)
        elif orig_msg.video:
            await context.bot.send_video(CHANNEL_CHAT_ID, orig_msg.video.file_id, caption=orig_msg.caption)
        elif orig_msg.animation:
            await context.bot.send_animation(CHANNEL_CHAT_ID, orig_msg.animation.file_id, caption=orig_msg.caption)
        elif orig_msg.document and getattr(orig_msg.document, "mime_type", None) == "image/gif":
            await context.bot.send_document(CHANNEL_CHAT_ID, orig_msg.document.file_id, caption=orig_msg.caption)
        elif orig_msg.text:
            await context.bot.send_message(CHANNEL_CHAT_ID, orig_msg.text)

        info_text = f"Пост опубликован.\nОператор: {operator}"
    else:
        feedback_text = "Ваш пост отклонён."
        info_text = f"Публикация отклонена.\nОператор: {operator}"

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=info_text,
            reply_markup=None
        )
    except Exception:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None
            )
        except Exception:
            pass

    try:
        await context.bot.send_message(orig_msg.chat_id, feedback_text)
    except Exception:
        pass

    pending_messages.pop(msg_id, None)
    admin_messages.pop(msg_id, None)

def main():
    app = ApplicationBuilder().token(API_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_private_message))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, handle_private_message))
    app.add_handler(MessageHandler(filters.VIDEO & filters.ChatType.PRIVATE, handle_private_message))
    app.add_handler(MessageHandler(filters.ANIMATION & filters.ChatType.PRIVATE, handle_private_message))
    app.add_handler(MessageHandler(filters.Document.MimeType("image/gif") & filters.ChatType.PRIVATE, handle_private_message))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()

if __name__ == '__main__':
    main()
