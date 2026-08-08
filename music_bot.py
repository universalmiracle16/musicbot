import os
import sqlite3
import random
import time
import yt_dlp
import subprocess
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = "8649416842:AAFXUmxKqU9zPDA8w8zXglfFf2GUJwAt_g0"
MUSIC_FOLDER = "/opt/render/project/src/music"  # Для Render
# MUSIC_FOLDER = "D:/MusicBot/music"  # Для локального запуска

# ===================== БАЗА ДАННЫХ =====================
def init_db():
    conn = sqlite3.connect('music_library.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artist TEXT,
            file_path TEXT NOT NULL,
            source TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_song(title, artist, file_path, source="Spotify"):
    conn = sqlite3.connect('music_library.db')
    cursor = conn.cursor()
    cursor.execute("INSERT INTO songs (title, artist, file_path, source) VALUES (?, ?, ?, ?)", 
                   (title, artist, file_path, source))
    conn.commit()
    conn.close()

def search_song(query):
    conn = sqlite3.connect('music_library.db')
    cursor = conn.cursor()
    cursor.execute("SELECT title, artist, file_path FROM songs WHERE title LIKE ? OR artist LIKE ? LIMIT 10", 
                   (f'%{query}%', f'%{query}%'))
    results = cursor.fetchall()
    conn.close()
    return results

# ===================== ПОИСК НА SPOTIFY =====================
def search_spotify(query, max_results=15):
    try:
        from spotdl import search
        from spotdl.types.song import Song
        
        results = search(query, limit=max_results)
        songs = []
        
        for item in results:
            if isinstance(item, Song):
                songs.append({
                    'title': item.name,
                    'uploader': item.artists[0] if item.artists else 'Неизвестен',
                    'url': item.url,
                    'source': 'Spotify'
                })
        return songs
    except Exception as e:
        print(f"Ошибка Spotify: {e}")
        return []

# ===================== ПОИСК НА SOUNDCLOUD =====================
def search_soundcloud(query, max_results=10):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'force_generic_extractor': False,
        'socket_timeout': 10,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_query = f"scsearch{max_results}:{query}"
            info = ydl.extract_info(search_query, download=False)
            
            if info and 'entries' in info:
                results = []
                for entry in info['entries']:
                    if entry:
                        title = entry.get('title', 'Неизвестно')
                        uploader = entry.get('uploader', 'Неизвестен')
                        url = entry.get('url', '')
                        
                        results.append({
                            'title': title,
                            'uploader': uploader,
                            'url': url,
                            'source': 'SoundCloud'
                        })
                return results
    except Exception as e:
        print(f"Ошибка SoundCloud: {e}")
    
    return []

# ===================== ПОИСК НА YOUTUBE (ЗАПАСНОЙ) =====================
def search_youtube(query, max_results=10):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'force_generic_extractor': False,
        'socket_timeout': 10,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_query = f"ytsearch{max_results}:{query}"
            info = ydl.extract_info(search_query, download=False)
            
            if info and 'entries' in info:
                results = []
                for entry in info['entries']:
                    if entry:
                        title = entry.get('title', 'Неизвестно')
                        uploader = entry.get('uploader', 'Неизвестен')
                        video_id = entry.get('id', '')
                        url = f"https://www.youtube.com/watch?v={video_id}"
                        
                        results.append({
                            'title': title,
                            'uploader': uploader,
                            'url': url,
                            'source': 'YouTube'
                        })
                return results
    except Exception as e:
        print(f"Ошибка YouTube: {e}")
    
    return []

# ===================== УНИВЕРСАЛЬНЫЙ ПОИСК =====================
def search_all(query, max_results=15):
    results = search_spotify(query, max_results)
    if results:
        return results
    
    results = search_soundcloud(query, max_results)
    if results:
        return results
    
    results = search_youtube(query, max_results)
    return results

# ===================== СКАЧИВАНИЕ =====================
async def download_from_spotify(url, title, artist):
    try:
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        output_path = os.path.join(MUSIC_FOLDER, f"{safe_title}.mp3")
        
        cmd = f'spotdl "{url}" --output "{output_path}" --format mp3'
        process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        
        if os.path.exists(output_path) and os.path.getsize(output_path) > 100000:
            return safe_title, artist, output_path
        return None, None, None
    except Exception as e:
        print(f"Ошибка скачивания Spotify: {e}")
        return None, None, None

async def download_from_url(url, title, uploader):
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': f'{MUSIC_FOLDER}/%(title)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'nooverwrites': False,
        'socket_timeout': 30,
    }
    
    try:
        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
            for file in os.listdir(MUSIC_FOLDER):
                if file.endswith('.mp3'):
                    file_path = os.path.join(MUSIC_FOLDER, file)
                    if os.path.getctime(file_path) > time.time() - 60:
                        new_path = os.path.join(MUSIC_FOLDER, f"{safe_title}.mp3")
                        if not os.path.exists(new_path):
                            os.rename(file_path, new_path)
                            return safe_title, uploader, new_path
                        return safe_title, uploader, file_path
            return safe_title, uploader, os.path.join(MUSIC_FOLDER, f"{safe_title}.mp3")
    except Exception as e:
        print(f"Ошибка скачивания: {e}")
        return None, None, None

# ===================== КОМАНДЫ =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎵 *Музыкальный Бот*\n\n"
        "Просто напиши название песни или исполнителя.\n"
        "Ищу на Spotify → SoundCloud → YouTube.",
        parse_mode='Markdown'
    )

# ===================== ПОИСК =====================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if len(query) < 2:
        await update.message.reply_text("❌ Слишком короткий запрос")
        return
    
    # Проверяем базу
    results = search_song(query)
    if results:
        title, artist, file_path = results[0]
        if os.path.exists(file_path):
            with open(file_path, 'rb') as audio:
                await update.message.reply_audio(audio=audio, title=title, performer=artist)
            return
    
    await update.message.reply_text(f"🔍 Поиск по запросу: {query}")
    videos = search_all(query, max_results=15)
    
    if not videos:
        await update.message.reply_text("❌ Ничего не найдено")
        return
    
    context.user_data['search_results'] = videos
    context.user_data['search_page'] = 0
    context.user_data['search_query'] = query
    
    await show_page(update, context, 0)

# ===================== ПОКАЗ СПИСКА (МИНИМАЛИСТИЧНО) =====================
async def show_page(update, context, page):
    videos = context.user_data.get('search_results', [])
    if not videos:
        await update.message.reply_text("❌ Результаты устарели")
        return
    
    per_page = 10
    total_pages = (len(videos) + per_page - 1) // per_page
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, len(videos))
    page_videos = videos[start_idx:end_idx]
    
    # Минималистичный список — только названия
    message = "🎵 *Выберите трек*\n\n"
    
    for i, video in enumerate(page_videos, start=start_idx + 1):
        message += f"{i}. {video['uploader']} - {video['title']}\n"
    
    # Кнопки с номерами
    buttons = []
    row = []
    for i in range(start_idx + 1, end_idx + 1):
        row.append(InlineKeyboardButton(str(i), callback_data=f"select_{i-1}"))
        if len(row) == 5:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    
    # Кнопки навигации
    nav_buttons = []
    if total_pages > 1:
        nav_buttons.append(InlineKeyboardButton(f"{page + 1} / {total_pages}", callback_data="page_info"))
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"page_{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    # Кнопка "Искать по исполнителю"
    query = context.user_data.get('search_query', '')
    if query:
        buttons.append([InlineKeyboardButton(f"🔍 Искать по исполнителю: {query}", callback_data=f"search_artist_{query}")])
    
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel")])
    
    reply_markup = InlineKeyboardMarkup(buttons)
    
    if page == 0:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

# ===================== ОБРАБОТЧИК КНОПОК =====================
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "cancel":
        await query.edit_message_text("❌ Отменено")
        return
    
    if data == "page_info":
        await query.answer()
        return
    
    if data.startswith("page_"):
        page = int(data.split("_")[1])
        context.user_data['search_page'] = page
        await show_page(update, context, page)
        return
    
    if data.startswith("search_artist_"):
        artist = data.replace("search_artist_", "")
        # Ищем по исполнителю
        await query.edit_message_text(f"🔍 Ищу исполнителя: {artist}")
        # Очищаем результаты и ищем заново
        videos = search_all(artist, max_results=15)
        if videos:
            context.user_data['search_results'] = videos
            context.user_data['search_page'] = 0
            context.user_data['search_query'] = artist
            await show_page(update, context, 0)
        else:
            await query.message.reply_text("❌ Ничего не найдено по исполнителю")
        return
    
    if data.startswith("select_"):
        index = int(data.split("_")[1])
        videos = context.user_data.get('search_results', [])
        
        if not videos or index >= len(videos):
            await query.edit_message_text("❌ Результаты устарели")
            return
        
        selected = videos[index]
        
        await query.edit_message_text(f"⬇️ {selected['uploader']} - {selected['title']}")
        
        if selected['source'] == 'Spotify':
            title, artist, file_path = await download_from_spotify(selected['url'], selected['title'], selected['uploader'])
        else:
            title, artist, file_path = await download_from_url(selected['url'], selected['title'], selected['uploader'])
        
        if title and os.path.exists(file_path):
            add_song(title, artist, file_path, selected['source'])
            
            size_bytes = os.path.getsize(file_path)
            size_mb = size_bytes / (1024 * 1024)
            size_str = f"{size_mb:.1f} MB"
            
            # Получаем длительность через ffprobe (если есть)
            duration_str = "??:??"
            try:
                import subprocess
                result = subprocess.run([
                    'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1', file_path
                ], capture_output=True, text=True)
                if result.stdout:
                    duration_sec = float(result.stdout.strip())
                    minutes = int(duration_sec // 60)
                    seconds = int(duration_sec % 60)
                    duration_str = f"{minutes}:{seconds:02d}"
            except:
                pass
            
            caption = f"{title} • {artist} • {duration_str} • {size_str}"
            
            with open(file_path, 'rb') as audio:
                await query.message.reply_audio(
                    audio=audio,
                    title=title,
                    performer=artist,
                    caption=caption
                )
        else:
            await query.message.reply_text("❌ Ошибка скачивания")

# ===================== ЗАПУСК =====================
def main():
    init_db()
    if not os.path.exists(MUSIC_FOLDER):
        os.makedirs(MUSIC_FOLDER)
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    print("🎵 Бот запущен!")
    print(f"📁 Музыка в: {MUSIC_FOLDER}")
    app.run_polling()

if __name__ == "__main__":
    main()